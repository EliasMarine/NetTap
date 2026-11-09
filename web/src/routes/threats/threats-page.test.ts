import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { goto } from '$app/navigation';
import ThreatsPage from './+page.svelte';
import { THREAT_SCORE_BRIDGE, THREAT_SCORE_HOW } from '$api/alerts';
import { captureMode } from '$lib/stores/captureMode';
import { LAN_POLICY } from '../../../e2e/visual/fixtures/drilldown';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

// #96: a failed detector returned [] and the page said "No beaconing patterns detected"; a
// failed report request was replaced with an all-zero report reading threat level "none".

const REPORT = {
	from: '',
	to: '',
	generated_at: '',
	summary: { threat_score: 0, threat_level: 'none', total_groups: 0, total_events: 0, categories: {}, top_threats: [], kill_chains: [], baseline: null },
	kill_chains: [],
	beaconing: [],
	dns_anomalies: { dga_suspects: [], tunnel_suspects: [], nxdomain_spikes: [], suspicious_tlds: [] },
	lateral_movement: [{ source_ip: '192.168.1.66', destination_ip: '192.168.1.10', port: 445, service: 'SMB', connection_count: 2 }],
	investigations: [],
	failed_checks: ['beaconing'],
	incomplete_checks: ['lateral_movement'],
};

