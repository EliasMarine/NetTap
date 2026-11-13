import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { goto } from '$app/navigation';
import type { ConnectionDetailResponse, LiveConnection } from '$lib/api/live';
import LiveConnectionDrawerContent from './LiveConnectionDrawerContent.svelte';

// NET-249 slice 2: the drawer's 24-hour history is an AreaChart on 5-minute slots, and a pick opens
// Log Explorer's conn records for the pair, either way round, on the port the history filtered on

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const CONNECTION = { source_ip: '192.168.1.20', source_port: 51000, dest_ip: '2001:db8::443', dest_port: 443, protocol: 'tcp', service: 'ssl' } as LiveConnection;
/** Two 5-minute slots; the reply's window starts 2 minutes into the first, so that slot is clipped. */
const HISTORY: ConnectionDetailResponse['history'] = {
	total_bytes: 3000,
	connection_count: 3,
	from: '2026-11-12T09:02:00.000Z',
	to: '2026-11-12T09:08:00.000Z',
	interval: '5m',
	port: 443,
	timeline: [
		{ timestamp: '2026-11-12T09:00:00.000Z', bytes: 1000, connections: 1 },
		{ timestamp: '2026-11-12T09:05:00.000Z', bytes: 2000, connections: 2 },
	],
};
const detail = (history: ConnectionDetailResponse['history']) =>
	({ geo: { ip: CONNECTION.dest_ip, country: '', country_code: '', city: '', lat: null, lon: null, asn: null, organization: '' }, alerts: [], alert_count: 0, history }) as ConnectionDetailResponse;
const show = (history: ConnectionDetailResponse['history'], over: Record<string, unknown> = {}) =>
	render(LiveConnectionDrawerContent, { connection: CONNECTION, detail: detail(history), detailLoading: false, detailFailed: false, activeTab: 'alerts', ...over });
const opened = () => {
	const href = String(vi.mocked(goto).mock.calls.at(-1)![0]);
	return { path: href.split('?')[0], query: Object.fromEntries(new URL(href, 'http://x').searchParams) };
};
const PAIR = '((source.ip:"192.168.1.20" AND destination.ip:"2001:db8::443") OR (source.ip:"2001:db8::443" AND destination.ip:"192.168.1.20"))';

describe('Live connection drawer — the history drills into its connections (NET-249)', () => {
	beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }));
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.mocked(goto).mockClear();
	});

	it('a pick opens the pair, either way round, on the history port, over the picked slots, with no count', async () => {
		show(HISTORY);
		expect(screen.getByText('Click a point or drag across the chart to see that moment.')).toBeInTheDocument();
		const chart = screen.getByRole('group', { name: /^Busiest at / });
		await fireEvent.keyDown(chart, { key: 'Home' });
		await fireEvent.keyDown(chart, { key: 'Enter' });
		expect(opened()).toEqual({
			path: '/logs',
			query: { type: 'zeek.conn', query: `${PAIR} AND destination.port:443`, from: HISTORY.from, to: '2026-11-12T09:04:59.999Z', range: '24h' },
		});
		await fireEvent.keyDown(chart, { key: 'End', shiftKey: true });
		await fireEvent.keyDown(chart, { key: 'Enter' });
		expect(opened().query).toMatchObject({ from: HISTORY.from, to: HISTORY.to });
	});

	it('leaves the port out when the history filtered on none', async () => {
		show({ ...HISTORY, port: null });
		const chart = screen.getByRole('group', { name: /^Busiest at / });
		await fireEvent.keyDown(chart, { key: 'Home' });
		await fireEvent.keyDown(chart, { key: 'Enter' });
		expect(opened().query.query).toBe(PAIR);
	});

	it.each([
		['the port it filtered on', { port: undefined }],
		['its window', { from: undefined, to: undefined }],
		['a bucket the drawer knows', { interval: undefined }],
	])("an older daemon's history without %s stays a picture", (_, over) => {
		show({ ...HISTORY, ...over });
		expect(screen.getByRole('img', { name: /^Busiest at / })).toBeInTheDocument();
		expect(screen.queryByText(/Click a point or drag/)).not.toBeInTheDocument();
	});

	it('keeps its loading, failed and empty states', () => {
		const { unmount } = show(HISTORY, { detail: null, detailLoading: true });
		expect(screen.getByText('Loading history…')).toBeInTheDocument();
		unmount();
		const failed = show(HISTORY, { detail: null, detailFailed: true });
		expect(screen.getByText("Couldn't load history for this connection: the request failed.")).toBeInTheDocument();
		failed.unmount();
		show({ ...HISTORY, timeline: [] });
		expect(screen.getByText('No history data available')).toBeInTheDocument();
	});
});
