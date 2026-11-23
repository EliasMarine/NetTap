import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { goto } from '$app/navigation';
import CategoryPage from './+page.svelte';
import { windowWords } from '$lib/utils/drilldown';
import { historyState, resetNavigation, traverse } from '../../../tests/app-navigation.svelte';

// NET-357: the category page reads its range from the URL. A pill replaces a rolling range's entry
// and pushes one when it leaves a Custom window, so Back returns to the window; and Back to a view
// clears what another view left on screen, even when that view's main reply had failed.

vi.mock('$app/state', () => import('../../../tests/app-navigation.svelte'));
vi.mock('$app/navigation', () => import('../../../tests/app-navigation.svelte'));

const HOUR = 3_600_000;
/** A: a 1 h Custom window */
const F = '2026-11-13T10:00:00.000Z';
const T = '2026-11-13T10:59:59.999Z';
const DETAIL = {
	category: 'streaming', label: 'Streaming', device_count: 1, total_bytes: 4000, connection_count: 3, services: [],
	devices: [{ ip: '192.168.1.20', hostname: null, total_bytes: 4000, download_bytes: 3904, upload_bytes: 96, connections: 3, percent: 100 }],
};
const PAGE = (query: string) => `http://localhost/traffic/streaming${query}`;
let urls: URL[] = [];
/** The requests that answer 503: 'detail' (the category) and 'bandwidth' (its series) */
let failing = new Set<string>();

const hoursOf = (u: URL) => Math.round((Date.parse(u.searchParams.get('to')!) - Date.parse(u.searchParams.get('from')!)) / HOUR);

function stubDaemon() {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	vi.stubGlobal(
		'fetch',
		vi.fn(async (raw: string) => {
			const u = new URL(raw, 'http://localhost');
			urls.push(u);
			// the series over the request's own window: a 6 h one draws 9,000 B, any other 1,000 then 3,000
			const series = (hoursOf(u) === 6 ? [9000] : [1000, 3000]).map((b, i) => ({
				timestamp: new Date(Date.parse(u.searchParams.get('from')!) + i * 60_000).toISOString(), download_bytes: b, upload_bytes: 0, total_bytes: b, connections: 1,
			}));
			const body =
				u.pathname === '/api/traffic/categories/streaming' ? !failing.has('detail') && DETAIL
				: u.pathname === '/api/traffic/categories/streaming/bandwidth'
					? !failing.has('bandwidth') && { category: 'streaming', from: u.searchParams.get('from'), to: u.searchParams.get('to'), interval: u.searchParams.get('interval'), series }
				: u.pathname === '/api/traffic/summary' ? { total_bytes: 8000 }
				: u.pathname === '/api/traffic/bandwidth' ? { from: '', to: '', interval: '1h', series: [] }
				: null;
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

/** The latest category request: the window the page is on */
const lastDetail = () => urls.filter((u) => u.pathname === '/api/traffic/categories/streaming').at(-1)!;
/** The chart's request: the category's series over the latest category request's window (the other is the trend's) */
const chartCall = () => urls.filter((u) => u.pathname === '/api/traffic/categories/streaming/bandwidth' && u.searchParams.get('from') === lastDetail().searchParams.get('from')).at(-1)!;
const chart = () => screen.queryByRole('group', { name: /^Busiest at/ }) ?? screen.queryByRole('img', { name: /^Busiest at/ });
const loaded = () => vi.waitFor(() => expect(chart()).toBeInTheDocument());
const pill = (name: string) => screen.getByRole('button', { name });
const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
	urls = [];
	failing = new Set();
	vi.mocked(goto).mockClear();
	stubDaemon();
});
afterEach(() => vi.unstubAllGlobals());

describe('Traffic category — the range lives in the URL (NET-357)', () => {
	it('opens on the URL range', async () => {
		resetNavigation(PAGE('?range=6h'), { category: 'streaming' });
		render(CategoryPage);
		await loaded();
		expect(hoursOf(chartCall())).toBe(6);
		expect(pill('6h')).toHaveAttribute('aria-pressed', 'true');
	});

	it('a pill on a rolling range replaces its entry', async () => {
		resetNavigation(PAGE('?range=6h'), { category: 'streaming' });
		render(CategoryPage);
		await loaded();
		await fireEvent.click(pill('24h'));
		expect(historyState()).toEqual({ entries: ['/traffic/streaming?range=24h'], index: 0 });
		await vi.waitFor(() => expect(hoursOf(chartCall())).toBe(24));
	});

	it('a pill on a Custom window pushes, and Back returns to the window, then to the 1 h entry before it', async () => {
		resetNavigation(PAGE('?range=1h'), { category: 'streaming' });
		await goto(`/traffic/streaming?from=${F}&to=${T}&range=1h&bytes=4000`); // a pick narrowed the page
		render(CategoryPage);
		await loaded();
		expect(lastDetail().searchParams.get('from')).toBe(F);

		await fireEvent.click(pill('6h'));
		expect(vi.mocked(goto).mock.calls.at(-1)![0]).toBe('/traffic/streaming?range=6h');
		expect(historyState()).toEqual({
			entries: ['/traffic/streaming?range=1h', `/traffic/streaming?from=${F}&to=${T}&range=1h&bytes=4000`, '/traffic/streaming?range=6h'],
			index: 2,
		});
		await vi.waitFor(() => expect(hoursOf(chartCall())).toBe(6));

		traverse(-1);
		await vi.waitFor(() => expect([lastDetail().searchParams.get('from'), lastDetail().searchParams.get('to')]).toEqual([F, T]));
		expect(pill(windowWords(F, T))).toHaveAttribute('aria-pressed', 'true');

		traverse(-1);
		await vi.waitFor(() => expect(lastDetail().searchParams.get('from')).not.toBe(F));
		expect(hoursOf(lastDetail())).toBe(1);
		expect(pill('1h')).toHaveAttribute('aria-pressed', 'true');
	});

	it("Back to a window after a range whose category failed leaves none of that range's chart", async () => {
		resetNavigation(PAGE(`?from=${F}&to=${T}`), { category: 'streaming' });
		render(CategoryPage);
		await loaded();

		failing = new Set(['detail']);
		await fireEvent.click(pill('6h'));
		await vi.waitFor(() => expect(hoursOf(chartCall())).toBe(6));
		await flush();

		failing = new Set(['bandwidth']);
		traverse(-1);
		expect(await screen.findByText("Couldn't load bandwidth over time: the request failed.")).toBeInTheDocument();
		expect(lastDetail().searchParams.get('from')).toBe(F);
		expect(chart()).toBeNull();
	});
});
