import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { goto } from '$app/navigation';
import * as iotApi from '$lib/api/iot';
import type { ActivityTimeline } from '$lib/api/iot';
import IoTPage from './+page.svelte';

// NET-249 slice 2: the drawer's activity timeline takes the owner's buckets, and a pick opens the
// conn records the device started over the picked slots, with the sources the reply left out

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/stores/captureMode', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/stores/captureMode')>()),
	initCaptureMode: vi.fn(async () => {}),
}));
vi.mock('$lib/api/iot', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/iot')>()),
	getFleetSummary: vi.fn(),
	getPrivacyReport: vi.fn(),
	getProtocolAudit: vi.fn(),
	getNetworkIsolation: vi.fn(),
	getManufacturerProfiles: vi.fn(),
	getCommunicationMap: vi.fn(),
	getActivityTimeline: vi.fn(),
}));

const DEVICE = {
	mac: 'AA:BB:CC:00:11:22', name: 'Doorbell', manufacturer: 'Acme', ip: '192.168.1.60', score: 80, grade: 'B',
	coverage: 55, checks_available: 5, checks_total: 9, privacy_score: 80, security_score: 80, behavior_score: null,
	anomaly_count: 0, encryption_pct: 90, tracker_count: 0, last_seen: null,
};
/** Two 5-minute slots; the reply's window starts 2 minutes into the first, so that slot is clipped. */
const ACTIVITY: ActivityTimeline = {
	mac: 'AA:BB:CC:00:11:22',
	interval: '5m',
	from: '2026-11-13T09:02:00.000Z',
	to: '2026-11-13T09:08:00.000Z',
	excluded_ips: ['192.168.1.199', '2001:db8::199'],
	buckets: [
		{ time: '2026-11-13T09:00:00.000Z', connections: 3, bytes: 0, destinations: 1 },
		{ time: '2026-11-13T09:05:00.000Z', connections: 8, bytes: 0, destinations: 2 },
	],
	baseline_hours: [],
	baseline_avg_hourly_bytes: 0,
};

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

async function openTimeline() {
	render(IoTPage);
	await flush();
	await fireEvent.click(screen.getByRole('button', { name: 'Open Doorbell' }));
	await flush();
	const panel = screen.getByRole('complementary', { name: 'Detail panel' });
	await fireEvent.click(within(panel).getByRole('button', { name: 'Timeline' }));
	return panel;
}
const opened = (n = -1) => {
	const href = String(vi.mocked(goto).mock.calls.at(n)![0]);
	return { path: href.split('?')[0], query: Object.fromEntries(new URL(href, 'http://x').searchParams) };
};

describe('IoT — the activity timeline drills into its connections (NET-249)', () => {
	beforeEach(() => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		localStorage.clear();
		vi.mocked(iotApi.getFleetSummary).mockResolvedValue({
			health_score: 82, health_grade: 'B', privacy_score: 70, security_score: 85, behavior_score: null, device_count: 1,
			scored_device_count: 1, anomaly_count: 0, anomalies_checked: 1, privacy_concerns: 0, unencrypted_count: 0, subtitle: '', devices: [DEVICE],
		} as never);
		vi.mocked(iotApi.getPrivacyReport).mockResolvedValue({ devices: [] });
		vi.mocked(iotApi.getProtocolAudit).mockResolvedValue({ devices: [] });
		vi.mocked(iotApi.getNetworkIsolation).mockResolvedValue({ segmentation_score: 100, segmentation_grade: 'A', pairs: [], recommendation: '' });
		vi.mocked(iotApi.getManufacturerProfiles).mockResolvedValue({ manufacturers: [] });
		vi.mocked(iotApi.getCommunicationMap).mockResolvedValue({ mac: DEVICE.mac, destinations: [] });
		vi.mocked(iotApi.getActivityTimeline).mockResolvedValue(ACTIVITY);
	});
	afterEach(() => {
		vi.clearAllMocks();
		vi.unstubAllGlobals();
		localStorage.clear();
	});

	it.each([
		['1h', '1m'],
		['6h', '5m'],
		['24h', '5m'],
		['7d', '1h'],
		['30d', '3h'],
	])('%s asks for %s slots', async (range, bucket) => {
		localStorage.setItem('nettap-display-settings', JSON.stringify({ defaultRange: range }));
		await openTimeline();
		expect(iotApi.getActivityTimeline).toHaveBeenLastCalledWith(DEVICE.mac, expect.objectContaining({ interval: bucket }));
	});

	it('a pick opens the conn records the device started, leaving out what the reply left out, with their figure', async () => {
		const panel = await openTimeline();
		expect(within(panel).getByText('Click a point or drag across the chart to see that moment.')).toBeInTheDocument();
		const chart = within(panel).getByRole('group', { name: /^Busiest at / });
		await fireEvent.keyDown(chart, { key: 'Home' });
		await fireEvent.keyDown(chart, { key: 'Enter' });
		expect(opened()).toEqual({
			path: '/logs',
			query: {
				type: 'zeek.conn',
				query: 'source.mac:"AA:BB:CC:00:11:22" OR source.mac:"aa:bb:cc:00:11:22"',
				// the exact list the timeline applied, so both sides leave out the same sources
				exclude_src: ACTIVITY.excluded_ips!.join(','),
				from: ACTIVITY.from, to: '2026-11-13T09:04:59.999Z', range: '24h', count: '3',
			},
		});
		await fireEvent.keyDown(chart, { key: 'End', shiftKey: true });
		await fireEvent.keyDown(chart, { key: 'Enter' });
		expect(opened().query).toMatchObject({ from: ACTIVITY.from, to: ACTIVITY.to, count: '11' });
	});

	it('leaves exclude_src out when the reply left nothing out', async () => {
		vi.mocked(iotApi.getActivityTimeline).mockResolvedValue({ ...ACTIVITY, excluded_ips: [] });
		const panel = await openTimeline();
		const chart = within(panel).getByRole('group', { name: /^Busiest at / });
		await fireEvent.keyDown(chart, { key: 'Home' });
		await fireEvent.keyDown(chart, { key: 'Enter' });
		expect(opened().query).not.toHaveProperty('exclude_src');
	});

	it.each([
		['the sources it left out', { excluded_ips: undefined }],
		['its window', { from: undefined, to: undefined }],
		['a bucket the page knows', { interval: '1d6h' }],
	])("an older daemon's reply without %s stays a picture", async (_, over) => {
		vi.mocked(iotApi.getActivityTimeline).mockResolvedValue({ ...ACTIVITY, ...over });
		const panel = await openTimeline();
		expect(within(panel).getByRole('img', { name: /^Busiest at / })).toBeInTheDocument();
		expect(within(panel).queryByText(/Click a point or drag/)).not.toBeInTheDocument();
	});
});
