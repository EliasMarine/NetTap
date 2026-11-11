/**
 * Client-side API helpers for the Threat Intelligence page.
 */

// Types
export interface ThreatReportSummary {
	threat_score: number;
	threat_level: string;
	total_groups: number;
	/** Events in the groups above info; informational_events are the rest (I8). */
	total_events: number;
	informational_events?: number;
	categories: Record<string, { label: string; groups: number; events: number }>;
	top_threats: SmartAlertItem[];
	kill_chains: KillChain[];
	baseline: BaselineInfo | null;
	/** NET-239: scoring findings left out by suppressions or false-positive marks. Absent from an older daemon. */
	suppressed_findings?: number;
	/** NET-239: 15 when the busier-than-usual +15 applied, else 0. Absent from an older daemon. */
	busier_window_points?: number;
}

export interface SmartAlertItem {
	signature_id: number;
	signature: string;
	severity: number;
	severity_label: string;
	category: string;
	category_label: string;
	source_ip: string;
	destination_ip: string;
	count: number;
	first_seen: string;
	last_seen: string;
	trend: string;
	assessment: string;
	destination_port?: number;
}

export interface KillChain {
	source_ip: string;
	stages: number[];
	stage_labels: string[];
	alert_count: number;
	assessment: string;
}

export interface BaselineInfo {
	deviation: number;
	avg_events: number;
	avg_threat_score: number;
	history_points: number;
	is_anomalous: boolean;
	/** NET-239: enough earlier hours (6) to compare with. Absent from an older daemon. */
	ready?: boolean;
	/** NET-239: earlier hours of this window length recorded (history_points counts this hour too). */
	earlier_hours?: number;
}

export interface BeaconSuspect {
	source_ip: string;
	destination_ip: string;
	destination_port: number;
	connection_count: number;
	interval_seconds: number;
	jitter_coefficient: number;
	confidence: number;
	assessment: string;
	/** #96: 'many_hosts' = one of host_count internet hosts this source contacts on schedules */
	pattern?: 'beacon' | 'many_hosts';
	host_count?: number;
}

export interface LateralMovement {
	source_ip: string;
	destination_ip: string;
	port: number;
	service: string;
	connection_count: number;
	first_seen: string | null;
	last_seen: string | null;
	assessment: string;
	fan_out?: number;
}

export interface DnsAnomalies {
	dga_suspects: Array<{
		domain: string;
		entropy: number;
		query_count: number;
		assessment: string;
	}>;
	tunnel_suspects: Array<{
		domain: string;
		subdomain_length: number;
		query_count: number;
		assessment: string;
	}>;
	nxdomain_spikes: Array<{
		source_ip: string;
		total_queries: number;
		nxdomain_count: number;
		nxdomain_ratio: number;
		assessment: string;
	}>;
	suspicious_tlds: Array<{ domain: string; tld: string; query_count: number }>;
}

export interface InvestigationSection {
	source_profile?: Record<string, unknown>;
	destination_profile?: Record<string, unknown>;
	connection_history?: Record<string, unknown>;
}

export interface Investigation {
	alert: {
		signature: string;
		severity_label: string;
		category_label: string;
		source_ip: string;
		destination_ip: string;
		count: number;
	};
	generated_at: string;
	sections: InvestigationSection;
	recommendation: string;
}

export interface ThreatReport {
	from: string;
	to: string;
	generated_at: string;
	summary: ThreatReportSummary;
	kill_chains: KillChain[];
	beaconing: BeaconSuspect[];
	dns_anomalies: DnsAnomalies;
	lateral_movement: LateralMovement[];
	investigations: Investigation[];
	/** #96: detectors that could not run (their lists are empty because nothing was checked) */
	failed_checks?: string[];
	/** #96: detectors a bucket cap stopped part way (their lists are partial) */
	incomplete_checks?: string[];
	/** NET-192 PR 3: present when beaconing came from the background scan (?snapshot=) */
	beaconing_snapshot?: BeaconingSnapshot;
}

/** The Threats page's ranges that read the background beaconing scan. */
export type SnapshotWindow = '24h' | '7d' | '30d';

/**
 * NET-192 PR 3: the background beaconing scan behind a ?snapshot= request.
 * pending: no scan has finished yet; ready: the last scan succeeded and is recent;
 * stale: the rows are from an older scan (the latest failed, or none has finished lately);
 * failed: no scan has succeeded yet.
 */
export interface BeaconingSnapshot {
	window: SnapshotWindow;
	state: 'pending' | 'ready' | 'stale' | 'failed';
	computed_at: string | null;
	last_success_at: string | null;
	last_error: string | null;
	/** the window the served rows scanned */
	from: string | null;
	to: string | null;
}

/** What the page asks for: a background snapshot, or a live scan over exact bounds. */
export type ThreatRequest = { snapshot: SnapshotWindow } | { from: string; to: string };

const SNAPSHOT_WINDOWS: readonly string[] = ['24h', '7d', '30d'] satisfies SnapshotWindow[];

export function isSnapshotWindow(range: string): range is SnapshotWindow {
	return SNAPSHOT_WINDOWS.includes(range);
}

