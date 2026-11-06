/**
 * Client-side API helpers for the certificate monitor.
 * Wraps daemon endpoints at /api/certificates.
 */

import { getJson } from './drilldown';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Certificate {
	_id: string;
	timestamp: string;
	domain: string;
	server_name: string;
	subject: string;
	issuer: string;
	not_before: string;
	not_after: string;
	tls_version: string;
	hash_sha256: string;
	source_ip: string;
	destination_ip: string;
	destination_port: number | string;
	validation_status: string;
	status: 'valid' | 'expiring' | 'expired' | 'self-signed';
	// OLD CODE START — 2026-11-01: now sent on every row (null when the cert has no expiry date)
	// days_until_expiry?: number;
	// OLD CODE END
	days_until_expiry: number | null;
	detection_reason?: string;
	// One row per certificate (Zeek x509.log), joined to the TLS sessions that sent it
	fingerprint: string;
	subject_cn: string;
	subject_full: string;
	issuer_org: string;
	issuer_full: string;
	key_type: string;
	key_length: number | null;
	sig_alg: string;
	serial: string;
	san_dns: string[];
	server_names: string[];
	clients: string[];
	first_seen: string;
	last_seen: string;
	times_seen: number;
	self_signed: boolean;
	/** Sessions per validation status; a session without one is "unchecked" (NET-154). */
	statuses?: Record<string, number>;
}

export interface CertificatesResponse {
	from: string;
	to: string;
	certificates: Certificate[];
	count: number;
	/** Every matching certificate; `certificates` stops at 5,000. */
	total?: number;
	truncated?: boolean;
}

export interface IssuerChange {
	domain: string;
	issuers: string[];
	issuer_count: number;
	certificates: Certificate[];
}

export interface IssuerChangesResponse {
	from: string;
	to: string;
	changes: IssuerChange[];
	count: number;
}

