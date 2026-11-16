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

	// NET-228 (audit ALR-18): a stage is NetTap's reading of a rule match, and a stage outside this
	// chain's order can still have matches, so it is "not in this chain", not "not seen"
	it('words a kill chain as a reading of rule matches', async () => {
		const chain = { source_ip: '192.168.1.66', stages: [1, 3], stage_labels: [], alert_count: 4, assessment: 'Chain' };
		stubDaemon({
			'/api/threats/report': { ...REPORT, kill_chains: [chain], failed_checks: [], incomplete_checks: [] },
			'/api/threats/intel': { from: '', to: '', new_indicators: 0, feeds: {}, total_indicators: 0 },
		});
		render(ThreatsPage);
		await vi.waitFor(() => expect(screen.getByText('Possible kill chains')).toBeInTheDocument());
		expect(screen.getByText('Stage 1 · Reconnaissance · Rule matched')).toBeInTheDocument();
		expect(screen.getByText('Stage 2 · Exploit · Not in this chain')).toBeInTheDocument();
		expect(screen.getByText('1 found')).toBeInTheDocument();
		expect(screen.getByText(/1 possible kill chain\b/)).toBeInTheDocument();
		expect(screen.queryByText(/Detected|active kill chain/)).not.toBeInTheDocument();
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

// NET-242: the page still lists older findings with a sensor stopped, so it says so at the top
describe('Threats page — the data pipeline now', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});
	const health = (state: string, sensors: Record<string, string> = {}) => ({
		uptime: 1, timestamp: '', storage: {}, smart: {}, opensearch_reachable: true, status: 'problem', healthy: false,
		pipeline: { state, newest_record_at: null, age_seconds: null, threshold_seconds: 900, sensors, checked_at: '' },
	});
	const line = /^Data pipeline now:/;

	it('says Suricata stopped above the findings it still lists', async () => {
		stubDaemon({ '/api/threats/report': REPORT, '/api/system/health': health('sensor_stopped', { 'nettap-suricata-live': 'exited' }) });
		render(ThreatsPage);
		const note = await screen.findByText(line);
		expect(note).toHaveTextContent('Data pipeline now: Suricata stopped. What this page shows may be out of date. See System for details.');
		expect(note.closest('p')).toHaveClass('notice', 'is-warn');
		expect(screen.getByRole('link', { name: 'System' })).toHaveAttribute('href', '/system');
		expect(screen.getByText(THREAT_SCORE_HOW)).toBeInTheDocument();
	});

	it('says nothing while data is arriving', async () => {
		stubDaemon({ '/api/threats/report': REPORT, '/api/system/health': health('fresh') });
		render(ThreatsPage);
		await screen.findByText(THREAT_SCORE_HOW);
		expect(screen.queryByText(line)).not.toBeInTheDocument();
	});

	it("says it couldn't check when the daemon couldn't", async () => {
		stubDaemon({ '/api/threats/report': REPORT, '/api/system/health': health('unknown') });
		render(ThreatsPage);
		expect(await screen.findByText(line)).toHaveTextContent("Data pipeline now: Couldn't check.");
	});
});

// NET-239: the suppressions and baseline that changed the score were hidden inputs
describe('Threats page — what changed the score', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says under the method what suppressions and the baseline changed', async () => {
		const baseline = { deviation: 1, avg_events: 0, avg_threat_score: 0, history_points: 3, is_anomalous: false, ready: false, earlier_hours: 2 };
		const summary = { ...REPORT.summary, suppressed_findings: 1, busier_window_points: 0, baseline };
		stubDaemon({ '/api/threats/report': { ...REPORT, summary } });
		render(ThreatsPage);
		const how = (await screen.findByText(THREAT_SCORE_HOW)).closest('details');
		expect(how).toHaveTextContent('1 finding in this window was left out by your suppressions or false-positive marks.');
		expect(how).toHaveTextContent("Still learning what's usual: 2 of 6 earlier hours recorded, so no +15 yet.");
		// NET-239 review: the KPI's "1× vs baseline" said a comparison was made while still learning
		expect(screen.queryByText(/× (vs|above) baseline/)).not.toBeInTheDocument();
	});
});

