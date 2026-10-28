/**
 * Client-side API helpers for the network tools endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DnsReconRecord {
	name: string;
	ttl: number;
	class: string;
	type: string;
	value: string;
}

export interface DnsReconResult {
	domain: string;
	records: Record<string, DnsReconRecord[]>;
	total_records: number;
	record_types_queried: string[];
	errors: string[];
}

export interface MacLookupResult {
	mac: string;
	oui_prefix: string;
	vendor: string;
	found: boolean;
}

export interface PingReply {
	bytes: number;
	from: string;
	seq: number;
	ttl: number;
	time_ms: number;
}

export interface PingResult {
	target: string;
	raw: string;
	packets_sent: number;
	packets_received: number;
	packet_loss_pct: number;
	rtt_min: number;
	rtt_avg: number;
	rtt_max: number;
	rtt_mdev: number;
	replies: PingReply[];
	error?: string;
}

export interface TracerouteHop {
	hop: number;
	host: string;
	ip: string;
	rtts: number[];
}

export interface TracerouteResult {
	target: string;
	hops: TracerouteHop[];
	total_hops: number;
	raw: string;
	error?: string;
}

export interface SslCertResult {
	host: string;
	port: number;
	subject: Record<string, string>;
	issuer: Record<string, string>;
	not_before: string;
	not_after: string;
	serial: string;
	fingerprint_sha256: string;
	san: string[];
	chain: string[];
	raw: string;
	error?: string;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Perform a DNS reconnaissance lookup for a domain.
 */
export async function dnsRecon(
	domain: string,
	recordTypes?: string[]
): Promise<DnsReconResult> {
	const body: Record<string, unknown> = { domain };
	if (recordTypes) {
		body.record_types = recordTypes;
	}

	const res = await fetch('/api/tools/dns-recon', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
	});

	if (!res.ok) {
		const data = await res.json().catch(() => ({}));
		return {
			domain,
			records: {},
			total_records: 0,
			record_types_queried: recordTypes || [],
			errors: [data.error || `DNS recon failed (HTTP ${res.status})`],
		};
	}

	return res.json();
}

/**
 * Look up a MAC address vendor (OUI).
 */
export async function macLookup(mac: string): Promise<MacLookupResult> {
	const res = await fetch(`/api/tools/mac-lookup/${encodeURIComponent(mac)}`);

	if (!res.ok) {
		return {
			mac,
			oui_prefix: '',
			vendor: '',
			found: false,
		};
	}

	return res.json();
}

/**
 * Ping a target host.
 */
export async function ping(
	target: string,
	count?: number
): Promise<PingResult> {
	const body: Record<string, unknown> = { target };
	if (count !== undefined) {
		body.count = count;
	}

	const res = await fetch('/api/tools/ping', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
	});

	if (!res.ok) {
		const data = await res.json().catch(() => ({}));
		return {
			target,
			raw: '',
			packets_sent: 0,
			packets_received: 0,
			packet_loss_pct: 100,
			rtt_min: 0,
			rtt_avg: 0,
			rtt_max: 0,
			rtt_mdev: 0,
			replies: [],
			error: data.error || `Ping failed (HTTP ${res.status})`,
		};
	}

	return res.json();
}

/**
 * Traceroute to a target host.
 */
export async function traceroute(
	target: string,
	maxHops?: number
): Promise<TracerouteResult> {
	const body: Record<string, unknown> = { target };
	if (maxHops !== undefined) {
		body.max_hops = maxHops;
	}

	const res = await fetch('/api/tools/traceroute', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
	});

	if (!res.ok) {
		const data = await res.json().catch(() => ({}));
		return {
			target,
			hops: [],
			total_hops: 0,
			raw: '',
			error: data.error || `Traceroute failed (HTTP ${res.status})`,
		};
	}

	return res.json();
}

/**
 * Inspect the SSL/TLS certificate of a host.
 */
export async function sslCertInspect(
	host: string,
	port?: number
): Promise<SslCertResult> {
	const body: Record<string, unknown> = { host };
	if (port !== undefined) {
		body.port = port;
	}

	const res = await fetch('/api/tools/ssl-cert', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
	});

	if (!res.ok) {
		const data = await res.json().catch(() => ({}));
		return {
			host,
			port: port || 443,
			subject: {},
			issuer: {},
			not_before: '',
			not_after: '',
			serial: '',
			fingerprint_sha256: '',
			san: [],
			chain: [],
			raw: '',
			error: data.error || `SSL cert inspection failed (HTTP ${res.status})`,
		};
	}

	return res.json();
}
