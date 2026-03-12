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

export interface DnsStats {
	total_queries: number;
	unique_domains: number;
	nxdomain_count: number;
	avg_resolution_ms: number;
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

export async function getTopDomains(
	opts: { from?: string; to?: string; limit?: number } = {}
): Promise<{ from: string; to: string; domains: TopDomain[] }> {
	const query = buildQuery({ from: opts.from, to: opts.to, limit: opts.limit });
	const res = await fetch(`/api/dns/top-domains${query}`);

	if (!res.ok) {
		return { from: '', to: '', domains: [] };
	}

	return res.json();
}

export async function getDeviceDns(
	ip: string,
	opts: { from?: string; to?: string } = {}
): Promise<{ device_ip: string; from: string; to: string; domains: DeviceDnsEntry[] }> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/dns/device/${encodeURIComponent(ip)}${query}`);

	if (!res.ok) {
		return { device_ip: ip, from: '', to: '', domains: [] };
	}

	return res.json();
}

export async function getNxdomains(
	opts: { from?: string; to?: string } = {}
): Promise<{ from: string; to: string; nxdomains: NxdomainEntry[] }> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/dns/nxdomain${query}`);

	if (!res.ok) {
		return { from: '', to: '', nxdomains: [] };
	}

	return res.json();
}

export async function getQueryTypes(
	opts: { from?: string; to?: string } = {}
): Promise<{ from: string; to: string; types: QueryTypeEntry[] }> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/dns/types${query}`);

	if (!res.ok) {
		return { from: '', to: '', types: [] };
	}

	return res.json();
}

export async function getDnsTimeline(
	opts: { from?: string; to?: string; interval?: string } = {}
): Promise<{ from: string; to: string; interval: string; series: TimelineEntry[] }> {
	const query = buildQuery({ from: opts.from, to: opts.to, interval: opts.interval });
	const res = await fetch(`/api/dns/timeline${query}`);

	if (!res.ok) {
		return { from: '', to: '', interval: '1m', series: [] };
	}

	return res.json();
}

export async function getSuspiciousDns(
	opts: { from?: string; to?: string } = {}
): Promise<{ from: string; to: string; suspicious: SuspiciousEntry[] }> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/dns/suspicious${query}`);

	if (!res.ok) {
		return { from: '', to: '', suspicious: [] };
	}

	return res.json();
}

export async function getDnsStats(
	opts: { from?: string; to?: string } = {}
): Promise<DnsStats> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/dns/stats${query}`);

	if (!res.ok) {
		return {
			total_queries: 0,
			unique_domains: 0,
			nxdomain_count: 0,
			avg_resolution_ms: 0,
		};
	}

	return res.json();
}
