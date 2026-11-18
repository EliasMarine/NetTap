import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { goto } from '$app/navigation';
import type { UsageDay } from '$lib/api/usage';
import Page from './+page.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn(async () => {}) }));

// NET-249 slice 2 (T10): a day on the Daily usage chart opens the moment page for that UTC day
// (the last one clipped to now), with the day's download, upload and local figures to compare.
// F4 (NET-329): the days are the ledger's, local to the owner's zone, each with its own bounds; the
// last one ends at its cutoff, where its count reached.

// OLD CODE START — F4: UTC days from /api/bandwidth/daily, each date + 24 h, the last clipped to the reply's `to`
// const MONTH_FROM = '2026-11-01T00:00:00.000Z';
// const NOW = '2026-11-02T13:20:00.000Z';
// const day = (date: string, down: number, up: number, local: number) => ({
// 	date, total_bytes: down + up + local, orig_bytes: 0, resp_bytes: 0, download_bytes: down, upload_bytes: up, local_bytes: local, connections: 1,
// });
// OLD CODE END
/** 1 November in Los Angeles: 25 hours, as the clocks go back */
const NOV_1 = { start: '2026-11-01T07:00:00.000Z', end: '2026-11-02T08:00:00.000Z' };
const NOV_2 = { start: '2026-11-02T08:00:00.000Z', end: '2026-11-03T08:00:00.000Z' };
/** What today's last count reached */
const CUTOFF = '2026-11-02T21:20:00.000Z';
const day = (date: string, bounds: { start: string; end: string }, cutoff: string | null, down: number, up: number, local: number): UsageDay => ({
	date, ...bounds, cutoff, counted_at: cutoff, download: down, upload: up, local, total: down + up, status: 'counted',
});
const future = (date: string): UsageDay => ({
	date, start: '2026-11-03T08:00:00.000Z', end: '2026-11-04T08:00:00.000Z', cutoff: null, counted_at: null,
	download: null, upload: null, local: null, total: null, status: 'future',
});
let dailyReply: unknown;

