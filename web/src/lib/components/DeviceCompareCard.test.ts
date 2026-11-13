import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import DeviceCompareCard from './DeviceCompareCard.svelte';
import type { DeviceCompareResponse } from '$api/device-compare';
import { COMPARE_SCOPE, NOT_EXACT, periodWords, TOO_MANY_LISTED } from '$lib/utils/device-compare';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const IP = '192.168.1.30';
const HOUR = 3_600_000;
const NOW = Date.UTC(2026, 10, 13, 21, 7, 42);
const MINUTE = Date.UTC(2026, 10, 13, 21, 7);
const iso = (ms: number) => new Date(ms).toISOString();
const [A_FROM, A_TO, B_TO] = [MINUTE - 48 * HOUR, MINUTE - 24 * HOUR, MINUTE].map(iso);
const period = (total_bytes: number, destinations: number | null, from = A_FROM, to = A_TO) => ({
	from,
	to,
	total_bytes,
	destinations,
	list_complete: true,
	buckets_exact: true,
});
const COMPLETE: DeviceCompareResponse = {
	ip: IP,
	a: period(1_200_000_000, 3),
	b: period(3_400_000_000, 5, A_TO, B_TO),
	exact: true,
	complete: true,
	new: {
		total: 53,
		items: [
			{ ip: '192.0.2.81', org: 'AS64500 Example Networks', bytes: 900 },
			{ ip: '192.0.2.80', org: null, bytes: 20 },
		],
	},
	gone: { total: 1, items: [{ ip: '198.51.100.7', org: 'AS64511 Old Host', bytes: 4000 }] },
	changed: {
		total: 2,
		partial: false,
		items: [
			{ ip: '203.0.113.6', org: null, a_bytes: 50, b_bytes: 1050, delta: 1000 },
			{ ip: '203.0.113.5', org: null, a_bytes: 3000, b_bytes: 1000, delta: -2000 },
		],
	},
};

/** Each compare request waits for `answer`; any other request (the LAN policy) is a 404. */
let pending: { url: string; resolve: (r: unknown) => void }[] = [];
function answer(body: unknown, status = 200) {
	pending.shift()!.resolve({ ok: status < 400, status, json: async () => body });
}
const asked = () => pending.map((p) => new URL(p.url, 'http://x').searchParams);

beforeEach(() => {
	vi.useFakeTimers({ toFake: ['Date'] });
	vi.setSystemTime(NOW);
	pending = [];
	vi.stubGlobal(
		'fetch',
		vi.fn((url: string) =>
			String(url).startsWith('/api/moment/device-compare')
				? new Promise((resolve) => pending.push({ url: String(url), resolve }))
				: Promise.resolve({ ok: false, status: 404, json: async () => ({}) }),
		),
	);
});
afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

const compare = () => fireEvent.click(screen.getByRole('button', { name: 'Compare' }));
const INCOMPLETE = {
	...COMPLETE,
	a: { ...COMPLETE.a, list_complete: false },
	complete: false,
	new: null,
	gone: null,
	changed: { ...COMPLETE.changed!, total: 80, partial: true },
};

