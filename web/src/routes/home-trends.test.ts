import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import HomePage from './+page.svelte';
import { _configure } from '$lib/stores/alertSnapshot';
import { SETTLE_MS } from '$lib/utils/window-trend';

// OLD CODE START — NET-228 (audit TRF-6): the trend compared the window ending now, still filling in
// (Zeek writes a connection when it ends), with the one before it, through a second summary and count
// // With no range chosen (the default), the "previous period" requests went out with no range too,
// // so every trend compared the current 24 h with itself. The range is now always explicit (the head
// // pills default to 24h), so the previous period is the window just before it.
//
// const HOUR = 60 * 60 * 1000;
// const counts = (total: number) => ({ from: '', to: '', counts: { total, high: total, medium: 0, low: 0 } });
//
// /** Alert count replies `current` for the chosen window and `previous` for the one before it. */
// function stubDaemon(current: number, previous: number): ReturnType<typeof vi.fn> {
// 	const fetchMock = vi.fn(async (url: string) => {
// 		if (url.startsWith('/api/alerts/count')) {
// 			const to = new URL(url, 'http://x').searchParams.get('to');
// 			const isPrevious = to !== null && new Date(to).getTime() < Date.now() - HOUR;
// 			return { ok: true, status: 200, json: async () => counts(isPrevious ? previous : current) };
// 		}
// 		return { ok: false, status: 503, json: async () => ({}) };
// 	});
// 	vi.stubGlobal('fetch', fetchMock);
// 	return fetchMock;
// }
//
// const windows = (f: ReturnType<typeof vi.fn>, path: string) =>
// 	f.mock.calls
// 		.map(([u]) => new URL(String(u), 'http://x'))
// 		.filter((u) => u.pathname === path)
// 		.map((u) => ({ from: u.searchParams.get('from'), to: u.searchParams.get('to') }));
//
// // was .trend-indicator ("▼ 50.0%"); the KpiCard chip carries the direction as an icon and a sign
// const trendTexts = () => [...document.querySelectorAll('.kpi-meta > .chip')].map((e) => e.textContent?.replace(/\s+/g, ' ').trim());
//
// describe('Home — trend indicators', () => {
// 	beforeEach(() => {
// 		// jsdom has no ResizeObserver; the bandwidth chart needs one to mount
// 		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
// 		_configure({}); // a fresh alert snapshot store per test
// 	});
//
// 	afterEach(() => {
// 		vi.unstubAllGlobals();
// 	});
//
// 	it('fetches the previous period as the window just before the current one, never the same one', async () => {
// 		const fetchMock = stubDaemon(5, 5);
// 		render(HomePage);
// 		expect(await screen.findByText('5 high, 0 med, 0 low')).toBeInTheDocument();
//
// 		await vi.waitFor(() => expect(windows(fetchMock, '/api/traffic/summary')).toHaveLength(2));
// 		const [current, previous] = windows(fetchMock, '/api/traffic/summary');
// 		expect(previous.to).toBe(current.from);
// 		expect(new Date(current.to!).getTime() - new Date(current.from!).getTime()).toBe(24 * HOUR);
//
// 		const alertWindows = windows(fetchMock, '/api/alerts/count');
// 		expect(alertWindows).toHaveLength(2);
// 		expect(alertWindows.filter((w) => new Date(w.to!).getTime() < Date.now() - 23 * HOUR)).toHaveLength(1);
// 		// equal counts are no change, not a chip
// 		expect(trendTexts()).toEqual([]);
// 	});
//
// 	it('compares a chosen range with the one before it', async () => {
// 		stubDaemon(5, 10);
// 		render(HomePage);
// 		await screen.findByText('5 high, 0 med, 0 low');
// 		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
//
// 		await vi.waitFor(() => expect(trendTexts()).toEqual(['−50.0%']));
// 		expect(screen.getByText('vs previous 7 days')).toBeInTheDocument();
//
// 		// the comparison words come from the shared list: "previous 6 hours", as on Traffic, not "previous 6 h"
// 		await fireEvent.click(screen.getByRole('button', { name: '6h' }));
// 		expect(await screen.findByText('vs previous 6 hours')).toBeInTheDocument();
// 		// fewer alerts is good news, so the chip is not the warning colour
// 		expect(document.querySelector('.kpi-meta > .chip')).not.toHaveClass('is-warn');
// 	});
//
// 	it('says "new" rather than a percentage when the previous period had no alerts', async () => {
// 		stubDaemon(5, 0);
// 		render(HomePage);
// 		await screen.findByText('5 high, 0 med, 0 low');
//
// 		await vi.waitFor(() => expect(trendTexts()).toEqual(['new']));
// 		expect(document.querySelector('.kpi-meta > .chip')).toHaveClass('is-warn');
// 		expect(document.body.textContent).not.toMatch(/Infinity|NaN|100\.0%/);
// 	});
// });
// OLD CODE END

