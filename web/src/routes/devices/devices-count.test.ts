// NET-160 section D: Home's Devices card links here with the Total devices figure it showed
// (`count`). When this window's own Total devices differs, the page says so beside the KPIs.
// The rendered page with its real load guard and registerPageRefresh; device list replies wait
// until the test answers them.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import type { Writable } from 'svelte/store';
import { goto } from '$app/navigation';
import { refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
const pageStore = vi.hoisted(() => ({ value: null as unknown as Writable<{ url: URL }> }));
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	pageStore.value = writable({ url: new URL('http://localhost/devices') });
	return { page: pageStore.value };
});
/** Navigate the mocked page store to /devices with this query. */
const goTo = (query = '') => pageStore.value.set({ url: new URL(`http://localhost/devices${query}`) });

const DEVICE = {
	ip: '192.168.1.10', mac: null, hostname: 'laptop', manufacturer: null, os_hint: null,
	first_seen: '', last_seen: '', total_bytes: 5000, connection_count: 5, protocols: [], alert_count: 0,
};
const PHONE = { ...DEVICE, ip: '192.168.1.9', hostname: 'phone', total_bytes: 100 };

/** A list reply echoing the asked window, with `total` as Total devices (devices.test.ts's reading()). */
function reading(url: URL, total: number) {
	return {
		from: url.searchParams.get('from'), to: url.searchParams.get('to'), limit: 500, devices: [DEVICE, PHONE], total,
		online_total: 0, as_of: '2026-11-06T12:00:00.000Z', online_since: '2026-11-06T11:55:00.000Z',
	};
}

let pending: { url: URL; answer: (body: unknown) => void }[] = [];
/** Bridge mode and no new devices; each device list request waits in `pending`. */
function stub(): void {
	pending = [];
	const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
	vi.stubGlobal('fetch', vi.fn(async (input: string) => {
		const url = new URL(input, 'http://localhost');
		if (url.pathname === '/api/devices') {
			const body = await new Promise((answer) => pending.push({ url, answer }));
			return body ? ok(body) : { ok: false, status: 502, json: async () => ({}) };
		}
		if (url.pathname === '/api/capture/mode') return ok({ mode: 'bridge', interface: 'br0' });
		if (url.pathname === '/api/devices/registry/new-count') return ok({ count: 0, since: '' });
		return { ok: false, status: 503, json: async () => ({}) };
	}));
}
/** Answer the nth device list request with this Total devices; null fails it. */
const answer = (n: number, total: number | null) => pending[n].answer(total === null ? undefined : reading(pending[n].url, total));
const requests = async (n: number) => vi.waitFor(() => expect(pending).toHaveLength(n));
const settle = () => new Promise((r) => setTimeout(r, 0));

const kpiValue = (label: string) => screen.getByText(label).closest('.kpi')?.querySelector('.kpi-num')?.textContent;
const total = async (value: string) => vi.waitFor(() => expect(kpiValue('Total devices')).toBe(value));
/** The difference line (CardState's loader is also a status, so by its class). */
const line = () => document.querySelector('p.notice[role="status"]')?.textContent ?? null;
const CAUSES = 'Records can be logged after a figure is counted (a connection is logged when it ends), and old records are deleted to free disk space.';