export interface CertStats {
	total_certs: number;
	expiring_count: number;
	expired_count: number;
	self_signed_count: number;
	issuer_changes_count: number;
	from: string;
	to: string;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

function buildTimeQuery(from?: string, to?: string): string {
	const qs = new URLSearchParams();
	if (from) qs.set('from', from);
	if (to) qs.set('to', to);
	return qs.toString();
}

/**
 * List observed TLS certificates.
 */
export async function getCertificates(from?: string, to?: string): Promise<CertificatesResponse> {
	// OLD CODE START — #96: a failure read as "No certificates found"
	// try {
	// 	const res = await fetch(`/api/certificates?${buildTimeQuery(from, to)}`);
	// 	if (!res.ok) return { from: '', to: '', certificates: [], count: 0 };
	// 	return res.json();
	// } catch {
	// 	return { from: '', to: '', certificates: [], count: 0 };
	// }
	// OLD CODE END
	const res = await fetch(`/api/certificates?${buildTimeQuery(from, to)}`);
	if (!res.ok) throw new Error(`Certificates failed: HTTP ${res.status}`);
	return res.json();
}

/**
 * Get certificates expiring within N days.
 */
export async function getExpiringCerts(days = 30, from?: string, to?: string): Promise<CertificatesResponse> {
	// OLD CODE START — #96: a failure read as "No certificates found"
	// try {
	// 	const qs = new URLSearchParams();
	// 	qs.set('days', String(days));
	// 	if (from) qs.set('from', from);
	// 	if (to) qs.set('to', to);
	// 	const res = await fetch(`/api/certificates/expiring?${qs.toString()}`);
	// 	if (!res.ok) return { from: '', to: '', certificates: [], count: 0 };
	// 	return res.json();
	// } catch {
	// 	return { from: '', to: '', certificates: [], count: 0 };
	// }
	// OLD CODE END
	const qs = new URLSearchParams();
	qs.set('days', String(days));
	if (from) qs.set('from', from);
	if (to) qs.set('to', to);
	const res = await fetch(`/api/certificates/expiring?${qs.toString()}`);
	if (!res.ok) throw new Error(`Expiring certificates failed: HTTP ${res.status}`);
	return res.json();
}

/**
 * Get self-signed certificates.
 */
export async function getSelfSignedCerts(from?: string, to?: string): Promise<CertificatesResponse> {
	// OLD CODE START — #96: a failure read as "No certificates found"
	// try {
	// 	const res = await fetch(`/api/certificates/self-signed?${buildTimeQuery(from, to)}`);
	// 	if (!res.ok) return { from: '', to: '', certificates: [], count: 0 };
	// 	return res.json();
	// } catch {
	// 	return { from: '', to: '', certificates: [], count: 0 };
	// }
	// OLD CODE END
	const res = await fetch(`/api/certificates/self-signed?${buildTimeQuery(from, to)}`);
	if (!res.ok) throw new Error(`Self-signed certificates failed: HTTP ${res.status}`);
	return res.json();
}

/**
 * Get issuer change detections.
 */
export async function getIssuerChanges(from?: string, to?: string): Promise<IssuerChangesResponse> {
	// OLD CODE START — #96: a failure hid the MITM warning as if no issuer had changed
	// try {
	// 	const res = await fetch(`/api/certificates/issuer-changes?${buildTimeQuery(from, to)}`);
	// 	if (!res.ok) return { from: '', to: '', changes: [], count: 0 };
	// 	return res.json();
	// } catch {
	// 	return { from: '', to: '', changes: [], count: 0 };
	// }
	// OLD CODE END
	const res = await fetch(`/api/certificates/issuer-changes?${buildTimeQuery(from, to)}`);
	if (!res.ok) throw new Error(`Issuer change check failed: HTTP ${res.status}`);
	return res.json();
}

// OLD CODE START — 2026-11-02: zeros on failure showed "0 certificates" as fact
// /**
//  * Get certificate hero card stats.
//  */
// export async function getCertStats(from?: string, to?: string): Promise<CertStats> {
// 	try {
// 		const res = await fetch(`/api/certificates/stats?${buildTimeQuery(from, to)}`);
// 		if (!res.ok) {
// 			return {
// 				total_certs: 0,
// 				expiring_count: 0,
// 				expired_count: 0,
// 				self_signed_count: 0,
// 				issuer_changes_count: 0,
// 				from: '',
// 				to: '',
// 			};
// 		}
// 		return res.json();
// 	} catch {
// 		return {
// 			total_certs: 0,
// 			expiring_count: 0,
// 			expired_count: 0,
// 			self_signed_count: 0,
// 			issuer_changes_count: 0,
// 			from: '',
// 			to: '',
// 		};
// 	}
// }
// OLD CODE END

/**
 * Get certificate hero card stats; null when they couldn't be loaded, so the page
 * shows a dash instead of zeros that look like real counts.
 */
export async function getCertStats(from?: string, to?: string): Promise<CertStats | null> {
	try {
		const res = await fetch(`/api/certificates/stats?${buildTimeQuery(from, to)}`);
		return res.ok ? await res.json() : null;
	} catch {
		return null;
	}
}

// ---------------------------------------------------------------------------
// Overview (NET-154): every figure the Certificates page shows, from one complete pass
// ---------------------------------------------------------------------------

export type CertSeverity = 'high' | 'medium' | 'low';

export type FindingKind =
	| 'unverified-alongside-verified'
	| 'unverified'
	| 'expired-at-use'
	| 'chain-expired'
	| 'weak'
	| 'device-expiry';

/** One certificate: x509 details (blank when `details_available` is false) and its sessions. */
export interface CertDetail {
	fingerprint: string;
	details_available: boolean;
	subject: string;
	subject_cn: string;
	subject_full: string;
	issuer: string;
	issuer_org: string;
	issuer_full: string;
	not_before: string;
	not_after: string;
	key_type: string;
	key_length: number | null;
	sig_alg: string;
	serial: string;
	san_dns: string[];
	self_signed: boolean;
	authority: string | null;
	sessions: number;
	first_seen: string;
	last_seen: string;
	statuses: Record<string, number>;
	verified: boolean;
	tls_versions: Record<string, number>;
	sites: string[];
	sites_total: number;
	servers: string[];
	servers_total: number;
	clients: string[];
	clients_total: number;
}

/** A site is the server name a device asked for; without one, the server's address. */
export interface CertSite {
	id: string;
	name: string | null;
	server: string | null;
	sessions: number;
	first_seen: string;
	last_seen: string;
	statuses: Record<string, number>;
	verified: boolean;
	scope: 'local' | 'public' | 'unknown' | 'mixed';
	certificates: string[];
	certificates_total: number;
	clients: string[];
	clients_total: number;
	servers: string[];
	servers_total: number;
	authorities: string[];
	worst: CertSeverity | null;
}

export interface CertFinding {
	id: string;
	kind: FindingKind;
	severity: CertSeverity;
	site_id: string;
	site: string | null;
	server: string | null;
	servers: string[];
	fingerprint: string;
	/**
	 * Only the sessions the finding is about: the failing ones for a verification finding, the
	 * ones after expiry for expired-at-use. `last_seen`, `servers` and `clients` cover the same.
	 */
	sessions: number;
	last_seen: string;
	clients: string[];
	clients_total: number;
	/** Failing validation statuses and their session counts. */
	failed?: Record<string, number>;
	authority?: string | null;
	other_authority?: string | null;
	not_after?: string;
	weaknesses?: string[];
	port?: number | string | null;
	days_left?: number | null;
}

/** A server on your network, for the certificate it presented last. */
export interface CertDevice {
	id: string;
	server: string | null;
	port: number | string | null;
	site_id: string;
	site: string | null;
	fingerprint: string;
	details_available: boolean;
	authority: string | null;
	not_after: string | null;
	days_left: number | null;
	self_signed: boolean;
	statuses: Record<string, number>;
	verified: boolean;
	sessions: number;
	last_seen: string;
	certificates_total: number;
	clients: string[];
	clients_total: number;
}

export interface QuietSwitch {
	site_id: string;
	site: string | null;
	server: string | null;
	authorities: string[];
	certificates: string[];
}

export interface CertSummary {
	certificates: number;
	certificates_without_details: number;
	sites: number;
	sessions: number;
	sessions_with_details: number;
	sessions_without_details: number;
	findings: { high: number; medium: number; low: number; total: number };
	local_certificates: number;
	local_endpoints: number;
	soonest_local_expiry_days: number | null;
}

export interface CertificateOverview {
	from: string;
	to: string;
	summary: CertSummary;
	sites: CertSite[];
	sites_total: number;
	sites_truncated: boolean;
	findings: CertFinding[];
	findings_total: number;
	findings_truncated: boolean;
	devices: CertDevice[];
	devices_total: number;
	devices_truncated: boolean;
	quiet_switches: QuietSwitch[];
	/** Every certificate a returned site, finding or device row refers to; the only certificate list sent. */
	details: Record<string, CertDetail>;
}

/**
 * Every figure the Certificates page shows. Throws with the daemon's reason (busy, too slow,
 * too much data) so the page can say why, never an empty overview that reads as "none".
 */
// OLD CODE START — NET-160: the whole window only; a drill-down now asks for one site and/or server
// export async function getCertificateOverview(from: string, to: string): Promise<CertificateOverview> {
// 	const res = await fetch(`/api/certificates/overview?${buildTimeQuery(from, to)}`);
// OLD CODE END
export async function getCertificateOverview(
	from: string,
	to: string,
	/** Only the sessions for this SNI name and/or this server address; the daemon filters before counting. */
	filter: { site?: string | null; server?: string | null } = {},
): Promise<CertificateOverview> {
	const qs = new URLSearchParams(buildTimeQuery(from, to));
	if (filter.site) qs.set('site', filter.site);
	if (filter.server) qs.set('server', filter.server);
	// OLD CODE START — a copy of api/drilldown.ts getJson's error-reason code
	// const res = await fetch(`/api/certificates/overview?${qs.toString()}`);
	// if (!res.ok) {
	// 	const reason = await res
	// 		.json()
	// 		.then((body: unknown) => (body && typeof body === 'object' && 'error' in body ? String(body.error) : ''))
	// 		.catch(() => '');
	// 	throw new Error(reason || `Certificate overview failed: HTTP ${res.status}`);
	// }
	// const body: unknown = await res.json();
	// OLD CODE END
	const body = await getJson(`/api/certificates/overview?${qs.toString()}`, 'Certificate overview');
	// Every part the page reads, so a malformed reply is an error, never a blank that reads as "none"
	const o = body as Partial<CertificateOverview> | null;
	const wellFormed =
		!!o &&
		typeof o === 'object' &&
		!!o.summary &&
		typeof o.summary === 'object' &&
		[o.sites, o.findings, o.devices, o.quiet_switches].every(Array.isArray) &&
		!!o.details &&
		typeof o.details === 'object';
	if (!wellFormed) {
		throw new Error('Certificate overview failed: the reply was malformed');
	}
	return o as CertificateOverview;
}