function stubDaemon(replies: Record<string, unknown>): void {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const body = replies[url.split('?')[0]];
			return body
				? { ok: true, status: 200, json: async () => body }
				: { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

describe('Threats page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('names a failed check instead of saying nothing was detected', async () => {
		stubDaemon({ '/api/threats/report': REPORT });
		render(ThreatsPage);
		await vi.waitFor(() => expect(screen.getByText(/Couldn't check for beaconing/)).toBeInTheDocument());
		expect(screen.queryByText('No beaconing patterns detected.')).not.toBeInTheDocument();
		expect(screen.getByText('check failed')).toBeInTheDocument();
		expect(screen.getByText(/Not every connection pair was checked/)).toBeInTheDocument();
		expect(screen.getByText(/Couldn't load threat intel/)).toBeInTheDocument();
		// a check that ran and found nothing still says so
		expect(screen.getByText('No DNS anomalies detected.')).toBeInTheDocument();
	});

	it('says the report failed instead of showing threat level none', async () => {
		stubDaemon({});
		render(ThreatsPage);
		await vi.waitFor(() => expect(screen.getByText("Couldn't load the threat report: the request failed.")).toBeInTheDocument());
		expect(screen.queryByText('NONE')).not.toBeInTheDocument();
	});

	it('counts a device that contacts many hosts on schedules once, not as many suspects', async () => {
		const peer = (h: number) => ({
			source_ip: '192.168.1.205', destination_ip: `198.51.100.${h}`, destination_port: 6881, connection_count: 30,
			interval_seconds: 2206, jitter_coefficient: 0.01, confidence: 60, assessment: '', pattern: 'many_hosts', host_count: 12,
		});
		const beacon = {
			source_ip: '192.168.1.188', destination_ip: '188.166.201.72', destination_port: 443, connection_count: 204,
			interval_seconds: 3600.6, jitter_coefficient: 0.0012, confidence: 100, assessment: '', pattern: 'beacon',
		};
		stubDaemon({
			'/api/threats/report': {
				...REPORT,
				failed_checks: [],
				incomplete_checks: [],
				beaconing: [beacon, ...Array.from({ length: 12 }, (_, h) => peer(h))],
			},
			'/api/threats/intel': { from: '', to: '', new_indicators: 0, feeds: {}, total_indicators: 0 },
		});
		render(ThreatsPage);
		await vi.waitFor(() => expect(screen.getByText('1 suspect')).toBeInTheDocument());
		expect(screen.getByText(/contacts 12 internet hosts on regular schedules/)).toBeInTheDocument();
		expect(screen.queryByText('198.51.100.3', { exact: false })).not.toBeInTheDocument();
	});

	// NET-160 slice 2a: lateral movement's addresses drill down; an internet one to its address page
	it('links both ends of a lateral movement', async () => {
		stubDaemon({
			'/api/threats/report': { ...REPORT, lateral_movement: [{ ...REPORT.lateral_movement[0], destination_ip: '198.51.100.7' }], failed_checks: [], incomplete_checks: [] },
			'/api/network/lan': LAN_POLICY,
		});
		const { container } = render(ThreatsPage);
		await vi.waitFor(() => expect(screen.getByRole('link', { name: '198.51.100.7' })).toHaveAttribute('href', '/address/198.51.100.7'));
		await vi.waitFor(() => expect(screen.getByRole('link', { name: '192.168.1.66' })).toHaveAttribute('href', '/devices/192.168.1.66'));
		expectNoNestedInteractive(container);
	});

	// NET-209: an internet source has no device page, so its kill chain opens the address page
	it("sends a kill chain's Investigate device to the address page for an internet source", async () => {
		const chain = (ip: string) => ({ source_ip: ip, stages: [1, 3], stage_labels: [], alert_count: 4, assessment: `Chain from ${ip}` });
		stubDaemon({
			'/api/threats/report': { ...REPORT, kill_chains: [chain('91.92.40.12'), chain('192.168.1.66')], failed_checks: [], incomplete_checks: [] },
			'/api/network/lan': LAN_POLICY,
		});
		render(ThreatsPage);
		// the lateral movement link shows the LAN policy has loaded
		await vi.waitFor(() => expect(screen.getByRole('link', { name: '192.168.1.66' })).toHaveAttribute('href', '/devices/192.168.1.66'));
		const [internet, lan] = screen.getAllByRole('button', { name: 'Investigate device' });
		await fireEvent.click(internet);
		expect(goto).toHaveBeenLastCalledWith('/address/91.92.40.12');
		await fireEvent.click(lan);
		expect(goto).toHaveBeenLastCalledWith('/devices/192.168.1.66');
	});

	it('says a failed auto-investigation failed instead of hiding it', async () => {
		stubDaemon({
			'/api/threats/report': { ...REPORT, failed_checks: ['investigations'], incomplete_checks: [] },
			'/api/threats/intel': { from: '', to: '', new_indicators: 0, feeds: {}, total_indicators: 0 },
		});
		render(ThreatsPage);
		await vi.waitFor(() => expect(screen.getByText(/Couldn't investigate one or more critical alerts/)).toBeInTheDocument());
		expect(screen.getByText(/Couldn't check auto-investigations/)).toBeInTheDocument();
	});
});

// NET-166: an investigation's byte figures are decimal (the page's own 1,024-based copy read 953.7 MB for 10^9 bytes)
describe('Threats page — investigation byte figures', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows the bytes a host sent and its 7-day total in decimal units', async () => {
		const investigation = {
			alert: { signature: 'ET MALWARE Example CnC', severity_label: 'CRITICAL', category_label: 'Malware', source_ip: '192.168.1.42', destination_ip: '203.0.113.45', count: 3 },
			generated_at: '',
			sections: {
				source_profile: { ip: '192.168.1.42', connection_count_24h: 120, unique_destinations: 8, total_bytes_24h: 1_000_000_000 },
				connection_history: { total_connections_7d: 900, total_bytes_7d: 2_500_000, first_seen: '' },
			},
			recommendation: '',
		};
		stubDaemon({
			'/api/threats/report': { ...REPORT, failed_checks: [], incomplete_checks: [], investigations: [investigation] },
			'/api/threats/intel': { from: '', to: '', new_indicators: 0, feeds: {}, total_indicators: 0 },
		});
		render(ThreatsPage);
		// the first investigation opens expanded
		await screen.findByText('Source host profile');

		const value = (label: string) => screen.getByText(label).nextElementSibling?.textContent;
		expect(value('Bytes it sent in them (24h)')).toBe('1.0 GB');
		expect(value('Total bytes')).toBe('2.5 MB');
	});
});

// NET-225 (ALR-3): post-NAT, alerts can't be charged to the device behind the router, so they score at full weight
describe('Threats page — the score in inline bridge mode', () => {
	afterEach(() => {
		captureMode.set(null);
		vi.unstubAllGlobals();
	});

	it('says what the score counts in bridge mode', async () => {
		captureMode.set('bridge');
		stubDaemon({ '/api/threats/report': REPORT });
		render(ThreatsPage);
		expect(await screen.findByRole('note')).toHaveTextContent(THREAT_SCORE_BRIDGE);
		expect(THREAT_SCORE_BRIDGE).toMatch(/even for unsolicited scans from the internet that your router blocks/);
	});

	it('says nothing about bridge mode in mirror mode', async () => {
		captureMode.set('mirror');
		stubDaemon({ '/api/threats/report': REPORT });
		render(ThreatsPage);
		await screen.findByText(THREAT_SCORE_HOW);
		expect(screen.queryByText(THREAT_SCORE_BRIDGE)).not.toBeInTheDocument();
	});

	it('states that alerts no device is charged with score at full weight, in every mode', () => {
		expect(THREAT_SCORE_HOW).toMatch(/neither address in NetTap's LAN subnets .* adds its full weight once per signature, source and destination/);
	});
});
