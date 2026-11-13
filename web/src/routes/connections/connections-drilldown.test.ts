import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import { goto } from '$app/navigation';
import { getConnections, getConnectionTimeline, type ConnectionTimelineResponse } from '$api/traffic';
import { getLiveDashboard } from '$api/live';
import Page from './+page.svelte';

// NET-249 slice 2: the session timeline is an AreaChart on the owner's buckets, and a pick opens
// Log Explorer's conn records over the picked slots, carrying their sessions

vi.mock('$app/stores', () => ({ page: readable({ url: new URL('http://localhost/connections') }) }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$api/traffic', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/traffic')>()),
	getConnections: vi.fn(),
	getConnectionStats: vi.fn().mockRejectedValue(new Error('not under test')),
	getConnectionSankey: vi.fn().mockRejectedValue(new Error('not under test')),
	getConnectionTimeline: vi.fn(),
}));
vi.mock('$api/live', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/live')>()),
	getLiveDashboard: vi.fn(),
}));
vi.mock('$api/devices-registry', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/devices-registry')>()),
	getRegistryDevices: vi.fn().mockRejectedValue(new Error('not under test')),
}));

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

/** Two 1-minute slots; the reply's window starts 20 seconds into the first, so that slot is clipped. */
const TIMELINE: ConnectionTimelineResponse = {
	from: '2026-11-13T09:00:20.000Z',
	to: '2026-11-13T09:01:40.000Z',
	interval: '1m',
	buckets: [
		{ timestamp: '2026-11-13T09:00:00.000Z', total: 12, protocols: { tcp: 7, udp: 3, icmp: 2 } },
		{ timestamp: '2026-11-13T09:01:00.000Z', total: 5, protocols: { udp: 5 } },
	],
};
const opened = (n = -1) => {
	const href = String(vi.mocked(goto).mock.calls.at(n)![0]);
	return { path: href.split('?')[0], query: Object.fromEntries(new URL(href, 'http://x').searchParams) };
};

describe('Connections — the session timeline drills into its records (NET-249)', () => {
	beforeEach(() => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		vi.mocked(getConnections).mockResolvedValue({ from: '', to: '', connections: [], total: 0, page: 1, size: 50, total_pages: 0 } as never);
		vi.mocked(getLiveDashboard).mockRejectedValue(new Error('not under test'));
		vi.mocked(getConnectionTimeline).mockResolvedValue(TIMELINE);
		vi.mocked(goto).mockClear();
	});
	afterEach(() => vi.unstubAllGlobals());

	it.each([
		['1h', '1m', 'minute'],
		['6h', '5m', '5 minutes'],
		['24h', '5m', '5 minutes'],
		['7d', '1h', 'hour'],
		['30d', '3h', '3 hours'],
	])('%s asks for %s buckets', async (range, bucket, words) => {
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: range }));
		await flush();
		expect(vi.mocked(getConnectionTimeline).mock.lastCall![0]!.interval).toBe(bucket);
		expect(screen.getByText(new RegExp(`^Sessions per ${words}, by protocol · `))).toBeInTheDocument();
	});

	it('draws TCP, UDP and the rest as lines, with the busiest slot in its label', async () => {
		render(Page);
		await flush();
		const chart = screen.getByRole('group', { name: /^Session volume, busiest at .* with 12 sessions/ });
		expect(chart.querySelectorAll('path.line')).toHaveLength(3);
		for (const name of ['TCP', 'UDP', 'Other']) expect(screen.getByText(name, { selector: '.legend li' })).toBeInTheDocument();
		expect(screen.getByText('Click a point or drag across the chart to see that moment.')).toBeInTheDocument();
	});

	it("a pick opens the conn records over the picked slots, with their sessions", async () => {
		render(Page);
		await flush();
		const chart = screen.getByRole('group', { name: /^Session volume/ });
		await fireEvent.keyDown(chart, { key: 'Home' });
		await fireEvent.keyDown(chart, { key: 'Enter' });
		expect(opened()).toEqual({ path: '/logs', query: { type: 'zeek.conn', from: TIMELINE.from, to: '2026-11-13T09:00:59.999Z', range: '1h', count: '12' } });
		await fireEvent.keyDown(chart, { key: 'End', shiftKey: true });
		await fireEvent.keyDown(chart, { key: 'Enter' });
		expect(opened()).toEqual({ path: '/logs', query: { type: 'zeek.conn', from: TIMELINE.from, to: TIMELINE.to, range: '1h', count: '17' } });
	});

	it("an older daemon's reply, with a bucket the page doesn't know, stays a picture", async () => {
		vi.mocked(getConnectionTimeline).mockResolvedValue({ ...TIMELINE, interval: '15m' });
		render(Page);
		await flush();
		expect(screen.getByRole('img', { name: /^Session volume/ })).toBeInTheDocument();
		expect(screen.queryByText(/Click a point or drag/)).not.toBeInTheDocument();
	});

	it('keeps its empty and error states', async () => {
		vi.mocked(getConnectionTimeline).mockResolvedValue({ ...TIMELINE, buckets: [] });
		const { unmount } = render(Page);
		await flush();
		expect(screen.getByText('No sessions in this time range')).toBeInTheDocument();
		unmount();
		vi.mocked(getConnectionTimeline).mockRejectedValue(new Error('HTTP 502'));
		render(Page);
		await flush();
		expect(screen.getByText("Couldn't load the session timeline: the request failed.")).toBeInTheDocument();
	});
});