function stubDaemon() {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	vi.stubGlobal(
		'fetch',
		vi.fn(async (raw: string) => {
			// OLD CODE: const body = raw.startsWith('/api/bandwidth/daily') ? dailyReply : null; (F4: the chart's days come with the month)
			const body = raw.startsWith('/api/usage/month') ? dailyReply : null;
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

const chart = () => screen.getByRole('group', { name: /^Busiest day/ });
const target = (n = 0) => new URL(String(vi.mocked(goto).mock.calls[n][0]), 'http://localhost');

beforeEach(() => {
	vi.mocked(goto).mockClear();
	// OLD CODE START — F4
	// dailyReply = {
	// 	from: MONTH_FROM, to: NOW, interval: '1d',
	// 	daily: [day('2026-11-01T00:00:00.000Z', 100, 10, 1), day('2026-11-02T00:00:00.000Z', 200, 20, 2)],
	// };
	// OLD CODE END
	// the month reply: its days are the chart, its bounds the device card's (§4.5)
	dailyReply = {
		tz: 'America/Los_Angeles', pending_tz: null, since: '2026-10-01', generation: 1, updated_at: CUTOFF,
		days: [day('2026-11-01', NOV_1, NOV_1.end, 100, 10, 1), day('2026-11-02', NOV_2, CUTOFF, 200, 20, 2), future('2026-11-03')],
		bytes: { download: 300, upload: 30, local: 3, total: 330 }, complete: true, gaps: [],
		year: 2026, month: 11, month_start: '2026-11-01T00:00:00-07:00', month_end: '2026-12-01T00:00:00-08:00',
		projected: null, daily_rate: null, days_remaining: null, sweep: null,
	};
	stubDaemon();
});
afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

describe('Bandwidth — a day opens its moment (NET-249)', () => {
	// OLD CODE: it('a day opens /moment for that UTC day, with its figures and the month as the whole chart', async () => { (F4: a local day)
	it('a day opens /moment for exactly its local day (25 hours here), with its figures and the month as the whole chart', async () => {
		render(Page);
		await vi.waitFor(() => expect(chart()).toBeInTheDocument());
		expect(screen.getByText('Click a point or drag across the chart to see that moment.')).toBeInTheDocument();
		await fireEvent.keyDown(chart(), { key: 'Home' });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(target(0).pathname).toBe('/moment');
		// OLD CODE START — F4: a UTC day
		// expect(Object.fromEntries(target(0).searchParams)).toEqual({
		// 	from: MONTH_FROM, to: '2026-11-01T23:59:59.999Z', down: '100', up: '10', local: '1', chart_from: MONTH_FROM, chart_to: NOW,
		// });
		// OLD CODE END
		expect(Object.fromEntries(target(0).searchParams)).toEqual({
			from: NOV_1.start, to: '2026-11-02T07:59:59.999Z', down: '100', up: '10', local: '1', chart_from: NOV_1.start, chart_to: CUTOFF,
		});
		// OLD CODE: // today ends now, not at midnight (F4: where its count reached)
		// today ends where its count reached, not at midnight; the future day isn't on the chart
		await fireEvent.keyDown(chart(), { key: 'End', shiftKey: true });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		// OLD CODE: expect(Object.fromEntries(target(1).searchParams)).toMatchObject({ from: MONTH_FROM, to: NOW, down: '300', up: '30', local: '3' }); (F4)
		expect(Object.fromEntries(target(1).searchParams)).toMatchObject({ from: NOV_1.start, to: CUTOFF, down: '300', up: '30', local: '3' });
	});

	// OLD CODE START — F4: every ledger day carries its bounds, so there is no reply without a bucket to fall back from
	// // OLD CODE: it('a reply that names no bucket (an older daemon) stays a picture', …) with getByRole('img', …)
	// // (chart gaps: the daily chart marks days with no record, so it is read with the arrow keys; it still picks nothing)
	// it('a reply that names no bucket (an older daemon) can be read but not picked', async () => {
	// 	dailyReply = { ...(dailyReply as object), interval: undefined };
	// 	render(Page);
	// 	await vi.waitFor(() => expect(chart()).toBeInTheDocument());
	// 	expect(chart().getAttribute('aria-label')).toMatch(/Use the left and right arrow keys to read each point\.$/);
	// 	expect(screen.queryByText(/see that moment/)).not.toBeInTheDocument();
	// });
	// OLD CODE END

	it('F4: today, not counted yet, ends now rather than at its midnight', async () => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-11-02T13:20:00.000Z'));
		const reply = dailyReply as { days: UsageDay[] };
		const pending: UsageDay = { ...reply.days[1], cutoff: null, counted_at: null, download: null, upload: null, local: null, total: null, status: 'pending' };
		dailyReply = { ...reply, days: [reply.days[0], pending, reply.days[2]] };
		render(Page);
		// findByRole, not vi.waitFor: that advances the faked clock
		await screen.findByRole('group', { name: /^Busiest day/ });
		await fireEvent.keyDown(chart(), { key: 'End' });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(Object.fromEntries(target(0).searchParams)).toMatchObject({ from: NOV_2.start, to: '2026-11-02T13:20:00.000Z', chart_to: '2026-11-02T13:20:00.000Z' });
		// it has no figures, so the link carries none: the moment page must not read "you clicked 0 B"
		expect(['down', 'up', 'local'].filter((k) => target(0).searchParams.has(k))).toEqual([]);
		// nor does a range that takes it in
		await fireEvent.keyDown(chart(), { key: 'Home', shiftKey: true });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(target(1).searchParams.get('from')).toBe(NOV_1.start);
		expect(['down', 'up', 'local'].filter((k) => target(1).searchParams.has(k))).toEqual([]);
	});

	it('F4: a day not counted opens its window with no figures', async () => {
		const reply = dailyReply as { days: UsageDay[] };
		const notCounted: UsageDay = { ...reply.days[0], cutoff: null, counted_at: null, download: null, upload: null, local: null, total: null, status: 'not_counted' };
		dailyReply = { ...reply, days: [notCounted, reply.days[1], reply.days[2]] };
		render(Page);
		await screen.findByRole('group', { name: /^Busiest day/ });
		await fireEvent.keyDown(chart(), { key: 'Home' });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(Object.fromEntries(target(0).searchParams)).toEqual({ from: NOV_1.start, to: '2026-11-02T07:59:59.999Z', chart_from: NOV_1.start, chart_to: CUTOFF });
	});

	it("F4: a cutoff before today's start (a clock that moved) still opens a valid window, at today's start", async () => {
		const reply = dailyReply as { days: UsageDay[] };
		dailyReply = { ...reply, days: [reply.days[0], { ...reply.days[1], cutoff: '2026-11-02T07:00:00.000Z' }, reply.days[2]] };
		render(Page);
		await screen.findByRole('group', { name: /^Busiest day/ });
		await fireEvent.keyDown(chart(), { key: 'End' });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(Object.fromEntries(target(0).searchParams)).toMatchObject({ from: NOV_2.start, to: NOV_2.start, chart_to: NOV_2.start });
	});
});