describe('Devices — the Total devices figure a link was clicked at', () => {
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
		vi.mocked(goto).mockReset();
		goTo('');
	});

	it('shows no line when the window has the count clicked', async () => {
		goTo('?range=24h&count=53');
		stub();
		render(Page);
		await requests(1);
		answer(0, 53);
		await total('53');
		expect(line()).toBeNull();
	});

	it('says how many more the window has now, with the KPIs', async () => {
		goTo('?range=24h&count=53');
		stub();
		render(Page);
		await requests(1);
		answer(0, 54);
		await total('54');
		expect(line()).toBe(`You clicked 53. This window now has 54 devices (1 more). ${CAUSES}`);
		// a full row of the KPI grid, under Total devices, not above the table
		// OLD CODE: document.querySelector('p.notice') (NET-225: this stub is bridge mode, whose note comes first)
		const notice = document.querySelector('p.notice[role="status"]') as HTMLElement;
		expect(notice.closest('.grid')?.contains(screen.getByText('Total devices'))).toBe(true);
		expect(notice).toHaveClass('c-12');
	});

	it('says how many fewer', async () => {
		goTo('?range=24h&count=53');
		stub();
		render(Page);
		await requests(1);
		answer(0, 51);
		await total('51');
		expect(line()).toBe(`You clicked 53. This window now has 51 devices (2 fewer). ${CAUSES}`);
	});

	it('a count-only change makes one load and keeps the shown reading until it answers', async () => {
		goTo('?range=24h&count=53');
		stub();
		render(Page);
		await requests(1);
		answer(0, 53);
		await total('53');

		goTo('?range=24h&count=50');
		await requests(2);
		expect(pending[1].url.searchParams.get('limit')).toBe('500');
		expect(kpiValue('Total devices')).toBe('53');
		expect(screen.getByRole('table', { name: 'All devices' })).toBeInTheDocument();
		expect(screen.queryByText('Loading devices')).not.toBeInTheDocument();
		expect(line()).toBeNull();

		answer(1, 54);
		await total('54');
		expect(line()).toContain('You clicked 50. This window now has 54 devices (4 more).');
		await settle();
		expect(pending).toHaveLength(2);
	});

	it("hand-off A then B, B's reply first: A's late total is never compared", async () => {
		goTo('?range=24h&count=10');
		stub();
		render(Page);
		await requests(1);
		goTo('?range=7d&count=20');
		await requests(2);
		answer(1, 21);
		await total('21');
		expect(line()).toContain('You clicked 20. This window now has 21 devices (1 more).');

		answer(0, 99);
		await settle();
		expect(kpiValue('Total devices')).toBe('21');
		expect(line()).toContain('You clicked 20. This window now has 21 devices (1 more).');
		expect(pending).toHaveLength(2);
	});

	it("hand-off A then B, A's reply first: B's comparison replaces A's", async () => {
		goTo('?range=24h&count=10');
		stub();
		render(Page);
		await requests(1);
		answer(0, 11);
		await total('11');
		expect(line()).toContain('You clicked 10. This window now has 11 devices (1 more).');

		goTo('?range=7d&count=20');
		await requests(2);
		expect(line()).toBeNull();
		answer(1, 22);
		await total('22');
		expect(line()).toContain('You clicked 20. This window now has 22 devices (2 more).');
		expect(pending).toHaveLength(2);
	});

	it('a manual refresh while the hand-off load is out ends the comparison', async () => {
		goTo('?range=24h&count=53');
		stub();
		render(Page);
		await requests(1);
		void refreshPage();
		await requests(2);
		answer(1, 60);
		await total('60');
		answer(0, 54);
		await settle();
		expect(kpiValue('Total devices')).toBe('60');
		expect(line()).toBeNull();
	});

	it("an automatic tick during the hand-off load sends nothing and keeps the comparison; the next idle tick ends it", async () => {
		// only the interval is fake, so the replies and vi.waitFor run on real time
		vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
		goTo('?range=24h&count=53');
		stub();
		render(Page);
		await requests(1);
		await fireEvent.click(screen.getByRole('button', { name: 'Paused' }));

		vi.advanceTimersByTime(30_000); // the load is still out: runIfIdle skips
		await settle();
		expect(pending).toHaveLength(1);
		answer(0, 54);
		await total('54');
		expect(line()).toContain('You clicked 53. This window now has 54 devices (1 more).');

		await settle();
		vi.advanceTimersByTime(30_000); // idle now: a refresh, which ends the comparison
		await requests(2);
		expect(line()).toBeNull();
		answer(1, 54);
		await settle();
		expect(kpiValue('Total devices')).toBe('54');
		expect(line()).toBeNull();
	});

	it('the local search, type pills and sort leave the line, and the table sorts on its own', async () => {
		goTo('?range=24h&count=53');
		stub();
		render(Page);
		await requests(1);
		answer(0, 54);
		await total('54');
		const shown = line();
		expect(shown).toContain('(1 more)');
		const table = screen.getByRole('table', { name: 'All devices' });

		await fireEvent.input(screen.getByLabelText('Search devices'), { target: { value: 'laptop' } });
		expect(within(table).getAllByRole('row')).toHaveLength(2);
		expect(line()).toBe(shown);
		await fireEvent.input(screen.getByLabelText('Search devices'), { target: { value: '' } });

		await fireEvent.click(screen.getByRole('button', { name: 'Computers 0' }));
		expect(screen.getByText('No devices match these filters')).toBeInTheDocument();
		expect(line()).toBe(shown);
		await fireEvent.click(screen.getByRole('button', { name: 'All 2' }));

		const sorted = screen.getByRole('table', { name: 'All devices' });
		expect(within(sorted).getAllByRole('row')[1]).toHaveTextContent('192.168.1.10'); // busiest first
		await fireEvent.click(within(sorted).getByRole('button', { name: 'Bandwidth' }));
		expect(within(sorted).getAllByRole('row')[1]).toHaveTextContent('192.168.1.9');
		expect(line()).toBe(shown);
		await settle();
		expect(pending).toHaveLength(1); // none of them asked the daemon again
	});

	it('a range pill writes a URL without count, so the line goes and the new window compares nothing', async () => {
		vi.mocked(goto).mockImplementation(async (href) => pageStore.value.set({ url: new URL(String(href), 'http://localhost') }));
		goTo('?range=24h&count=53');
		stub();
		render(Page);
		await requests(1);
		answer(0, 54);
		await total('54');
		expect(line()).not.toBeNull();

		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		const [href] = vi.mocked(goto).mock.calls[0];
		expect(new URL(String(href), 'http://localhost').searchParams.has('count')).toBe(false);
		await requests(2);
		expect(line()).toBeNull();
		answer(1, 54);
		await total('54');
		expect(line()).toBeNull();
	});

	it('ignores an invalid count', async () => {
		goTo('?range=24h&count=1e3');
		stub();
		render(Page);
		await requests(1);
		answer(0, 54);
		await total('54');
		expect(line()).toBeNull();
	});

	it('a failed hand-off load shows the error and no line', async () => {
		goTo('?range=24h&count=53');
		stub();
		render(Page);
		await requests(1);
		answer(0, null);
		expect(await screen.findByText("Couldn't load devices: the request failed.")).toBeInTheDocument();
		expect(kpiValue('Total devices')).toBe('—');
		expect(line()).toBeNull();
	});
});
