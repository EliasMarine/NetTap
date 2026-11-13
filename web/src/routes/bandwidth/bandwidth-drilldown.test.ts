import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { goto } from '$app/navigation';
import Page from './+page.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn(async () => {}) }));

// NET-249 slice 2 (T10): a day on the Daily usage chart opens the moment page for that UTC day
// (the last one clipped to now), with the day's download, upload and local figures to compare.

const MONTH_FROM = '2026-11-01T00:00:00.000Z';
const NOW = '2026-11-02T13:20:00.000Z';
const day = (date: string, down: number, up: number, local: number) => ({
	date, total_bytes: down + up + local, orig_bytes: 0, resp_bytes: 0, download_bytes: down, upload_bytes: up, local_bytes: local, connections: 1,
});
let dailyReply: unknown;

function stubDaemon() {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	vi.stubGlobal(
		'fetch',
		vi.fn(async (raw: string) => {
			const body = raw.startsWith('/api/bandwidth/daily') ? dailyReply : null;
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

const chart = () => screen.getByRole('group', { name: /^Busiest day/ });
const target = (n = 0) => new URL(String(vi.mocked(goto).mock.calls[n][0]), 'http://localhost');

beforeEach(() => {
	vi.mocked(goto).mockClear();
	dailyReply = {
		from: MONTH_FROM, to: NOW, interval: '1d',
		daily: [day('2026-11-01T00:00:00.000Z', 100, 10, 1), day('2026-11-02T00:00:00.000Z', 200, 20, 2)],
	};
	stubDaemon();
});
afterEach(() => vi.unstubAllGlobals());

describe('Bandwidth — a day opens its moment (NET-249)', () => {
	it('a day opens /moment for that UTC day, with its figures and the month as the whole chart', async () => {
		render(Page);
		await vi.waitFor(() => expect(chart()).toBeInTheDocument());
		expect(screen.getByText('Click a point or drag across the chart to see that moment.')).toBeInTheDocument();
		await fireEvent.keyDown(chart(), { key: 'Home' });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(target(0).pathname).toBe('/moment');
		expect(Object.fromEntries(target(0).searchParams)).toEqual({
			from: MONTH_FROM, to: '2026-11-01T23:59:59.999Z', down: '100', up: '10', local: '1', chart_from: MONTH_FROM, chart_to: NOW,
		});
		// today ends now, not at midnight
		await fireEvent.keyDown(chart(), { key: 'End', shiftKey: true });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(Object.fromEntries(target(1).searchParams)).toMatchObject({ from: MONTH_FROM, to: NOW, down: '300', up: '30', local: '3' });
	});

	it('a reply that names no bucket (an older daemon) stays a picture', async () => {
		dailyReply = { ...(dailyReply as object), interval: undefined };
		render(Page);
		await vi.waitFor(() => expect(screen.getByRole('img', { name: /^Busiest day/ })).toBeInTheDocument());
		expect(screen.queryByText(/see that moment/)).not.toBeInTheDocument();
	});
});
