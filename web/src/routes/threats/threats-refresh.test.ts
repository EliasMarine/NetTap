import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { goto } from '$app/navigation';
import { getThreatReport, getThreatIntel, type ThreatReport, type ThreatIntelInfo } from '$api/threats';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import ThreatsPage from './+page.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$api/threats', () => ({ getThreatReport: vi.fn(), getThreatIntel: vi.fn() }));

const EMPTY: ThreatReport = {
	from: '',
	to: '',
	generated_at: '',
	summary: { threat_score: 0, threat_level: 'none', total_groups: 0, total_events: 0, categories: {}, top_threats: [], kill_chains: [], baseline: null },
	kill_chains: [],
	beaconing: [],
	dns_anomalies: { dga_suspects: [], tunnel_suspects: [], nxdomain_spikes: [], suspicious_tlds: [] },
	lateral_movement: [],
	investigations: [],
	failed_checks: [],
	incomplete_checks: [],
};
const NO_INTEL: ThreatIntelInfo = { from: '', to: '', new_indicators: 0, feeds: {}, total_indicators: 0 };

const chain = (ip: string) => ({ source_ip: ip, stages: [1, 3], stage_labels: [], alert_count: 4, assessment: `Chain from ${ip}` });

const FULL: ThreatReport = {
	...EMPTY,
	summary: {
		...EMPTY.summary,
		threat_score: 72,
		threat_level: 'high',
		total_groups: 9,
		total_events: 1500,
		categories: { malware_c2: { label: 'Malware & C2', groups: 2, events: 40 }, policy: { label: 'Policy', groups: 1, events: 0 } },
	},
	kill_chains: [chain('192.168.1.42')],
	beaconing: [
		{ source_ip: '192.168.1.188', destination_ip: '188.166.201.72', destination_port: 443, connection_count: 204, interval_seconds: 3600, jitter_coefficient: 0.0012, confidence: 100, assessment: '', pattern: 'beacon' },
	],
	dns_anomalies: {
		dga_suspects: [{ domain: 'xj3kq9.biz', entropy: 4.1, query_count: 230, assessment: '' }],
		tunnel_suspects: [],
		nxdomain_spikes: [{ source_ip: '192.168.1.80', total_queries: 400, nxdomain_count: 300, nxdomain_ratio: 0.75, assessment: '' }],
		suspicious_tlds: [],
	},
	lateral_movement: [{ source_ip: '192.168.1.66', destination_ip: '192.168.1.10', port: 445, service: 'SMB', connection_count: 2, first_seen: null, last_seen: null, assessment: '' }],
	investigations: [
		{
			alert: { signature: 'ET MALWARE Example CnC', severity_label: 'CRITICAL', category_label: 'Malware', source_ip: '192.168.1.42', destination_ip: '203.0.113.45', count: 3 },
			generated_at: '',
			sections: { source_profile: { ip: '192.168.1.42', connection_count_24h: 120, unique_destinations: 8, total_bytes_24h: 2048, protocols: ['tcp', 'udp'] } },
			recommendation: 'Disconnect the device and scan it.',
		},
		{
			alert: { signature: 'ET SCAN Example Sweep', severity_label: 'MEDIUM', category_label: 'Scan', source_ip: '192.168.1.57', destination_ip: '192.0.2.88', count: 1 },
			generated_at: '',
			sections: {},
			recommendation: 'Check who runs a scanner.',
		},
	],
};
const INTEL: ThreatIntelInfo = { ...NO_INTEL, feeds: { feodo: { label: 'Abuse.ch Feodo', indicator_count: 118 } }, total_indicators: 118 };

