import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import { goto } from '$app/navigation';
import { refreshPage } from '$lib/stores/pageRefresh';
import type { DhcpTimeline } from '$lib/api/dhcp-timeline';
import { LAN_POLICY } from '../../../../e2e/visual/fixtures/drilldown';
import { DHCP_MAC, DHCP_TIMELINE, DHCP_TIMELINE_EMPTY } from '../../../../e2e/visual/fixtures/dhcp';
import { expectNoNestedInteractive } from '../../../tests/nested-interactive';

// NET-263: one device's DHCP transactions, by ?mac= over the range pills

const pageStore = vi.hoisted(() => ({ value: null as unknown as ReturnType<typeof writable> }));
vi.mock('$app/stores', async () => {
	const { writable: w } = await import('svelte/store');
	pageStore.value = w({ url: new URL('http://localhost/tools/dhcp-timeline'), params: {} });
	return { page: pageStore.value };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const { default: Page } = await import('./+page.svelte');

const REGISTRY = {
	total: 1,
	devices: [{ mac: DHCP_MAC.toUpperCase(), ips: ['192.168.1.138'], hostnames: [], display_name: 'Office AP', manufacturer: null, friendly_name: null, category: 'infrastructure', first_seen: '', last_seen: '', is_new: false }],
};

let calls: URL[] = [];
type Reply = { ok: boolean; status: number; json: () => Promise<unknown> };
const ok = (body: unknown): Reply => ({ ok: true, status: 200, json: async () => body });
const failing = (status: number, error: string): Reply => ({ ok: false, status, json: async () => ({ error }) });

/** The daemon: the LAN policy, the registry, and the timeline (or an error with its reason). */
function stubDaemon(
	timeline: DhcpTimeline | Promise<never> | ((url: URL) => Promise<Reply>) | undefined,
	opts: { registry?: boolean; error?: string; status?: number } = {},
) {
	calls = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: string) => {
			const url = new URL(input, 'http://localhost');
			calls.push(url);
			if (url.pathname === '/api/network/lan') return { ok: true, status: 200, json: async () => LAN_POLICY };
			if (url.pathname === '/api/devices/registry') return opts.registry === false ? { ok: false, status: 500, json: async () => ({}) } : { ok: true, status: 200, json: async () => REGISTRY };
			if (timeline instanceof Promise) return timeline;
			if (typeof timeline === 'function') return timeline(url);
			if (url.pathname === '/api/dhcp/timeline' && timeline) return ok(timeline);
			return failing(opts.status ?? 400, opts.error ?? 'Enter a six-byte MAC address, such as aa:bb:cc:dd:ee:ff.');
		}),
	);
}

const goTo = (query = '') => pageStore.value.set({ url: new URL(`http://localhost/tools/dhcp-timeline${query}`), params: {} });
const timelineCall = () => calls.find((u) => u.pathname === '/api/dhcp/timeline');
const timelineCalls = () => calls.filter((u) => u.pathname === '/api/dhcp/timeline');
const OTHER_MAC = '02:00:5e:00:53:39';
const PRINTER = { ...DHCP_TIMELINE, mac: OTHER_MAC, transactions: [{ ...DHCP_TIMELINE.transactions[0], host_name: 'Printer', assigned_ip: '192.168.1.77' }] };
const table = () => screen.getByRole('table', { name: /DHCP transactions for/ });

