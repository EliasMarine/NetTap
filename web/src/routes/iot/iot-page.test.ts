import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { get } from 'svelte/store';
import * as iotApi from '$lib/api/iot';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import IoTPage from './+page.svelte';

// The redesigned /iot (PLAN.md §5.6): KPIs, the trust Ring, the device table, the cards' states,
// and the page refresh contract (§5.5).

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

const device = (mac: string, name: string, score: number, extra: Record<string, unknown> = {}) => ({
	mac, name, manufacturer: 'Acme', ip: '192.168.1.60', score, grade: score >= 75 ? 'B' : 'D',
	privacy_score: score, security_score: score, behavior_score: score,
	anomaly_count: 0, encryption_pct: 90, tracker_count: 0, last_seen: null, ...extra,
});

const fleet = (devices: ReturnType<typeof device>[], extra: Record<string, unknown> = {}) => ({
	health_score: 82, health_grade: 'B', privacy_score: 70, security_score: 85, behavior_score: 90,
	device_count: devices.length, anomaly_count: 2, privacy_concerns: 1, unencrypted_count: 0,
	subtitle: 'Most devices behave well.', devices, ...extra,
});

const ISOLATION = { segmentation_score: 100, segmentation_grade: 'A', pairs: [], recommendation: '' };

function mockAll() {
	vi.mocked(iotApi.getFleetSummary).mockResolvedValue(fleet([device('m1', 'Doorbell', 80), device('m2', 'Camera', 40)]) as never);
	vi.mocked(iotApi.getPrivacyReport).mockResolvedValue({ devices: [] });
	vi.mocked(iotApi.getProtocolAudit).mockResolvedValue({ devices: [] });
	vi.mocked(iotApi.getNetworkIsolation).mockResolvedValue(ISOLATION);
	vi.mocked(iotApi.getManufacturerProfiles).mockResolvedValue({ manufacturers: [] });
	vi.mocked(iotApi.getCommunicationMap).mockResolvedValue({ mac: 'm1', destinations: [] });
	vi.mocked(iotApi.getActivityTimeline).mockResolvedValue({ mac: 'm1', interval: '1h', buckets: [], baseline_hours: [], baseline_avg_hourly_bytes: 0 });
}

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

function deferred<T>() {
	let resolve!: (v: T) => void;
	const promise = new Promise<T>((r) => (resolve = r));
	return { promise, resolve };
}

const failed = () => Promise.reject(new Error('HTTP 500'));