// The owner's three asks: the investigation's sections share its width, a beaconing row opens its
// pair, and a DNS row opens why it was listed
describe('Threats page — drill-downs and the investigation layout', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.mocked(goto).mockClear();
	});
	const INTEL = { from: '', to: '', new_indicators: 0, feeds: {}, total_indicators: 0 };
	const BEACON = {
		source_ip: '192.168.1.188', destination_ip: '188.166.201.72', destination_port: 443, connection_count: 204,
		interval_seconds: 3600.6, jitter_coefficient: 0.0012, confidence: 100, assessment: '', pattern: 'beacon',
	};
	const MANY = {
		source_ip: '192.168.1.205', destination_ip: '198.51.100.9', destination_port: 6881, connection_count: 30,
		interval_seconds: 2206, jitter_coefficient: 0.01, confidence: 60, assessment: '', pattern: 'many_hosts', host_count: 12,
	};
	const DNS = {
		dga_suspects: [{ domain: 'Static.CloudflareInsights.com', entropy: 3.837, query_count: 1, assessment: '' }],
		tunnel_suspects: [{ domain: 'a'.repeat(51) + '.example.com.', subdomain_length: 59, query_count: 24, assessment: '' }],
		nxdomain_spikes: [{ source_ip: '192.168.1.116', total_queries: 827, nxdomain_count: 364, nxdomain_ratio: 0.44, assessment: '' }],
		suspicious_tlds: [],
	};

	it('opens a beaconing row on its pair, over the same range, and links a many-hosts device', async () => {
		stubDaemon({
			'/api/threats/report': { ...REPORT, failed_checks: [], incomplete_checks: [], beaconing: [BEACON, MANY] },
			'/api/threats/intel': INTEL,
			'/api/network/lan': LAN_POLICY,
		});
		const { container } = render(ThreatsPage);
		const open = await screen.findByRole('button', { name: 'Open beaconing from 192.168.1.188 to 188.166.201.72:443' });
		await fireEvent.click(open);
		expect(goto).toHaveBeenLastCalledWith('/threats/beaconing/192.168.1.188/188.166.201.72/443?range=24h');
		await vi.waitFor(() => expect(screen.getByRole('link', { name: '192.168.1.205' })).toHaveAttribute('href', '/devices/192.168.1.205'));
		expectNoNestedInteractive(container);
	});

	it('opens a DNS row on why it was listed: the raw name in finding mode, or the device\'s failed lookups', async () => {
		stubDaemon({ '/api/threats/report': { ...REPORT, failed_checks: [], incomplete_checks: [], dns_anomalies: DNS }, '/api/threats/intel': INTEL });
		const { container } = render(ThreatsPage);
		await screen.findByText('Up to 5 of each finding · select one to see why it was listed · last 24 hours');
		await fireEvent.click(screen.getByRole('button', { name: 'Open DGA suspect Static.CloudflareInsights.com: why it was listed' }));
		expect(goto).toHaveBeenLastCalledWith('/domain/static.cloudflareinsights.com?range=24h&finding=Static.CloudflareInsights.com');
		await fireEvent.click(screen.getByRole('button', { name: /^Open DNS tunnelling a+\.example\.com\.: why it was listed$/ }));
		expect(goto).toHaveBeenLastCalledWith(`/domain/${'a'.repeat(51)}.example.com?range=24h&finding=${'a'.repeat(51)}.example.com.`);
		await fireEvent.click(screen.getByRole('button', { name: 'Open NXDOMAIN spike 192.168.1.116: why it was listed' }));
		expect(goto).toHaveBeenLastCalledWith('/threats/failed-lookups/192.168.1.116?range=24h');
		expectNoNestedInteractive(container);
	});

	it('leaves a DNS row plain when its name has no domain page (Zeek writes non-ASCII as \\xNN)', async () => {
		const odd = 'caf\\xc3\\xa9-kq3z8wxv1m7tbn5r6yhp.com';
		stubDaemon({
			'/api/threats/report': { ...REPORT, failed_checks: [], incomplete_checks: [], dns_anomalies: { ...DNS, dga_suspects: [{ domain: odd, entropy: 4.1, query_count: 2, assessment: '' }] } },
			'/api/threats/intel': INTEL,
		});
		render(ThreatsPage);
		const table = await screen.findByRole('table', { name: 'DNS anomalies' });
		expect(screen.queryByRole('button', { name: `Open DGA suspect ${odd}: why it was listed` })).not.toBeInTheDocument();
		expect(table).toHaveTextContent(odd);
		// the other rows still open
		expect(screen.getByRole('button', { name: 'Open NXDOMAIN spike 192.168.1.116: why it was listed' })).toBeInTheDocument();
	});

	it("links an investigation's rule to its page by rule.name, over the report's window", async () => {
		const investigation = (rule_name?: string | null) => ({
			alert: { signature: 'ET MALWARE Example CnC (as shown)', severity_label: 'CRITICAL', category_label: 'Malware', source_ip: '192.168.1.42', destination_ip: '203.0.113.45', count: 3, rule_name, activity: true },
			generated_at: '',
			sections: { source_profile: { ip: '192.168.1.42', connection_count_24h: 1, unique_destinations: 1, total_bytes_24h: 1 } },
			recommendation: 'Check the device.',
		});
		const from = '2026-11-15T00:00:00.000Z';
		const to = '2026-11-16T00:00:00.000Z';
		stubDaemon({ '/api/threats/report': { ...REPORT, from, to, failed_checks: [], incomplete_checks: [], investigations: [investigation('ET MALWARE Example CnC')] }, '/api/threats/intel': INTEL });
		const { container, unmount } = render(ThreatsPage);
		const link = await screen.findByRole('link', { name: 'What this rule means and which devices it involved' });
		const href = new URL(link.getAttribute('href')!, 'http://x');
		expect(href.pathname).toBe('/alerts/rule/ET%20MALWARE%20Example%20CnC');
		expect(Object.fromEntries(href.searchParams)).toEqual({ from, to, range: '24h', activity: 'true' });
		expectNoNestedInteractive(container);
		unmount();
		// an older daemon's investigation has no rule.name: no link rather than one by the shown signature
		stubDaemon({ '/api/threats/report': { ...REPORT, failed_checks: [], incomplete_checks: [], investigations: [investigation(undefined)] }, '/api/threats/intel': INTEL });
		render(ThreatsPage);
		await screen.findByText('Source host profile');
		expect(screen.queryByRole('link', { name: 'What this rule means and which devices it involved' })).not.toBeInTheDocument();
	});

	it('lays the investigation sections out apart from the todo, and breaks an IPv6 address only after a colon', async () => {
		const v6 = '2001:0db8:85a3:0000:0000:8a2e:0370:7334';
		const investigation = {
			alert: { signature: 'ET MALWARE Example CnC', severity_label: 'CRITICAL', category_label: 'Malware', source_ip: v6, destination_ip: '203.0.113.45', count: 3 },
			generated_at: '',
			sections: {
				source_profile: { ip: v6, connection_count_24h: 120, unique_destinations: 8, total_bytes_24h: 1_000 },
				destination_profile: { ip: '203.0.113.45', connection_count_24h: 3, unique_destinations: 1, total_bytes_24h: 10 },
				connection_history: { total_connections_7d: 900, total_bytes_7d: 2_500_000, first_seen: '' },
			},
			recommendation: 'Check the device.',
		};
		stubDaemon({ '/api/threats/report': { ...REPORT, failed_checks: [], incomplete_checks: [], investigations: [investigation] }, '/api/threats/intel': INTEL });
		const { container } = render(ThreatsPage);
		await screen.findByText('Source host profile');
		const body = container.querySelector('.inv-body')!;
		expect(body.querySelectorAll(':scope > .inv-sections > section')).toHaveLength(3);
		// the todo is outside the sections' grid, so auto-fit can collapse the tracks no section fills
		expect(body.querySelector(':scope > .todo')).toHaveTextContent('Check the device.');
		expect(body.querySelector('.inv-sections .todo')).toBeNull();
		const ip = body.querySelector('dd.ip')!;
		expect(ip.textContent).toBe(v6);
		expect(ip.querySelectorAll('wbr')).toHaveLength(7);
		// the head's source → destination line breaks the same way (it scrolled the page at 390 px)
		const head = container.querySelector('.inv-head .mono')!;
		expect(head.textContent).toBe(`${v6} → 203.0.113.45`);
		expect(head.querySelectorAll('wbr')).toHaveLength(7);
	});
});