describe('DHCP lease timeline page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.mocked(goto).mockClear();
		goTo();
	});

	it('asks for a device first, and reads nothing without one', async () => {
		stubDaemon(DHCP_TIMELINE);
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: 'DHCP lease timeline' })).toBeInTheDocument();
		expect(await screen.findByRole('heading', { name: 'Pick a device' })).toBeInTheDocument();
		expect(timelineCall()).toBeUndefined();
	});

	it('shows loading, not an empty list, before the answer', () => {
		goTo(`?mac=${DHCP_MAC}`);
		stubDaemon(new Promise(() => {}) as Promise<never>);
		render(Page);
		expect(screen.getAllByRole('status').some((s) => s.getAttribute('aria-busy') === 'true')).toBe(true);
		expect(screen.queryByRole('table')).not.toBeInTheDocument();
	});

	it('lists the transactions over the URL window, named from the registry, each with its line', async () => {
		goTo(`?mac=${DHCP_MAC}&range=7d`);
		stubDaemon(DHCP_TIMELINE);
		const { container } = render(Page);
		expect(await screen.findByRole('heading', { name: 'Office AP' })).toBeInTheDocument();
		const sent = timelineCall()!;
		expect(sent.searchParams.get('mac')).toBe(DHCP_MAC);
		expect((Date.parse(sent.searchParams.get('to')!) - Date.parse(sent.searchParams.get('from')!)) / 3_600_000).toBe(168);
		expect(within(table()).getAllByRole('row')).toHaveLength(DHCP_TIMELINE.transactions.length + 1);
		expect(screen.getByText('ACK observed from 192.168.1.1 for 192.168.1.138. OFFER also observed.')).toBeInTheDocument();
		expect(screen.getByText('NAK observed from 192.168.1.1 for 192.168.1.139. Server message: “lease not found”.')).toBeInTheDocument();
		expect(screen.getByText('ACK, DISCOVER, OFFER, REQUEST')).toBeInTheDocument();
		// Zeek's server is shown as what it recorded only when it isn't the one endpoint
		expect(screen.queryByText('Zeek recorded 192.168.1.1')).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
		expectNoNestedInteractive(container);
	});

	// OLD CODE: it('links the packets where two servers took part, …' expected 2 links (PR #263 review: every row has one)
	it('names no sender where two servers took part, and links every row to its packets by time', async () => {
		goTo(`?mac=${DHCP_MAC}`);
		stubDaemon(DHCP_TIMELINE);
		render(Page);
		expect(await screen.findByText('NAK observed. Server endpoints in this transaction: 192.168.1.1 and 192.168.1.5.')).toBeInTheDocument();
		const links = screen.getAllByRole('link', { name: /^See the captured packets from \d/ });
		expect(links).toHaveLength(DHCP_TIMELINE.transactions.length);
		expect(new Set(links.map((a) => a.getAttribute('aria-label'))).size).toBe(links.length);
		const q = new URL(links[0].getAttribute('href')!, 'http://x').searchParams;
		expect(q.get('filter')).toBe(`dhcp && dhcp.hw.mac_addr == ${DHCP_MAC}`);
		expect(screen.getByRole('columnheader', { name: /Server endpoints/ })).toBeInTheDocument();
		expect(screen.getAllByText('for 24 h')).toHaveLength(2);
	});

	it('says why a device can have no DHCP messages', async () => {
		goTo(`?mac=${DHCP_MAC}`);
		stubDaemon(DHCP_TIMELINE_EMPTY);
		render(Page);
		expect(await screen.findByRole('heading', { name: /^No DHCP messages from this device in the last/ })).toBeInTheDocument();
		expect(screen.getByText(/only reaches NetTap if it crosses the mirrored link\. Phones with a private Wi-Fi address/)).toBeInTheDocument();
		expect(screen.queryByRole('table')).not.toBeInTheDocument();
	});

	it("says when only the newest 200 are shown", async () => {
		goTo(`?mac=${DHCP_MAC}`);
		stubDaemon({ ...DHCP_TIMELINE, truncated: true });
		render(Page);
		expect(await screen.findByText(/Showing the newest 200 transactions\./)).toBeInTheDocument();
	});

	// OLD CODE: it("shows the daemon's reason and a retry on an error", … with ?mac=nonsense (PR #263 review: a 400 says what to fix)
	it("a MAC the daemon turns down shows its own words, with no retry", async () => {
		goTo('?mac=nonsense');
		stubDaemon(undefined);
		render(Page);
		expect(await screen.findByRole('heading', { name: 'Enter a six-byte MAC address, such as aa:bb:cc:dd:ee:ff.' })).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
	});

	it("shows the daemon's reason on a failure, and Try again asks again", async () => {
		goTo(`?mac=${DHCP_MAC}`);
		stubDaemon(undefined, { status: 503, error: 'Working this out took too long. Try a shorter time range.' });
		render(Page);
		expect(await screen.findByRole('heading', { name: "Couldn't load the DHCP history: the request failed." })).toBeInTheDocument();
		expect(screen.getByText('Working this out took too long. Try a shorter time range.')).toBeInTheDocument();
		expect(timelineCalls()).toHaveLength(1);
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		await vi.waitFor(() => expect(timelineCalls()).toHaveLength(2));
	});

	it('a failure with no reason says what to check, never loading for ever', async () => {
		goTo(`?mac=${DHCP_MAC}`);
		stubDaemon(async () => ({ ok: false, status: 500, json: async () => ({ error: '' }) }) as Reply);
		render(Page);
		// the client's own words when the daemon gives none
		expect(await screen.findByText('DHCP timeline failed: HTTP 500')).toBeInTheDocument();
		stubDaemon(async () => Promise.reject(new Error('')));
		await refreshPage();
		expect(await screen.findByText('Check that NetTap is running on the System page, then try again.')).toBeInTheDocument();
		expect(screen.queryAllByRole('status').some((s) => s.getAttribute('aria-busy') === 'true')).toBe(false);
	});

	it('a failed refresh keeps the rows on screen and says so', async () => {
		goTo(`?mac=${DHCP_MAC}`);
		stubDaemon(DHCP_TIMELINE);
		render(Page);
		await screen.findByRole('heading', { name: 'Office AP' });
		stubDaemon(undefined, { status: 503, error: 'Two other look-ups are being worked out right now; try again in a minute.' });
		await refreshPage();
		expect(await screen.findByText(/Couldn't refresh the DHCP history; showing the last figures loaded\. Two other look-ups/)).toBeInTheDocument();
		expect(within(table()).getAllByRole('row')).toHaveLength(DHCP_TIMELINE.transactions.length + 1);
	});

	it("drops an older device's answer that lands after another was asked for", async () => {
		const pending = new Map<string, (r: Reply) => void>();
		stubDaemon((url) => new Promise<Reply>((resolve) => pending.set(url.searchParams.get('mac')!, resolve)));
		goTo(`?mac=${DHCP_MAC}`);
		render(Page);
		await vi.waitFor(() => expect(pending.has(DHCP_MAC)).toBe(true));
		goTo(`?mac=${OTHER_MAC}`);
		await vi.waitFor(() => expect(pending.has(OTHER_MAC)).toBe(true));
		pending.get(DHCP_MAC)!(ok(DHCP_TIMELINE));
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.queryByRole('heading', { name: 'Office AP' })).not.toBeInTheDocument();
		pending.get(OTHER_MAC)!(ok(PRINTER));
		expect(await screen.findByRole('heading', { name: 'Printer' })).toBeInTheDocument();
		expect(within(table()).getAllByRole('row')).toHaveLength(2);
		expect(screen.queryByRole('heading', { name: 'Office AP' })).not.toBeInTheDocument();
	});

	it('choosing the device on screen again loads it again, and a range pill keeps what was typed', async () => {
		goTo(`?mac=${DHCP_MAC}`);
		stubDaemon(DHCP_TIMELINE);
		render(Page);
		await screen.findByRole('heading', { name: 'Office AP' });
		const field = screen.getByLabelText('Device') as HTMLInputElement;
		expect(field.value).toBe(DHCP_MAC);
		await fireEvent.click(screen.getByRole('button', { name: 'Show history' }));
		await vi.waitFor(() => expect(timelineCalls()).toHaveLength(2));
		expect(goto).not.toHaveBeenCalled();

		await fireEvent.input(field, { target: { value: '02:00:5e:00' } });
		goTo(`?mac=${DHCP_MAC}&range=7d`);
		await vi.waitFor(() => expect(timelineCalls()).toHaveLength(3));
		expect(field.value).toBe('02:00:5e:00');
	});

	it("picks a device by name from the suggestions' list, keeping the range", async () => {
		goTo('?range=6h');
		stubDaemon(DHCP_TIMELINE);
		render(Page);
		await vi.waitFor(() => expect(calls.some((u) => u.pathname === '/api/devices/registry')).toBe(true));
		const field = screen.getByLabelText('Device');
		await vi.waitFor(() => expect(document.querySelector('#dhcp-devices option')).toHaveAttribute('value', DHCP_MAC));
		await fireEvent.input(field, { target: { value: 'office ap' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Show history' }));
		expect(goto).toHaveBeenCalledWith(`/tools/dhcp-timeline?mac=${encodeURIComponent(DHCP_MAC)}&range=6h`, expect.anything());
	});

	it('still takes a typed MAC when the device list fails, and says so', async () => {
		stubDaemon(DHCP_TIMELINE, { registry: false });
		render(Page);
		expect(await screen.findByText(/Couldn't load your devices for suggestions/)).toBeInTheDocument();
		await fireEvent.input(screen.getByLabelText('Device'), { target: { value: 'AA-BB-CC-DD-EE-FF' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Show history' }));
		expect(goto).toHaveBeenCalledWith('/tools/dhcp-timeline?mac=AA-BB-CC-DD-EE-FF&range=24h', expect.anything());
	});

	it('a range pill keeps the device and drops a link’s exact window', async () => {
		goTo(`?mac=${DHCP_MAC}&from=2026-11-12T00:00:00.000Z&to=2026-11-12T06:00:00.000Z`);
		stubDaemon(DHCP_TIMELINE);
		render(Page);
		await screen.findByRole('heading', { name: 'Office AP' });
		expect(timelineCall()!.searchParams.get('from')).toBe('2026-11-12T00:00:00.000Z');
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		expect(goto).toHaveBeenCalledWith(`/tools/dhcp-timeline?mac=${encodeURIComponent(DHCP_MAC)}&range=7d`, expect.anything());
	});
});
