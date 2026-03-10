/**
 * Client-side API helpers for log explorer endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Time range options shared by log queries. */
export interface TimeRangeParams {
	from?: string;
	to?: string;
}

export interface LogStatsResponse {
	from: string;
	to: string;
	total_events: number;
	unique_sources: number;
	protocol_count: number;
	total_bytes: number;
}

export interface LogTimelineBucket {
	timestamp: string;
	total: number;
	conn: number;
	dns: number;
	http: number;
	ssl: number;
	files: number;
	dhcp: number;
	smtp: number;
	alert: number;
}

export interface LogTimelineResponse {
	from: string;
	to: string;
	interval: string;
	buckets: LogTimelineBucket[];
}

export interface LogTalkerEntry {
	ip: string;
	count: number;
}

export interface LogTopTalkersResponse {
	from: string;
	to: string;
	talkers: LogTalkerEntry[];
}

export interface LogProtocolEntry {
	protocol: string;
	label: string;
	count: number;
}

export interface LogProtocolBreakdownResponse {
	from: string;
	to: string;
	protocols: LogProtocolEntry[];
}

export interface LogDestinationEntry {
	ip: string;
	count: number;
}

export interface LogTopDestinationsResponse {
	from: string;
	to: string;
	destinations: LogDestinationEntry[];
}

export interface LogDnsEntry {
	domain: string;
	count: number;
}

export interface LogTopDnsResponse {
	from: string;
	to: string;
	queries: LogDnsEntry[];
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function buildQuery(params: Record<string, string | number | undefined>): string {
	const qs = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value !== undefined && value !== '') {
			qs.set(key, String(value));
		}
	}
	const str = qs.toString();
	return str ? `?${str}` : '';
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get aggregate stats for logs (total events, unique sources, etc.).
 */
export async function getLogStats(
	opts: TimeRangeParams = {}
): Promise<LogStatsResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/logs/stats${query}`);

	if (!res.ok) {
		return {
			from: '',
			to: '',
			total_events: 0,
			unique_sources: 0,
			protocol_count: 0,
			total_bytes: 0,
		};
	}

	return res.json();
}

/**
 * Get log event timeline (date_histogram bucketed by protocol type).
 */
export async function getLogTimeline(
	opts: TimeRangeParams & { interval?: string } = {}
): Promise<LogTimelineResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, interval: opts.interval });
	const res = await fetch(`/api/logs/timeline${query}`);

	if (!res.ok) {
		return { from: '', to: '', interval: opts.interval || '1h', buckets: [] };
	}

	return res.json();
}

/**
 * Get top talkers (source IPs by event count).
 */
export async function getLogTopTalkers(
	opts: TimeRangeParams & { limit?: number } = {}
): Promise<LogTopTalkersResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, limit: opts.limit });
	const res = await fetch(`/api/logs/top-talkers${query}`);

	if (!res.ok) {
		return { from: '', to: '', talkers: [] };
	}

	return res.json();
}

/**
 * Get protocol breakdown (event counts per log type).
 */
export async function getLogProtocolBreakdown(
	opts: TimeRangeParams = {}
): Promise<LogProtocolBreakdownResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/logs/protocol-breakdown${query}`);

	if (!res.ok) {
		return { from: '', to: '', protocols: [] };
	}

	return res.json();
}

/**
 * Get top destination IPs by event count.
 */
export async function getLogTopDestinations(
	opts: TimeRangeParams & { limit?: number } = {}
): Promise<LogTopDestinationsResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, limit: opts.limit });
	const res = await fetch(`/api/logs/top-destinations${query}`);

	if (!res.ok) {
		return { from: '', to: '', destinations: [] };
	}

	return res.json();
}

/**
 * Get top DNS queries by count.
 */
export async function getLogTopDns(
	opts: TimeRangeParams & { limit?: number } = {}
): Promise<LogTopDnsResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, limit: opts.limit });
	const res = await fetch(`/api/logs/top-dns${query}`);

	if (!res.ok) {
		return { from: '', to: '', queries: [] };
	}

	return res.json();
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

/**
 * Format a byte count to a human-readable string (e.g. 1.0 KB, 2.5 MB).
 */
export function formatBytes(bytes: number): string {
	if (bytes >= 1_099_511_627_776) return `${(bytes / 1_099_511_627_776).toFixed(1)} TB`;
	if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
	if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
	if (bytes >= 1_024) return `${(bytes / 1_024).toFixed(1)} KB`;
	return `${bytes} B`;
}

/**
 * Format a number with compact notation (e.g. 1.5K, 2.5M).
 */
export function formatCompactNumber(n: number): string {
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
	if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
	return String(n);
}

/**
 * Get the CSS custom property color for a protocol type.
 */
export function protocolColor(protocol: string): string {
	switch (protocol) {
		case 'conn':
			return 'var(--cyan)';
		case 'dns':
			return 'var(--green)';
		case 'http':
			return 'var(--orange)';
		case 'ssl':
			return 'var(--purple)';
		case 'files':
			return 'var(--yellow, #ffd600)';
		case 'dhcp':
			return 'var(--pink, #ff80ab)';
		case 'smtp':
			return 'var(--teal, #64ffda)';
		case 'alert':
			return 'var(--red)';
		default:
			return 'var(--text-muted)';
	}
}

/**
 * Get a human-readable label for a protocol type.
 */
export function protocolLabel(protocol: string): string {
	switch (protocol) {
		case 'conn':
			return 'Connections';
		case 'dns':
			return 'DNS';
		case 'http':
			return 'HTTP';
		case 'ssl':
			return 'TLS';
		case 'files':
			return 'Files';
		case 'dhcp':
			return 'DHCP';
		case 'smtp':
			return 'SMTP';
		case 'alert':
			return 'IDS Alerts';
		default:
			return protocol;
	}
}