describe('DeviceCompareCard', () => {
	it('offers two back-to-back 24-hour periods ending now, with its scope, and asks nothing yet', () => {
		render(DeviceCompareCard, { ip: IP });
		expect(screen.getByLabelText<HTMLSelectElement>('Length').value).toBe('24h');
		const a = screen.getByLabelText<HTMLInputElement>('First period starts').value;
		const b = screen.getByLabelText<HTMLInputElement>('Second period starts').value;
		expect([new Date(a).getTime(), new Date(b).getTime()]).toEqual([MINUTE - 48 * HOUR, MINUTE - 24 * HOUR]);
		expect(screen.getByText(COMPARE_SCOPE)).toBeTruthy();
		expect(pending).toEqual([]);
	});

	it('sends the device and both periods, then shows the summary and the three lists', async () => {
		const { container } = render(DeviceCompareCard, { ip: IP });
		await compare();
		expect(screen.getByText('Comparing the two periods')).toBeTruthy();
		expect(Object.fromEntries(asked()[0])).toEqual({
			ip: IP,
			a_from: new Date(MINUTE - 48 * HOUR).toISOString(),
			a_to: new Date(MINUTE - 24 * HOUR).toISOString(),
			b_from: new Date(MINUTE - 24 * HOUR).toISOString(),
			b_to: new Date(MINUTE).toISOString(),
		});
		answer(COMPLETE);
		await screen.findByText(
			/^In the second period this device started connections to 53 new destinations and none to 1 earlier one\. Bytes went from 1\.2 GB to 3\.4 GB\.$/,
		);
		// which periods these are, in the browser's time
		expect(screen.getByText(`First period ${periodWords(A_FROM, A_TO)} · second period ${periodWords(A_TO, B_TO)}`)).toBeTruthy();

		const fresh = screen.getByRole('table', { name: 'New in the second period' });
		expect(within(fresh).getByText('AS64500 Example Networks')).toBeTruthy();
		expect(screen.getByText('and 51 more')).toBeTruthy();
		const gone = screen.getByRole('table', { name: 'No longer seen' });
		expect(within(gone).getByText('AS64511 Old Host')).toBeTruthy();
		expect(within(gone).getByText('4.0 KB')).toBeTruthy();
		const changed = screen.getByRole('table', { name: 'Largest changes' });
		// the arrow and the sign carry the direction
		expect(within(changed).getByText('+1.0 KB')).toBeTruthy();
		expect(within(changed).getByText('−2.0 KB')).toBeTruthy();
		expect(screen.getByText('Destinations seen in both periods, by the size of the change')).toBeTruthy();
		expect(screen.getByText(COMPARE_SCOPE)).toBeTruthy(); // still there with results
		expectNoNestedInteractive(container);
	});

	it('a shorter length moves both starts, and the periods stay back to back', async () => {
		render(DeviceCompareCard, { ip: IP });
		await fireEvent.change(screen.getByLabelText('Length'), { target: { value: '1h' } });
		await compare();
		const q = asked()[0];
		expect([q.get('a_from'), q.get('a_to'), q.get('b_to')]).toEqual(
			[MINUTE - 2 * HOUR, MINUTE - HOUR, MINUTE].map((t) => new Date(t).toISOString()),
		);
		expect(q.get('b_from')).toBe(q.get('a_to'));
	});

	it('clears the result as soon as an input changes, so a result always matches the inputs', async () => {
		render(DeviceCompareCard, { ip: IP });
		await compare();
		answer(COMPLETE);
		await screen.findByRole('table', { name: 'Largest changes' });
		await fireEvent.input(screen.getByLabelText('Second period starts'), { target: { value: '2026-11-12T10:00' } });
		expect(screen.queryByRole('table')).toBeNull();
		expect(screen.queryByText(/ · second period /)).toBeNull();
	});

	it('shows nothing from another device', async () => {
		const { rerender } = render(DeviceCompareCard, { ip: IP });
		await compare();
		answer(COMPLETE);
		await screen.findByRole('table', { name: 'Largest changes' });
		await rerender({ ip: '192.168.1.31' });
		expect(screen.queryByRole('table')).toBeNull();
	});

	it("shows the daemon's sentence when it refuses the periods", async () => {
		render(DeviceCompareCard, { ip: IP });
		await compare();
		answer({ error: 'The two periods must not overlap.' }, 400);
		expect(await screen.findByText("Couldn't compare these periods")).toBeTruthy();
		expect(screen.getByText('The two periods must not overlap.')).toBeTruthy();
	});

	it('asks for a start before sending anything', async () => {
		render(DeviceCompareCard, { ip: IP });
		await fireEvent.input(screen.getByLabelText('First period starts'), { target: { value: '' } });
		await compare();
		expect(screen.getByText('Pick when each period starts.')).toBeTruthy();
		expect(pending).toEqual([]);
	});

	it('says why new and gone are missing when a list was incomplete, and keeps the changes', async () => {
		render(DeviceCompareCard, { ip: IP });
		await compare();
		answer(INCOMPLETE);
		expect(await screen.findByText((text) => text.startsWith(TOO_MANY_LISTED))).toBeTruthy();
		expect(screen.queryByRole('table', { name: 'New in the second period' })).toBeNull();
		expect(screen.getByRole('heading', { name: 'Largest changes among destinations listed in both periods' })).toBeTruthy();
		expect(screen.getByRole('table', { name: 'Largest changes among destinations listed in both periods' })).toBeTruthy();
		// a lower bound: a destination left off a list may have changed too
		expect(screen.getByText('and at least 78 more')).toBeTruthy();
	});

	it('shows only the totals when the lists were estimates', async () => {
		render(DeviceCompareCard, { ip: IP });
		await compare();
		answer({ ...COMPLETE, a: { ...COMPLETE.a, buckets_exact: false, destinations: null }, exact: false, complete: false, new: null, gone: null, changed: null });
		expect(await screen.findByText(`${NOT_EXACT} Bytes went from 1.2 GB to 3.4 GB.`)).toBeTruthy();
		expect(screen.queryByRole('table')).toBeNull();
	});

	it('says so when the device started nothing in either period', async () => {
		render(DeviceCompareCard, { ip: IP });
		await compare();
		answer({ ...COMPLETE, a: period(0, 0), b: period(0, 0, A_TO, B_TO), new: { total: 0, items: [] }, gone: { total: 0, items: [] }, changed: { total: 0, items: [], partial: false } });
		expect(await screen.findByText('This device started no connections in either period.')).toBeTruthy();
		expect(screen.queryByRole('table')).toBeNull();
	});

	it('is one compare at a time: Compare is off while one runs', async () => {
		render(DeviceCompareCard, { ip: IP });
		await compare();
		expect(screen.getByRole('button', { name: 'Compare' })).toHaveProperty('disabled', true);
		answer({ error: 'Two other look-ups are being worked out right now; try again in a minute.' }, 503);
		await screen.findByText('Two other look-ups are being worked out right now; try again in a minute.');
		expect(screen.getByRole('button', { name: 'Compare' })).toHaveProperty('disabled', false);
		await compare();
		answer(COMPLETE);
		await screen.findByRole('table', { name: 'Largest changes' });
		expect(screen.queryByText(/try again in a minute/)).toBeNull();
	});
});
