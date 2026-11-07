/**
 * /alerts, NET-160 section D: a counted link (?count=N) and the list it opens. The list stays live;
 * when the total of the one request the link started differs from N, the page says so exactly.
 * Rendered page with its real guards and registerPageRefresh; API replies are deferred where order matters.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import {
	getAlerts,
	getAlertCount,
	getAlertTimeline,
	getAlertTopSignatures,
	getAlertTopIps,
	getEnhancedCategories,
	getSmartAlertSummary,
	type Alert,
	type AlertsListResponse,
} from '$api/alerts';
import { _configure as resetAlertSnapshots } from '$lib/stores/alertSnapshot';
import { refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';

/** The page's URL: setting `nav.url` is a same-route navigation, and goto() sets it as SvelteKit would. */
const nav = vi.hoisted(() => {
	let url = new URL('http://localhost/alerts');
	const readers = new Set<(v: { url: URL }) => void>();
	return {
		get url() {
			return url;
		},
		set url(next: URL) {
			url = next;
			for (const fn of readers) fn({ url });
		},
		subscribe(fn: (v: { url: URL }) => void) {
			readers.add(fn);
			fn({ url });
			return () => readers.delete(fn);
		},
	};
});
vi.mock('$app/stores', () => ({ page: { subscribe: nav.subscribe } }));
vi.mock('$app/navigation', () => ({
	goto: vi.fn(async (href: string) => {
		nav.url = new URL(href, nav.url);
	}),
}));
vi.mock('$api/alerts', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/alerts')>()),
	getAlerts: vi.fn(),
	getAlertCount: vi.fn(),
	getAlertTimeline: vi.fn(),
	getAlertTopSignatures: vi.fn(),
	getAlertTopIps: vi.fn(),
	getEnhancedCategories: vi.fn(),
	getSmartAlertSummary: vi.fn(),
}));

const noResizeObserver = class {
	observe() {}
	unobserve() {}
	disconnect() {}
};

function deferred<T>() {
	let resolve!: (v: T) => void;
	let reject!: (e: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

const range = { from: '', to: '' };

function alert(id: string, signature = `Sig ${id}`): Alert {
	return {
		_id: id,
		_index: 'suricata-x',
		timestamp: '2026-11-03T10:00:00Z',
		alert: { signature, signature_id: 2000, severity: 2, category: 'Potentially Bad Traffic' },
		rule: { name: signature },
		src_ip: '192.168.1.42',
		dest_ip: '203.0.113.45',
		proto: 'tcp',
		acknowledged: false,
	};
}

/** One page of rows whose search matched `total` alerts. */
function list(total: number, page = 1): AlertsListResponse {
	return { ...range, page, size: 50, total, total_pages: Math.max(1, Math.ceil(total / 50)), alerts: [alert(`a${page}`)] };
}

/** Every request succeeds; the list's search matches `total` alerts. */
function succeedAll(total = 1) {
	vi.mocked(getAlerts).mockResolvedValue(list(total));
	vi.mocked(getAlertCount).mockResolvedValue({ ...range, counts: { total: 40, high: 3, medium: 7, low: 20 } });
	vi.mocked(getAlertTimeline).mockResolvedValue({ ...range, interval: '1h', buckets: [] });
	vi.mocked(getAlertTopSignatures).mockResolvedValue({ ...range, signatures: [], complete: true, examined: 0 });
	vi.mocked(getAlertTopIps).mockResolvedValue({ ...range, direction: 'dest', ips: [], complete: true, examined: 0 });
	vi.mocked(getEnhancedCategories).mockResolvedValue({ ...range, categories: [] });
	vi.mocked(getSmartAlertSummary).mockResolvedValue({
		...range, threat_score: 0, threat_level: 'none', total_groups: 0, total_events: 0, categories: {}, top_threats: [],
	});
}

const at = (query: string) => (nav.url = new URL(`http://localhost/alerts${query}`));
const listCalls = () => vi.mocked(getAlerts).mock.calls.map(([opts]) => opts!);
/** The dashboard's own requests: a list-only search makes none of them. */
const dashboardCalls = () =>
	[getAlertCount, getAlertTimeline, getAlertTopSignatures, getAlertTopIps, getEnhancedCategories, getSmartAlertSummary].reduce(
		(n, fn) => n + vi.mocked(fn).mock.calls.length,
		0,
	);
/** The difference line, or null when the page shows none. */
const countLine = () => screen.queryByText(/^You clicked/);
const CAUSES = 'Records can be logged after a figure is counted (a connection is logged when it ends), and old records are deleted to free disk space.';
const matching = (n: string) => screen.getByText(new RegExp(`^${n} matching`));

beforeEach(() => {
	resetAlertSnapshots({});
	vi.clearAllMocks();
	vi.stubGlobal('ResizeObserver', noResizeObserver);
	// the LAN policy request (IP links); an empty policy is enough here
	vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ version: 'v1', subnets: [], source: 'env', ipv6: 'not-lan' }) })));
});

