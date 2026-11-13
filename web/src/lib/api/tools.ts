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

/** NET-262: what an A or AAAA answer points at; unspecified is 0.0.0.0 or :: (often a blocked name) */
export type DnsScope = 'private' | 'public' | 'loopback' | 'unspecified';

/** NET-262: one answer from a resolver compare */
export interface DnsCompareAnswer extends DnsReconRecord {
	/** Owner, class, type and data without the TTL: equal keys are the same record */
	key: string;
	/** A and AAAA answers only */
	scope?: DnsScope;
}

export interface DnsCompareReply {
	resolver: string;
	/** dig's status (NOERROR, NXDOMAIN, SERVFAIL, …); null when no reply came back */
	status: string | null;
	answers: DnsCompareAnswer[];
	/** The lowest answer TTL in seconds; null with no answers */
	ttl: number | null;
	latency_ms: number | null;
	error: string | null;
	/** More than 100 answers came back; `answers` holds 100 of them, in key order */
	truncated: boolean;
}

export interface DnsCompareResult {
	name: string;
	record_type: string;
	results: DnsCompareReply[];
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
	// OLD CODE START — 2026-11-06 (S12): the daemon sent 0 ms when no reply came back
	// rtt_min: number;
	// rtt_avg: number;
	// rtt_max: number;
	// rtt_mdev: number;
	// OLD CODE END
	/** null when no reply came back (100% loss): there is no round trip to time */
	rtt_min: number | null;
	rtt_avg: number | null;
	rtt_max: number | null;
	rtt_mdev: number | null;
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
	/** S1: openssl's own verdict on the chain and the name; null when nothing was checked */
	trusted: boolean | null;
	/** Every reason verification failed ("self-signed certificate", "hostname mismatch") */
	verify_errors: string[];
	/** Whether the certificate covers the host asked for; null when not checked */
	name_match: boolean | null;
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
 * Ask several resolvers the same question (NET-262). Throws with the daemon's reason on failure.
 */
export async function dnsCompare(name: string, recordType: string, resolvers: string[]): Promise<DnsCompareResult> {
	const res = await fetch('/api/tools/dns-compare', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ name, record_type: recordType, resolvers }),
	});

	if (!res.ok) {
		const data = await res.json().catch(() => ({}));
		throw new Error(data.error || `Resolver compare failed (HTTP ${res.status})`);
	}

	const data = await res.json();
	if (!Array.isArray(data?.results)) throw new Error('NetTap sent a reply the page cannot read.');
	return data as DnsCompareResult;
}

/**
 * Look up a MAC address vendor (OUI).
 */
export async function macLookup(mac: string): Promise<MacLookupResult> {
	const res = await fetch(`/api/tools/mac-lookup/${encodeURIComponent(mac)}`);

	// OLD CODE START — #96: a failed request read as "Not Found / Unknown vendor"
	// if (!res.ok) {
	// 	return {
	// 		mac,
	// 		oui_prefix: '',
	// 		vendor: '',
	// 		found: false,
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) {
		const data = await res.json().catch(() => ({}));
		throw new Error(data.error || `MAC lookup failed: HTTP ${res.status}`);
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
			rtt_min: null,
			rtt_avg: null,
			rtt_max: null,
			rtt_mdev: null,
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
			trusted: null,
			verify_errors: [],
			name_match: null,
			error: data.error || `SSL cert inspection failed (HTTP ${res.status})`,
		};
	}

	return res.json();
}
