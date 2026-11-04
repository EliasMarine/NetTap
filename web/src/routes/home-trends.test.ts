import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import HomePage from './+page.svelte';
import { _configure } from '$lib/stores/alertSnapshot';

// With no range chosen (the default), the "previous period" requests went out with no range too,
// so every trend compared the current 24 h with itself. The range is now always explicit (the head
// pills default to 24h), so the previous period is the window just before it.

const HOUR = 60 * 60 * 1000;
const counts = (total: number) => ({ from: '', to: '', counts: { total, high: total, medium: 0, low: 0 } });

/** Alert count replies `current` for the chosen window and `previous` for the one before it. */
function stubDaemon(current: number, previous: number): ReturnType<typeof vi.fn> {
	const fetchMock = vi.fn(async (url: string) => {
		if (url.startsWith('/api/alerts/count')) {
			const to = new URL(url, 'http://x').searchParams.get('to');
			const isPrevious = to !== null && new Date(to).getTime() < Date.now() - HOUR;
			return { ok: true, status: 200, json: async () => counts(isPrevious ? previous : current) };
		}
		return { ok: false, status: 503, json: async () => ({}) };
	});
	vi.stubGlobal('fetch', fetchMock);
	return fetchMock;
}

const windows = (f: ReturnType<typeof vi.fn>, path: string) =>
	f.mock.calls
		.map(([u]) => new URL(String(u), 'http://x'))
		.filter((u) => u.pathname === path)
		.map((u) => ({ from: u.searchParams.get('from'), to: u.searchParams.get('to') }));

// was .trend-indicator ("▼ 50.0%"); the KpiCard chip carries the direction as an icon and a sign
const trendTexts = () => [...document.querySelectorAll('.kpi-meta > .chip')].map((e) => e.textContent?.replace(/\s+/g, ' ').trim());

describe('Home — trend indicators', () => {
	beforeEach(() => {
		// jsdom has no ResizeObserver; the bandwidth chart needs one to mount
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		_configure({}); // a fresh alert snapshot store per test
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('fetches the previous period as the window just before the current one, never the same one', async () => {
		const fetchMock = stubDaemon(5, 5);
		render(HomePage);
		expect(await screen.findByText('5 high, 0 med, 0 low')).toBeInTheDocument();

		await vi.waitFor(() => expect(windows(fetchMock, '/api/traffic/summary')).toHaveLength(2));
		const [current, previous] = windows(fetchMock, '/api/traffic/summary');
		expect(previous.to).toBe(current.from);
		expect(new Date(current.to!).getTime() - new Date(current.from!).getTime()).toBe(24 * HOUR);

		const alertWindows = windows(fetchMock, '/api/alerts/count');
		expect(alertWindows).toHaveLength(2);
		expect(alertWindows.filter((w) => new Date(w.to!).getTime() < Date.now() - 23 * HOUR)).toHaveLength(1);
		// equal counts are no change, not a chip
		expect(trendTexts()).toEqual([]);
	});

	it('compares a chosen range with the one before it', async () => {
		stubDaemon(5, 10);
		render(HomePage);
		await screen.findByText('5 high, 0 med, 0 low');
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));

		await vi.waitFor(() => expect(trendTexts()).toEqual(['−50.0%']));
		expect(screen.getByText('vs previous 7 days')).toBeInTheDocument();
		// fewer alerts is good news, so the chip is not the warning colour
		expect(document.querySelector('.kpi-meta > .chip')).not.toHaveClass('is-warn');
	});

	it('says "new" rather than a percentage when the previous period had no alerts', async () => {
		stubDaemon(5, 0);
		render(HomePage);
		await screen.findByText('5 high, 0 med, 0 low');

		await vi.waitFor(() => expect(trendTexts()).toEqual(['new']));
		expect(document.querySelector('.kpi-meta > .chip')).toHaveClass('is-warn');
		expect(document.body.textContent).not.toMatch(/Infinity|NaN|100\.0%/);
	});
});