function deferred<T>() {
	let resolve!: (v: T) => void;
	let reject!: (e: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

const flush = async () => {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
};

afterEach(() => {
	vi.clearAllMocks();
});

describe('Threats page — card states', () => {
	it('shows the loading state while the report is in flight', () => {
		vi.mocked(getThreatReport).mockReturnValue(new Promise(() => {}));
		vi.mocked(getThreatIntel).mockReturnValue(new Promise(() => {}));
		render(ThreatsPage);
		expect(screen.getByRole('status')).toHaveTextContent('Loading the threat report');
		expect(screen.getByRole('heading', { level: 1, name: 'Threats' })).toBeInTheDocument();
	});

	it('gives every card its empty state when nothing was found', async () => {
		vi.mocked(getThreatReport).mockResolvedValue(EMPTY);
		vi.mocked(getThreatIntel).mockResolvedValue(NO_INTEL);
		render(ThreatsPage);
		await vi.waitFor(() => expect(screen.getByText('No active kill chains')).toBeInTheDocument());
		for (const title of [
			// OLD CODE START: 'No threat intel indicators loaded', (I7: the card counts the window's matches) OLD CODE END
			'No threat intel matches',
			'No beaconing patterns detected.',
			'No DNS anomalies detected.',
			'No lateral movement detected.',
			'No auto-investigations',
		]) {
			expect(screen.getByText(title)).toBeInTheDocument();
		}
		expect(screen.getByText('No actionable threats detected.')).toBeInTheDocument();
		expect(screen.queryByRole('alert')).not.toBeInTheDocument();
	});

	it('gives every failed check its own error state, never a zero', async () => {
		vi.mocked(getThreatReport).mockResolvedValue({
			...EMPTY,
			failed_checks: ['beaconing', 'dns_anomalies', 'lateral_movement', 'investigations'],
		});
		vi.mocked(getThreatIntel).mockRejectedValue(new Error('HTTP 503'));
		render(ThreatsPage);
		await vi.waitFor(() => expect(screen.getAllByRole('alert')).toHaveLength(5));
		for (const text of [
			"Couldn't check for beaconing: the query failed.",
			"Couldn't check for DNS anomalies: the query failed.",
			"Couldn't check for lateral movement: the query failed.",
			"Couldn't investigate one or more critical alerts: a query failed.",
			"Couldn't load threat intel: the request failed.",
		]) {
			expect(screen.getByText(text)).toBeInTheDocument();
		}
		// the beaconing KPI says it wasn't checked instead of 0
		const kpi = screen.getByText('Beaconing', { selector: '.kpi-top span' }).closest('.kpi')!;
		expect(within(kpi as HTMLElement).getByText('—')).toBeInTheDocument();
	});

	it('shows the report as KPIs, cards and sortable tables, with every action', async () => {
		vi.mocked(getThreatReport).mockResolvedValue(FULL);
		vi.mocked(getThreatIntel).mockResolvedValue(INTEL);
		render(ThreatsPage);
		await vi.waitFor(() => expect(screen.getByText('72')).toBeInTheDocument());
		expect(screen.getByText('High')).toBeInTheDocument(); // threat level as a SeverityPill
		expect(screen.getByText('Abuse.ch Feodo')).toBeInTheDocument();
		expect(screen.getByRole('img', { name: /Malware & C2 40/ })).toBeInTheDocument();

		expect(screen.getByRole('table', { name: 'Beaconing suspects' })).toHaveTextContent('188.166.201.72:443');
		const dns = screen.getByRole('table', { name: 'DNS anomalies' });
		expect(dns).toHaveTextContent('xj3kq9.biz');
		expect(dns).toHaveTextContent('300 / 400');
		expect(screen.getByRole('table', { name: 'Lateral movement' })).toHaveTextContent('SMB');
		for (const name of ['From', 'To', 'Service', 'Port', 'Connections', 'Fan-out']) {
			expect(within(screen.getByRole('table', { name: 'Lateral movement' })).getByRole('button', { name })).toBeInTheDocument();
		}

		await fireEvent.click(screen.getByRole('button', { name: 'Investigate device' }));
		expect(goto).toHaveBeenCalledWith('/devices/192.168.1.42');
		await fireEvent.click(screen.getByRole('button', { name: 'View connections' }));
		expect(goto).toHaveBeenCalledWith('/connections?ip=192.168.1.42');

		// the first investigation starts open; opening another closes it
		const first = screen.getByRole('button', { name: /ET MALWARE Example CnC/ });
		const second = screen.getByRole('button', { name: /ET SCAN Example Sweep/ });
		expect(first).toHaveAttribute('aria-expanded', 'true');
		expect(within(first).getByText('Critical')).toBeInTheDocument();
		expect(screen.getByText('Disconnect the device and scan it.')).toBeInTheDocument();
		expect(screen.getByText('tcp, udp')).toBeInTheDocument();
		await fireEvent.click(second);
		expect(first).toHaveAttribute('aria-expanded', 'false');
		expect(second).toHaveAttribute('aria-expanded', 'true');
		expect(screen.queryByText('Disconnect the device and scan it.')).not.toBeInTheDocument();
		expect(screen.getByText('Check who runs a scanner.')).toBeInTheDocument();
		await fireEvent.click(second);
		expect(second).toHaveAttribute('aria-expanded', 'false');
	});
});

describe('Threats page — refresh contract', () => {
	async function settledResult(): Promise<string> {
		await flush();
		return refreshPage();
	}

	it('reports ok when both requests succeed, and advances Updated', async () => {
		vi.mocked(getThreatReport).mockResolvedValue(EMPTY);
		vi.mocked(getThreatIntel).mockResolvedValue(NO_INTEL);
		const { unmount } = render(ThreatsPage);
		expect(await settledResult()).toBe('ok');
		expect(get(pageRefresh)).toMatchObject({ available: true, status: 'ok' });
		expect(get(pageRefresh).updatedAt).not.toBeNull();
		unmount();
	});

	it('reports partial when only the report loads', async () => {
		vi.mocked(getThreatReport).mockResolvedValue(EMPTY);
		vi.mocked(getThreatIntel).mockRejectedValue(new Error('HTTP 503'));
		const { unmount } = render(ThreatsPage);
		expect(await settledResult()).toBe('partial');
		unmount();
	});

	it('reports failed when both fail', async () => {
		vi.mocked(getThreatReport).mockRejectedValue(new Error('HTTP 503'));
		vi.mocked(getThreatIntel).mockRejectedValue(new Error('HTTP 503'));
		const { unmount } = render(ThreatsPage);
		expect(await settledResult()).toBe('failed');
		expect(get(pageRefresh).updatedAt).toBeNull();
		unmount();
	});

	it('does not return while a request is still pending', async () => {
		const intel = deferred<ThreatIntelInfo>();
		vi.mocked(getThreatReport).mockResolvedValue(EMPTY);
		vi.mocked(getThreatIntel).mockReturnValue(intel.promise);
		const { unmount } = render(ThreatsPage);
		let done = false;
		refreshPage().then(() => (done = true));
		await flush();
		expect(done).toBe(false);
		intel.resolve(NO_INTEL);
		await flush();
		expect(done).toBe(true);
		unmount();
	});

	it('shows only the newest range when an older one answers last', async () => {
		const day = deferred<ThreatReport>();
		const week = deferred<ThreatReport>();
		vi.mocked(getThreatReport).mockReturnValueOnce(day.promise).mockReturnValueOnce(week.promise);
		vi.mocked(getThreatIntel).mockResolvedValue(NO_INTEL);
		const { unmount } = render(ThreatsPage);
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		const [, [weekParams]] = vi.mocked(getThreatReport).mock.calls;
		const span = Date.parse(weekParams!.to!) - Date.parse(weekParams!.from!);
		expect(span).toBe(7 * 24 * 3600 * 1000);

		week.resolve({ ...FULL, kill_chains: [chain('10.0.0.7')] });
		await flush();
		day.resolve({ ...FULL, kill_chains: [chain('10.0.0.24')] });
		await flush();
		expect(screen.getByText('10.0.0.7')).toBeInTheDocument();
		expect(screen.queryByText('10.0.0.24')).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByText(/· last 7 days/, { selector: '.page-sub' })).toBeInTheDocument();
		unmount();
	});

	it('writes nothing after the page has gone', async () => {
		const report = deferred<ThreatReport>();
		vi.mocked(getThreatReport).mockReturnValue(report.promise);
		vi.mocked(getThreatIntel).mockResolvedValue(NO_INTEL);
		const { unmount } = render(ThreatsPage);
		await flush();
		unmount();
		expect(get(pageRefresh)).toMatchObject({ available: false, updatedAt: null });
		report.resolve(FULL);
		await flush();
		expect(get(pageRefresh)).toMatchObject({ available: false, updatedAt: null, status: null });
		expect(await refreshPage()).toBe('skipped');
	});
});

// Accuracy audit 2026-11-06
describe('Threats page — what the figures count', () => {
	it('says the alert events need attention and how many informational ones are left out (I8)', async () => {
		vi.mocked(getThreatReport).mockResolvedValue({ ...FULL, summary: { ...FULL.summary, informational_events: 83_490 } });
		vi.mocked(getThreatIntel).mockResolvedValue(INTEL);
		render(ThreatsPage);
		await vi.waitFor(() =>
			expect(screen.getByText('1.5K alert events need attention · 83.5K informational not counted. NetTap found 2 investigations.')).toBeInTheDocument(),
		);
		expect(screen.queryByText(/Suricata generated/)).not.toBeInTheDocument();
	});

	it('shows the matches seen in the window, and an unavailable state when the scan fails (I7)', async () => {
		vi.mocked(getThreatReport).mockResolvedValue(FULL);
		vi.mocked(getThreatIntel).mockResolvedValue({
			...NO_INTEL,
			feeds: { et_compromised: { label: 'ET Compromised IPs', indicator_count: 3 }, feodo: { label: 'Abuse.ch Feodo', indicator_count: 0 } },
			total_indicators: 3,
		});
		const { unmount } = render(ThreatsPage);
		await vi.waitFor(() => expect(screen.getByText('ET Compromised IPs')).toBeInTheDocument());
		expect(screen.queryByText('Abuse.ch Feodo')).not.toBeInTheDocument();
		expect(screen.getByText(/^Listed internet addresses seen in alerts · /)).toBeInTheDocument();
		unmount();

		vi.mocked(getThreatIntel).mockRejectedValue(new Error('HTTP 500'));
		render(ThreatsPage);
		await vi.waitFor(() => expect(screen.getByText('Threat intel unavailable')).toBeInTheDocument());
	});
});

