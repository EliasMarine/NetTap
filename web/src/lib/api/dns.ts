/**
 * Client-side API helpers for DNS analytics endpoints.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TopDomain {
	domain: string;
	count: number;
	unique_clients: number;
}

export interface DeviceDnsEntry {
	domain: string;
	count: number;
	query_types: { type: string; count: number }[];
}

export interface NxdomainEntry {
	domain: string;
	count: number;
	clients: string[];
}

export interface QueryTypeEntry {
	type: string;
	count: number;
}

export interface TimelineEntry {
	timestamp: string;
	count: number;
}

export interface SuspiciousEntry {
	type: string;
	domain: string;
	count: number;
	severity: string;
	description: string;
	length?: number;
	unique_clients?: number;
}

// OLD CODE START — NET-225: no median, and a window with nothing answered read 0 ms
// export interface DnsStats {
// 	total_queries: number;
// 	unique_domains: number;
// 	nxdomain_count: number;
// 	avg_resolution_ms: number;
// }
// OLD CODE END
export interface DnsStats {
	total_queries: number;
	unique_domains: number;
	nxdomain_count: number;
	/** null when no lookup in the window was answered, so nothing was timed */
	avg_resolution_ms: number | null;
	/** the typical lookup: a few 20 s retries pull the mean far above it */
	median_resolution_ms: number | null;
}

/** NET-225 (DNS-1): Zeek's dns.log holds plain DNS only. */
export const ENCRYPTED_DNS_NOTE =
	"Only plain DNS shows here. Lookups sent over DNS over HTTPS (DoH) or DNS over TLS (DoT) are encrypted, so NetTap can't see the names they ask for.";

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

export async function getTopDomains(
	opts: { from?: string; to?: string; limit?: number } = {}
): Promise<{ from: string; to: string; domains: TopDomain[] }> {
	const query = buildQuery({ from: opts.from, to: opts.to, limit: opts.limit });
	const res = await fetch(`/api/dns/top-domains${query}`);

	// OLD CODE START — #96: a failed request read as "No domains recorded"
	// if (!res.ok) {
	// 	return { from: '', to: '', domains: [] };
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Top domains failed: HTTP ${res.status}`);

	return res.json();
}

export async function getDeviceDns(
	ip: string,
	opts: { from?: string; to?: string } = {}
): Promise<{ device_ip: string; from: string; to: string; domains: DeviceDnsEntry[] }> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/dns/device/${encodeURIComponent(ip)}${query}`);

	// OLD CODE START — #96: a failed request read as "No DNS records" for the device
	// if (!res.ok) {
	// 	return { device_ip: ip, from: '', to: '', domains: [] };
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Device DNS failed: HTTP ${res.status}`);

	return res.json();
}

export async function getNxdomains(
	opts: { from?: string; to?: string } = {}
): Promise<{ from: string; to: string; nxdomains: NxdomainEntry[] }> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/dns/nxdomain${query}`);

	// OLD CODE START — #96: a failed request read as "No NXDOMAIN errors detected"
	// if (!res.ok) {
	// 	return { from: '', to: '', nxdomains: [] };
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`NXDOMAIN list failed: HTTP ${res.status}`);

	return res.json();
}

export async function getQueryTypes(
	opts: { from?: string; to?: string } = {}
): Promise<{ from: string; to: string; types: QueryTypeEntry[] }> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/dns/types${query}`);

	// OLD CODE START — #96: a failed request read as no query types
	// if (!res.ok) {
	// 	return { from: '', to: '', types: [] };
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Query types failed: HTTP ${res.status}`);

	return res.json();
}

export async function getDnsTimeline(
	opts: { from?: string; to?: string; interval?: string } = {}
): Promise<{ from: string; to: string; interval: string; series: TimelineEntry[] }> {
	const query = buildQuery({ from: opts.from, to: opts.to, interval: opts.interval });
	const res = await fetch(`/api/dns/timeline${query}`);

	// OLD CODE START — #96: a failed request read as an empty timeline
	// if (!res.ok) {
	// 	return { from: '', to: '', interval: '1m', series: [] };
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`DNS timeline failed: HTTP ${res.status}`);

	return res.json();
}

export async function getSuspiciousDns(
	opts: { from?: string; to?: string } = {}
): Promise<{ from: string; to: string; suspicious: SuspiciousEntry[] }> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/dns/suspicious${query}`);

	// OLD CODE START — #96: a failed check read as "No suspicious DNS patterns detected"
	// if (!res.ok) {
	// 	return { from: '', to: '', suspicious: [] };
	// }
	// OLD CODE END
	if (!res.ok) {
		throw new Error(`Suspicious DNS check failed: HTTP ${res.status}`);
	}

	return res.json();
}

export async function getDnsStats(
	opts: { from?: string; to?: string } = {}
): Promise<DnsStats> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/dns/stats${query}`);

	// OLD CODE START — #96: a failed request read as 0 queries
	// if (!res.ok) {
	// 	return {
	// 		total_queries: 0,
	// 		unique_domains: 0,
	// 		nxdomain_count: 0,
	// 		avg_resolution_ms: 0,
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`DNS stats failed: HTTP ${res.status}`);

	return res.json();
}
