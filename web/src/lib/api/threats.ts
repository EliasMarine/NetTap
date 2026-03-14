/**
 * Client-side API helpers for the Threat Intelligence page.
 */

// Types
export interface ThreatReportSummary {
	threat_score: number;
	threat_level: string;
	total_groups: number;
	total_events: number;
	categories: Record<string, { label: string; groups: number; events: number }>;
	top_threats: SmartAlertItem[];
	kill_chains: KillChain[];
	baseline: BaselineInfo | null;
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
}

export interface ThreatIntelInfo {
	from: string;
	to: string;
	new_indicators: number;
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
	opts: { from?: string; to?: string } = {}
): Promise<ThreatReport> {
	const q = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/threats/report${q}`, { signal: AbortSignal.timeout(30_000) });
	if (!res.ok) {
		return {
			from: '',
			to: '',
			generated_at: '',
			summary: {
				threat_score: 0,
				threat_level: 'none',
				total_groups: 0,
				total_events: 0,
				categories: {},
				top_threats: [],
				kill_chains: [],
				baseline: null
			},
			kill_chains: [],
			beaconing: [],
			dns_anomalies: {
				dga_suspects: [],
				tunnel_suspects: [],
				nxdomain_spikes: [],
				suspicious_tlds: []
			},
			lateral_movement: [],
			investigations: []
		};
	}
	return res.json();
}

export async function getBeaconing(
	opts: { from?: string; to?: string } = {}
): Promise<{ beacons: BeaconSuspect[]; total: number }> {
	const q = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/threats/beaconing${q}`);
	if (!res.ok) return { beacons: [], total: 0 };
	return res.json();
}

export async function getLateralMovement(
	opts: { from?: string; to?: string } = {}
): Promise<{ movements: LateralMovement[]; total: number }> {
	const q = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/threats/lateral${q}`);
	if (!res.ok) return { movements: [], total: 0 };
	return res.json();
}

export async function getDnsAnomalies(
	opts: { from?: string; to?: string } = {}
): Promise<DnsAnomalies> {
	const q = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/threats/dns-anomalies${q}`);
	if (!res.ok)
		return {
			dga_suspects: [],
			tunnel_suspects: [],
			nxdomain_spikes: [],
			suspicious_tlds: []
		};
	return res.json();
}

export async function getThreatIntel(
	opts: { from?: string; to?: string } = {}
): Promise<ThreatIntelInfo> {
	const q = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/threats/intel${q}`);
	if (!res.ok) return { from: '', to: '', new_indicators: 0, feeds: {}, total_indicators: 0 };
	return res.json();
}