const HOUR = 60 * 60 * 1000;
const STEP: Record<string, number> = { '5m': 300_000, '30m': 1_800_000, '1h': HOUR, '12h': 12 * HOUR, '1d': 24 * HOUR };

interface Slot {
	bytes: number;
	connections: number;
	alerts: number;
}
/** Each slot's figures by its half of the trend window: older first, then newer. */
type Shape = (half: 'older' | 'newer', i: number) => Slot;

/** A slot per step from `from`, plus the extra one holding `to`, as the daemon's time_slots replies. */
function slots(url: URL, shape: Shape): { timestamp: string; slot: Slot }[] {
	const from = Date.parse(url.searchParams.get('from')!);
	const to = Date.parse(url.searchParams.get('to')!);
	const step = STEP[url.searchParams.get('interval')!];
	const mid = from + (to - from) / 2;
	const out = [];
	for (let t = from, i = 0; t <= to; t += step, i++) {
		out.push({ timestamp: new Date(t).toISOString(), slot: shape(t < mid ? 'older' : 'newer', i) });
	}
	return out;
}

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const isTrendWindow = (u: URL) => Date.parse(u.searchParams.get('to')!) <= Date.now() - SETTLE_MS;

/** The trend's two series follow `shape`; `failTrend` fails the trend's traffic series. */
function stubDaemon(shape: Shape, failTrend = false): ReturnType<typeof vi.fn> {
	const fetchMock = vi.fn(async (input: string) => {
		const u = new URL(input, 'http://x');
		const from = u.searchParams.get('from');
		const to = u.searchParams.get('to');
		if (u.pathname === '/api/traffic/summary') {
			return ok({ from, to, total_bytes: 1e9, orig_bytes: 0, resp_bytes: 0, upload_bytes: 0, download_bytes: 1e9, local_bytes: 0, packet_count: 0, connection_count: 900, top_protocol: 'tcp' });
		}
		if (u.pathname === '/api/alerts/count') return ok({ from, to, counts: { total: 5, high: 5, medium: 0, low: 0 } });
		if (u.pathname === '/api/traffic/bandwidth' && isTrendWindow(u)) {
			if (failTrend) return { ok: false, status: 503, json: async () => ({}) };
			const series = slots(u, shape).map(({ timestamp, slot }) => ({ timestamp, orig_bytes: 0, resp_bytes: 0, upload_bytes: 0, download_bytes: slot.bytes, local_bytes: 0, total_bytes: slot.bytes, connections: slot.connections }));
			return ok({ from, to, interval: u.searchParams.get('interval'), series });
		}
		if (u.pathname === '/api/alerts/timeline') {
			const buckets = slots(u, shape).map(({ timestamp, slot }) => ({ timestamp, high: slot.alerts, medium: 0, low: 0, info: 0 }));
			return ok({ from, to, interval: u.searchParams.get('interval'), buckets });
		}
		return { ok: false, status: 503, json: async () => ({}) };
	});
	vi.stubGlobal('fetch', fetchMock);
	return fetchMock;
}

const trendRequest = (f: ReturnType<typeof vi.fn>) =>
	f.mock.calls.map(([u]) => new URL(String(u), 'http://x')).find((u) => u.pathname === '/api/traffic/bandwidth' && isTrendWindow(u))!;

// the KpiCard chip carries the direction as an icon and a sign
const trendTexts = () => [...document.querySelectorAll('.kpi-meta > .chip')].map((e) => e.textContent?.replace(/\s+/g, ' ').trim());
const metaTexts = () => [...document.querySelectorAll('.kpi-meta > span')].map((e) => e.textContent?.trim());