afterEach(() => {
	vi.useRealTimers();
	nav.url = new URL('http://localhost/alerts');
	vi.unstubAllGlobals();
});

describe('Alerts — the figure a link was clicked at (NET-160 section D)', () => {
	it('shows no line when the list matches the figure clicked', async () => {
		at('?signature=ET%20SCAN%20Nmap&count=37');
		succeedAll(37);
		render(Page);
		await flush();
		expect(matching('37')).toBeInTheDocument();
		expect(countLine()).toBeNull();
	});

	it('says how many more the search matches now, as a neutral status line above the list', async () => {
		at('?count=1234');
		succeedAll(1240);
		render(Page);
		await flush();
		const line = countLine()!;
		expect(line).toHaveTextContent(`You clicked 1,234. This search now matches 1,240 alerts (6 more). ${CAUSES}`);
		expect(line).toHaveAttribute('role', 'status');
		expect(line).toHaveClass('notice');
		expect(line.className).not.toMatch(/is-/);
		expect(line.closest('#alerts-table')).not.toBeNull();
	});

	it('says how many fewer', async () => {
		at('?count=1234');
		succeedAll(1200);
		render(Page);
		await flush();
		expect(countLine()).toHaveTextContent('You clicked 1,234. This search now matches 1,200 alerts (34 fewer).');
	});

	it('names a single alert as such', async () => {
		at('?count=3');
		succeedAll(1);
		render(Page);
		await flush();
		expect(countLine()).toHaveTextContent('You clicked 3. This search now matches 1 alert (2 fewer).');
	});

	it.each(['1e3', '-1', ' 5', '', '1234567890123456', 'abc'])('ignores count=%j: no line', async (raw) => {
		at(`?count=${encodeURIComponent(raw)}`);
		succeedAll(7);
		render(Page);
		await flush();
		expect(matching('7')).toBeInTheDocument();
		expect(countLine()).toBeNull();
	});

	it('a failed first request shows the error state and no line', async () => {
		at('?count=10');
		succeedAll();
		vi.mocked(getAlerts).mockRejectedValue(new Error('HTTP 502'));
		render(Page);
		await flush();
		expect(screen.getByText("Couldn't load alerts: the request failed.")).toBeInTheDocument();
		expect(countLine()).toBeNull();
	});

	it('a count-only change makes one list request, no dashboard requests, and a new comparison', async () => {
		at('?signature=ET%20SCAN%20Nmap&range=7d&count=5');
		succeedAll(5);
		render(Page);
		await flush();
		expect(countLine()).toBeNull();
		vi.clearAllMocks();
		vi.mocked(getAlerts).mockResolvedValue(list(5));
		at('?signature=ET%20SCAN%20Nmap&range=7d&count=7');
		await flush();
		expect(listCalls()).toEqual([expect.objectContaining({ page: 1, signature: 'ET SCAN Nmap' })]);
		expect(dashboardCalls()).toBe(0);
		expect(countLine()).toHaveTextContent('You clicked 7. This search now matches 5 alerts (2 fewer).');
	});

	it('the same filters and count again make no request', async () => {
		at('?count=5');
		succeedAll(9);
		render(Page);
		await flush();
		vi.mocked(getAlerts).mockClear();
		at('?count=5');
		await flush();
		expect(listCalls()).toHaveLength(0);
		expect(countLine()).toHaveTextContent('You clicked 5.');
	});

	describe('hand-off A then hand-off B', () => {
		/** A is the page's first load (refresh.run); B a new signature on the same window (fetchAlerts). */
		async function openAThenB() {
			const a = deferred<AlertsListResponse>();
			const b = deferred<AlertsListResponse>();
			succeedAll();
			vi.mocked(getAlerts).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
			at('?signature=A&count=10');
			render(Page);
			await flush();
			at('?signature=B&count=20');
			await flush();
			expect(listCalls().map((c) => c.signature)).toEqual(['A', 'B']);
			return { a, b };
		}

		it("B answers first, A late: B's line shows and A's total is never compared", async () => {
			const { a, b } = await openAThenB();
			b.resolve(list(25));
			await flush();
			a.resolve(list(13));
			await flush();
			expect(countLine()).toHaveTextContent('You clicked 20. This search now matches 25 alerts (5 more).');
			expect(matching('25')).toBeInTheDocument();
			expect(listCalls()).toHaveLength(2);
		});

		it("A answers first (superseded), then B: only B's comparison shows", async () => {
			const { a, b } = await openAThenB();
			a.resolve(list(13));
			await flush();
			expect(countLine()).toBeNull();
			b.resolve(list(25));
			await flush();
			expect(countLine()).toHaveTextContent('You clicked 20. This search now matches 25 alerts (5 more).');
			expect(matching('25')).toBeInTheDocument();
			expect(listCalls()).toHaveLength(2);
		});

		it("A's line showed, then B replaces it: gone while B loads, B's once it answers", async () => {
			succeedAll(13);
			at('?signature=A&count=10');
			render(Page);
			await flush();
			expect(countLine()).toHaveTextContent('You clicked 10. This search now matches 13 alerts (3 more).');
			const b = deferred<AlertsListResponse>();
			vi.mocked(getAlerts).mockReturnValueOnce(b.promise);
			at('?signature=B&count=20');
			await flush();
			expect(countLine()).toBeNull();
			b.resolve(list(18));
			await flush();
			expect(countLine()).toHaveTextContent('You clicked 20. This search now matches 18 alerts (2 fewer).');
			expect(matching('18')).toBeInTheDocument();
			expect(listCalls()).toHaveLength(2);
		});
	});

	it("a manual refresh while the hand-off's request is pending ends the comparison: the refresh's total, no line", async () => {
		const handOff = deferred<AlertsListResponse>();
		at('?count=10');
		succeedAll(40);
		vi.mocked(getAlerts).mockReturnValueOnce(handOff.promise);
		render(Page);
		await flush();
		const refreshed = refreshPage();
		await flush();
		handOff.resolve(list(16));
		await refreshed;
		await flush();
		expect(matching('40')).toBeInTheDocument();
		expect(countLine()).toBeNull();
		expect(listCalls()).toHaveLength(2);
	});

	it('an automatic tick during the first load sends nothing and the comparison survives; the next idle tick refreshes and ends it', async () => {
		vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
		const handOff = deferred<AlertsListResponse>();
		at('?count=10');
		succeedAll(1);
		vi.mocked(getAlerts).mockReturnValueOnce(handOff.promise);
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Paused' }));
		const sent = { list: listCalls().length, dashboard: dashboardCalls() };
		vi.advanceTimersByTime(15_000);
		await flush();
		expect({ list: listCalls().length, dashboard: dashboardCalls() }).toEqual(sent);

		handOff.resolve(list(16));
		await flush();
		expect(countLine()).toHaveTextContent('You clicked 10. This search now matches 16 alerts (6 more).');

		vi.advanceTimersByTime(15_000);
		await flush();
		expect(listCalls()).toHaveLength(sent.list + 1);
		expect(countLine()).toBeNull();
		expect(matching('1')).toBeInTheDocument();
	});

	describe('any later list load ends the line when it starts', () => {
		/** Opens a counted link whose list is two pages and differs, in the table view. */
		async function openWithLine() {
			at('?count=110');
			succeedAll(116);
			const view = render(Page);
			await flush();
			await fireEvent.click(screen.getByRole('button', { name: 'All alerts' }));
			expect(countLine()).toHaveTextContent('(6 more)');
			const held = deferred<AlertsListResponse>();
			vi.mocked(getAlerts).mockReturnValueOnce(held.promise);
			return { held, container: view.container };
		}

		it.each([
			['a sort', async (container: HTMLElement) => {
				const header = [...container.querySelectorAll('th button.th-btn')].find((b) => b.textContent?.startsWith('Severity'))!;
				await fireEvent.click(header);
			}],
			['the next page', async () => fireEvent.click(screen.getByRole('button', { name: 'Next page' }))],
			['a refresh', async () => void refreshPage()],
		])('%s', async (_name, act) => {
			const { held, container } = await openWithLine();
			const sent = listCalls().length;
			await act(container);
			await flush();
			expect(listCalls()).toHaveLength(sent + 1);
			expect(countLine()).toBeNull();
			held.resolve(list(116, listCalls().at(-1)!.page));
			await flush();
			expect(countLine()).toBeNull();
		});
	});

	it('a control that writes the URL drops count and makes one list request, with no comparison', async () => {
		at('?signature=ET%20SCAN%20Nmap&count=10');
		succeedAll(16);
		render(Page);
		await flush();
		expect(countLine()).not.toBeNull();
		vi.clearAllMocks();
		vi.mocked(getAlerts).mockResolvedValue(list(3));
		await fireEvent.click(within(screen.getByRole('group', { name: 'Severity' })).getByRole('button', { name: 'High' }));
		await flush();
		expect(nav.url.searchParams.has('count')).toBe(false);
		expect(nav.url.searchParams.get('severity')).toBe('high');
		expect(listCalls()).toEqual([expect.objectContaining({ severity: 1, signature: 'ET SCAN Nmap', page: 1 })]);
		expect(dashboardCalls()).toBe(0);
		expect(countLine()).toBeNull();
	});
});