describe('IoT page — layout', () => {
	beforeEach(mockAll);
	afterEach(() => vi.clearAllMocks());

	it('shows the KPIs and the trust Ring with its three score rows', async () => {
		render(IoTPage);
		await flush();

		expect(screen.getByRole('heading', { level: 1, name: 'IoT trust score' })).toBeInTheDocument();
		const kpi = screen.getAllByText('Anomalies').map((el) => el.closest('.kpi')).find(Boolean);
		expect(kpi?.querySelector('.kpi-num')?.textContent).toBe('2');
		expect(screen.getByRole('img', { name: 'Smart home health 82 of 100, grade B' })).toBeInTheDocument();
		expect(screen.getByText('Most devices behave well.')).toBeInTheDocument();
		const rows = document.querySelectorAll('.score-rows li');
		expect(Array.from(rows, (li) => li.textContent?.trim())).toEqual(['Privacy70', 'Security85', 'Behaviour90']);
	});

	it('lists devices worst first in a table where every column sorts, and a row opens the drawer', async () => {
		render(IoTPage);
		await flush();
		const table = screen.getByRole('table', { name: 'Device trust scores' });

		for (const th of within(table).getAllByRole('columnheader')) expect(within(th).getByRole('button')).toBeInTheDocument();
		expect(within(table).getAllByRole('row')[1]).toHaveTextContent('Camera');

		await fireEvent.click(screen.getByRole('button', { name: 'Open Doorbell' }));
		await flush();
		expect(iotApi.getCommunicationMap).toHaveBeenCalledWith('m1', expect.objectContaining({ from: expect.any(String) }));
		expect(screen.getByRole('heading', { name: 'Doorbell' })).toBeInTheDocument();
	});

	it('shows each finding with its severity as a pill and opens its device', async () => {
		vi.mocked(iotApi.getProtocolAudit).mockResolvedValue({
			devices: [{ mac: 'm2', name: 'Camera', category: 'camera', violation_count: 1, compliant: false,
				findings: [{ type: 'telnet_open', severity: 'high', port: 23, description: 'Camera accepts Telnet' }] }],
		});
		render(IoTPage);
		await flush();

		const finding = screen.getByText('Camera accepts Telnet').closest('li') as HTMLElement;
		expect(within(finding).getByText('High')).toBeInTheDocument();
		expect(within(finding).getByText('Security')).toBeInTheDocument();
		await fireEvent.click(within(finding).getByRole('button', { name: 'Camera' }));
		await flush();
		expect(iotApi.getCommunicationMap).toHaveBeenCalledWith('m2', expect.anything());
	});

	it('shows the empty states when nothing is classified', async () => {
		vi.mocked(iotApi.getFleetSummary).mockResolvedValue(fleet([]) as never);
		render(IoTPage);
		await flush();
		expect(screen.getByText('No IoT devices classified yet.')).toBeInTheDocument();
		expect(screen.getByText('No manufacturer data available.')).toBeInTheDocument();
	});

	it('shows the loading state while the fleet summary is pending', async () => {
		vi.mocked(iotApi.getFleetSummary).mockReturnValue(new Promise(() => {}));
		render(IoTPage);
		await flush();
		expect(screen.getByRole('status')).toHaveTextContent('Scanning IoT devices');
		expect(screen.getByRole('heading', { level: 1, name: 'IoT trust score' })).toBeInTheDocument();
	});

	it('says N/A in the privacy tab for a device with only local chatter, not 0% encrypted', async () => {
		vi.mocked(iotApi.getPrivacyReport).mockResolvedValue({
			devices: [{ mac: 'm1', name: 'Doorbell', privacy_grade: 'A', privacy_score: 90, tracker_domains: [], tracker_count: 0,
				telemetry_bytes: 0, third_party_orgs: 0, encryption_ratio: 0, encryption_applicable: false, phone_home_per_hour: 0 }],
		});
		render(IoTPage);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Open Doorbell' }));
		await flush();
		await fireEvent.click(within(screen.getByRole('complementary', { name: 'Detail panel' })).getByRole('button', { name: 'Privacy' }));
		expect(screen.getByText(/^N\/A: only local traffic/)).toBeInTheDocument();
		expect(screen.queryByRole('img', { name: /encrypted/ })).not.toBeInTheDocument();
	});
});

describe('IoT page — page refresh contract', () => {
	beforeEach(mockAll);
	afterEach(() => vi.clearAllMocks());

	it('reports ok when every request succeeds, and unregisters on unmount', async () => {
		const { unmount } = render(IoTPage);
		await flush();
		expect(await refreshPage()).toBe('ok');
		unmount();
		expect(get(pageRefresh).available).toBe(false);
	});

	it('reports partial when one request fails', async () => {
		vi.mocked(iotApi.getManufacturerProfiles).mockImplementation(failed);
		render(IoTPage);
		await flush();
		expect(await refreshPage()).toBe('partial');
	});

	it('reports failed when every request fails', async () => {
		for (const fn of [iotApi.getFleetSummary, iotApi.getPrivacyReport, iotApi.getProtocolAudit, iotApi.getNetworkIsolation, iotApi.getManufacturerProfiles]) {
			vi.mocked(fn).mockImplementation(failed);
		}
		render(IoTPage);
		await flush();
		expect(await refreshPage()).toBe('failed');
	});

	it('drops the older range when the newer one answers first', async () => {
		const slow = deferred<ReturnType<typeof fleet>>();
		vi.mocked(iotApi.getFleetSummary).mockReturnValueOnce(slow.promise as never);
		render(IoTPage);
		await flush();

		vi.mocked(iotApi.getFleetSummary).mockResolvedValueOnce(fleet([device('m9', 'Seven day plug', 60)]) as never);
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		await flush();
		expect(screen.getByText('Seven day plug')).toBeInTheDocument();

		slow.resolve(fleet([device('m8', 'One day plug', 60)]));
		await flush();
		expect(screen.queryByText('One day plug')).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
	});
});