/** Older half twice the newer one in bytes and alerts; connections steady. */
const halving: Shape = (half) => ({ bytes: half === 'older' ? 20 : 10, connections: 5, alerts: half === 'older' ? 2 : 1 });

describe('Home — trends over two equal settled windows (NET-228, TRF-6)', () => {
	beforeEach(() => {
		// jsdom has no ResizeObserver; the bandwidth chart needs one to mount
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		_configure({}); // a fresh alert snapshot store per test
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('compares two equal windows of whole slots that end before the newest, still-arriving minutes', async () => {
		const fetchMock = stubDaemon(halving);
		render(HomePage);

		await vi.waitFor(() => expect(trendTexts()).toEqual(['−50.0%', '−50.0%']));
		const asked = trendRequest(fetchMock);
		const from = Date.parse(asked.searchParams.get('from')!);
		const to = Date.parse(asked.searchParams.get('to')!);
		expect(to - from).toBe(48 * HOUR);
		expect(to % HOUR).toBe(0);
		expect(Date.now() - to).toBeGreaterThanOrEqual(SETTLE_MS);
		// the timeline asks for the same window, so its slots line up with the connections'
		const timeline = fetchMock.mock.calls.map(([u]) => new URL(String(u), 'http://x')).find((u) => u.pathname === '/api/alerts/timeline')!;
		expect(timeline.searchParams.toString()).toBe(asked.searchParams.toString());
		// steady connections are no change, and every line says where the compared data ends
		expect(metaTexts()).toEqual(expect.arrayContaining([expect.stringMatching(/^No change vs previous 24 hours, up to \d\d:\d\d$/)]));
		expect(metaTexts().filter((t) => /^vs previous 24 hours, up to \d\d:\d\d$/.test(t ?? ''))).toHaveLength(2);
	});

	it('says there is not enough data when a slot has no connections (NetTap off, or not yet installed)', async () => {
		stubDaemon((half, i) => ({ ...halving(half, i), connections: i === 2 ? 0 : 5 }));
		render(HomePage);

		await vi.waitFor(() => expect(metaTexts().filter((t) => t === 'Not enough data to compare')).toHaveLength(3));
		expect(trendTexts()).toEqual([]);
	});

	it('an alert window with no alerts is not enough data, not "new" (Suricata may have been down)', async () => {
		stubDaemon((half, i) => ({ ...halving(half, i), alerts: half === 'older' ? 0 : 1 }));
		render(HomePage);

		await vi.waitFor(() => expect(trendTexts()).toEqual(['−50.0%']));
		expect(metaTexts()).toContain('Not enough data to compare');
		expect(document.body.textContent).not.toMatch(/\bnew\b|Infinity|NaN/);
	});

	it('says the comparison failed when its series does not load, rather than showing no trend', async () => {
		stubDaemon(halving, true);
		render(HomePage);

		await vi.waitFor(() => expect(metaTexts().filter((t) => t === "Couldn't load the comparison")).toHaveLength(3));
		expect(trendTexts()).toEqual([]);
	});

	it('compares a chosen range over its own slots', async () => {
		const fetchMock = stubDaemon(halving);
		render(HomePage);
		await vi.waitFor(() => expect(trendTexts()).toHaveLength(2));
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));

		await vi.waitFor(() => expect(metaTexts().some((t) => /^vs previous 7 days, up to /.test(t ?? ''))).toBe(true));
		const asked = fetchMock.mock.calls.map(([u]) => new URL(String(u), 'http://x')).filter((u) => u.pathname === '/api/traffic/bandwidth' && isTrendWindow(u)).at(-1)!;
		expect(asked.searchParams.get('interval')).toBe('12h');
		expect(Date.parse(asked.searchParams.get('to')!) - Date.parse(asked.searchParams.get('from')!)).toBe(2 * 168 * HOUR);
		// fewer alerts is good news, so the chip is not the warning colour
		expect(trendTexts()).toEqual(['−50.0%', '−50.0%']);
		expect([...document.querySelectorAll('.kpi-meta > .chip')].some((c) => c.classList.contains('is-warn'))).toBe(false);
	});
});
