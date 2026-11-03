import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import HomePage from './+page.svelte';

// With no range chosen (the default), the "previous period" requests went out with no range too,
// so every trend compared the current 24 h with itself.

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

const callsTo = (f: ReturnType<typeof vi.fn>, path: string) =>
	f.mock.calls.filter(([u]) => String(u).startsWith(path)).length;

const trendTexts = () => [...document.querySelectorAll('.trend-indicator')].map((e) => e.textContent?.replace(/\s+/g, ' ').trim());

describe('Home — trend indicators', () => {
	beforeEach(() => {
		// jsdom has no ResizeObserver; the bandwidth chart needs one to mount
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('does not fetch the current period a second time as the "previous" one', async () => {
		const fetchMock = stubDaemon(5, 5);
		render(HomePage);
		expect(await screen.findByText('5 high, 0 med, 0 low')).toBeInTheDocument();

		expect(callsTo(fetchMock, '/api/alerts/count')).toBe(1);
		expect(callsTo(fetchMock, '/api/traffic/summary')).toBe(1);
		expect(trendTexts()).toEqual([]);
	});

	it('compares a chosen range with the one before it', async () => {
		stubDaemon(5, 10);
		render(HomePage);
		await screen.findByText('5 high, 0 med, 0 low');
		await fireEvent.click(screen.getByRole('button', { name: 'Apply' }));

		await vi.waitFor(() => expect(trendTexts()).toEqual(['▼ 50.0%']));
	});

	it('says "new" rather than a percentage when the previous period had no alerts', async () => {
		stubDaemon(5, 0);
		render(HomePage);
		await screen.findByText('5 high, 0 med, 0 low');
		await fireEvent.click(screen.getByRole('button', { name: 'Apply' }));

		await vi.waitFor(() => expect(trendTexts()).toEqual(['▲ new']));
		expect(document.body.textContent).not.toMatch(/Infinity|NaN|100\.0%/);
	});
});