/**
 * The Threats page's range pill as a request (NET-192 PR 3): 24h, 7d and 30d read the
 * background beaconing scan; 1h and 6h are scanned live over `bounds`, the page's own window,
 * so the report and the threat intel count the same span.
 */
export function threatRequest(range: string, bounds: { from: string; to: string }): ThreatRequest {
	return isSnapshotWindow(range) ? { snapshot: range } : bounds;
}

export interface ThreatIntelInfo {
	from: string;
	to: string;
	new_indicators: number;
	/** Indicators seen in alerts inside the window, per feed (I7: not every cached one). */
	feeds: Record<string, { label: string; indicator_count: number }>;
	total_indicators: number;
}

// Helper
function buildQuery(params: Record<string, string | undefined>): string {
	const qs = new URLSearchParams();
	for (const [k, v] of Object.entries(params)) {
		if (v !== undefined && v !== '') qs.set(k, v);
	}
	const s = qs.toString();
	return s ? `?${s}` : '';
}

// Fetch functions
export async function getThreatReport(
	opts: { from?: string; to?: string; snapshot?: SnapshotWindow } = {}
): Promise<ThreatReport> {
	// OLD CODE: const q = buildQuery({ from: opts.from, to: opts.to }); (NET-192 PR 3: ?snapshot=)
	const q = buildQuery({ from: opts.from, to: opts.to, snapshot: opts.snapshot });
	// OLD CODE: const res = await fetch(`/api/threats/report${q}`, { signal: AbortSignal.timeout(30_000) }); (below the scan's time on a busy network)
	// Just above the route's THREAT_SCAN_TIMEOUT_MS (120 s), so the route's answer always arrives first
	const res = await fetch(`/api/threats/report${q}`, { signal: AbortSignal.timeout(125_000) });
	// OLD CODE START — #96: a failed report read as threat level "none" with nothing detected
	// if (!res.ok) {
	// 	return {
	// 		from: '',
	// 		to: '',
	// 		generated_at: '',
	// 		summary: {
	// 			threat_score: 0,
	// 			threat_level: 'none',
	// 			total_groups: 0,
	// 			total_events: 0,
	// 			categories: {},
	// 			top_threats: [],
	// 			kill_chains: [],
	// 			baseline: null
	// 		},
	// 		kill_chains: [],
	// 		beaconing: [],
	// 		dns_anomalies: {
	// 			dga_suspects: [],
	// 			tunnel_suspects: [],
	// 			nxdomain_spikes: [],
	// 			suspicious_tlds: []
	// 		},
	// 		lateral_movement: [],
	// 		investigations: []
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Threat report failed: HTTP ${res.status}`);
	return res.json();
}

export async function getBeaconing(
	opts: { from?: string; to?: string; snapshot?: SnapshotWindow } = {}
): Promise<{ beacons: BeaconSuspect[]; total: number; complete: boolean; beaconing_snapshot?: BeaconingSnapshot }> {
	// OLD CODE: const q = buildQuery({ from: opts.from, to: opts.to }); (NET-192 PR 3: ?snapshot=)
	const q = buildQuery({ from: opts.from, to: opts.to, snapshot: opts.snapshot });
	const res = await fetch(`/api/threats/beaconing${q}`);
	// OLD CODE START — #96: a failure read as "none found"
	// if (!res.ok) return { beacons: [], total: 0 };
	// OLD CODE END
	if (!res.ok) throw new Error(`Beaconing check failed: HTTP ${res.status}`);
	return res.json();
}

export async function getLateralMovement(
	opts: { from?: string; to?: string } = {}
): Promise<{ movements: LateralMovement[]; total: number; complete: boolean }> {
	const q = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/threats/lateral${q}`);
	// OLD CODE START — #96: a failure read as "none found"
	// if (!res.ok) return { movements: [], total: 0 };
	// OLD CODE END
	if (!res.ok) throw new Error(`Lateral movement check failed: HTTP ${res.status}`);
	return res.json();
}

export async function getDnsAnomalies(
	opts: { from?: string; to?: string } = {}
): Promise<DnsAnomalies> {
	const q = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/threats/dns-anomalies${q}`);
	// OLD CODE START — #96: a failure read as "No DNS anomalies detected"
	// if (!res.ok)
	// 	return { dga_suspects: [], tunnel_suspects: [], nxdomain_spikes: [], suspicious_tlds: [] };
	// OLD CODE END
	if (!res.ok) throw new Error(`DNS anomaly check failed: HTTP ${res.status}`);
	return res.json();
}

export async function getThreatIntel(
	opts: { from?: string; to?: string } = {}
): Promise<ThreatIntelInfo> {
	const q = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/threats/intel${q}`);
	// OLD CODE START — #96: a failure read as "none found"
	// if (!res.ok) return { from: '', to: '', new_indicators: 0, feeds: {}, total_indicators: 0 };
	// OLD CODE END
	if (!res.ok) throw new Error(`Threat intel failed: HTTP ${res.status}`);
	return res.json();
}
