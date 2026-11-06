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
	coverage: 55, checks_available: 5, checks_total: 11,
	privacy_score: score, security_score: score, behavior_score: score,
	anomaly_count: 0, encryption_pct: 90, tracker_count: 0, last_seen: null, ...extra,
});

const fleet = (devices: ReturnType<typeof device>[], extra: Record<string, unknown> = {}) => ({
	health_score: 82, health_grade: 'B', privacy_score: 70, security_score: 85, behavior_score: 90,
	device_count: devices.length, scored_device_count: devices.length, anomaly_count: 2, anomalies_checked: devices.length,
	privacy_concerns: 1, unencrypted_count: 0,
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
				tracker_lookup_share: null, third_party_orgs: 0, encryption_ratio: 0, encryption_applicable: false, phone_home_per_hour: 0 }],
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

// NET-158: the score counts only measured checks, and an unmeasured figure says so
describe('IoT page — only measured figures', () => {
	beforeEach(mockAll);
	afterEach(() => vi.clearAllMocks());

	const kpi = (label: string) => screen.getAllByText(label).map((el) => el.closest('.kpi')).find(Boolean) as HTMLElement;

	it('shows no fleet score, not 0 or F, when no device has enough measured', async () => {
		const unscored = device('m1', 'Doorbell', 0, { score: null, grade: null, coverage: 40, checks_available: 4, behavior_score: null, anomaly_count: null });
		vi.mocked(iotApi.getFleetSummary).mockResolvedValue(fleet([unscored], {
			health_score: null, health_grade: null, privacy_score: null, security_score: null, behavior_score: null,
			scored_device_count: 0, anomalies_checked: 0,
		}) as never);
		render(IoTPage);
		await flush();

		expect(screen.queryByRole('img', { name: /Smart home health/ })).not.toBeInTheDocument();
		expect(screen.getByText('Not enough measured')).toBeInTheDocument();
		expect(screen.getByText(/from 0 of 1 devices/)).toBeInTheDocument();
		const rows = document.querySelectorAll('.score-rows li');
		expect(Array.from(rows, (li) => li.textContent?.trim())).toEqual(['Privacy—', 'Security—', 'Behaviour—']);
		const row = within(screen.getByRole('table', { name: 'Device trust scores' })).getAllByRole('row')[1];
		expect(row).toHaveTextContent('— Not enough measured');
		expect(row).toHaveTextContent('Not checked');
	});

	it('says anomalies were not checked, over the last hour, when no device has a baseline', async () => {
		vi.mocked(iotApi.getFleetSummary).mockResolvedValue(fleet([device('m1', 'Doorbell', 80)], { anomaly_count: 0, anomalies_checked: 0 }) as never);
		render(IoTPage);
		await flush();
		const card = kpi('Anomalies');
		expect(card.querySelector('.kpi-num')?.textContent).toBe('—');
		expect(card).toHaveTextContent('Not checked: no device has a baseline');
		expect(card).toHaveTextContent('last hour');
		expect(card).not.toHaveTextContent('All clear');
	});

	it('states the over-5 tracker threshold behind the privacy concerns count', async () => {
		vi.mocked(iotApi.getFleetSummary).mockResolvedValue(fleet([device('m1', 'Doorbell', 80)], { privacy_concerns: 0 }) as never);
		render(IoTPage);
		await flush();
		expect(kpi('Privacy concerns')).toHaveTextContent('None with over 5 tracker domains');
		expect(kpi('Privacy concerns')).not.toHaveTextContent('No trackers');
	});

	it('counts devices under 50% encrypted, and says when none could be measured', async () => {
		vi.mocked(iotApi.getFleetSummary).mockResolvedValue(fleet([device('m1', 'Doorbell', 80), device('m2', 'Hub', 80, { encryption_pct: null })]) as never);
		const { unmount } = render(IoTPage);
		await flush();
		expect(kpi('Unencrypted')).toHaveTextContent('None under 50% encrypted · 1 of 2 measured');
		expect(kpi('Unencrypted')).not.toHaveTextContent('Fully encrypted');
		unmount();

		vi.mocked(iotApi.getFleetSummary).mockResolvedValue(fleet([device('m1', 'Doorbell', 80, { encryption_pct: null })]) as never);
		render(IoTPage);
		await flush();
		expect(kpi('Unencrypted').querySelector('.kpi-num')?.textContent).toBe('—');
		expect(kpi('Unencrypted')).toHaveTextContent('Not measured: no device had traffic to judge');
	});

	it('shows the coverage in the drawer and the share of lookups to trackers in the privacy tab', async () => {
		vi.mocked(iotApi.getPrivacyReport).mockResolvedValue({
			devices: [{ mac: 'm1', name: 'Doorbell', privacy_grade: 'B', privacy_score: 80, tracker_domains: [{ domain: 'doubleclick.net', query_count: 3 }],
				tracker_count: 1, tracker_lookup_share: 0.25, third_party_orgs: 1, encryption_ratio: 1, encryption_applicable: true, phone_home_per_hour: 2 }],
		});
		render(IoTPage);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Open Doorbell' }));
		await flush();
		const panel = screen.getByRole('complementary', { name: 'Detail panel' });
		expect(panel).toHaveTextContent('from 5 of 11 checks (55 of 100 points)');
		await fireEvent.click(within(panel).getByRole('button', { name: 'Privacy' }));
		expect(panel).toHaveTextContent('80/100'); // the same figure as the table's privacy pillar
		expect(panel).toHaveTextContent('25%share of lookups to trackers');
	});

	it('does not tag destinations "new" when the device has no baseline', async () => {
		vi.mocked(iotApi.getCommunicationMap).mockResolvedValue({
			mac: 'm1',
			destinations: [{ ip: '203.0.113.9', hostname: null, country: 'US', ports: [443], bytes_sent: 10, bytes_received: 90,
				connection_count: 1, first_seen: '', last_seen: '', in_baseline: null }],
		});
		render(IoTPage);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Open Doorbell' }));
		await flush();
		const panel = screen.getByRole('complementary', { name: 'Detail panel' });
		await fireEvent.click(within(panel).getByRole('button', { name: 'Comm Map' }));
		expect(panel).toHaveTextContent('New destinations not checked: this device has no baseline yet.');
		expect(within(panel).queryByText(/· new$/)).not.toBeInTheDocument();
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
