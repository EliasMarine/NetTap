/**
 * Client-side API helpers for the certificate monitor.
 * Wraps daemon endpoints at /api/certificates.
 */

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
	days_until_expiry?: number;
	detection_reason?: string;
}

export interface CertificatesResponse {
	from: string;
	to: string;
	certificates: Certificate[];
	count: number;
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
	self_signed_count: number;
	issuer_changes_count: number;
	from: string;
	to: string;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8880';

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
	try {
		const res = await fetch(`${API_BASE}/api/certificates?${buildTimeQuery(from, to)}`);
		if (!res.ok) return { from: '', to: '', certificates: [], count: 0 };
		return res.json();
	} catch {
		return { from: '', to: '', certificates: [], count: 0 };
	}
}

/**
 * Get certificates expiring within N days.
 */
export async function getExpiringCerts(days = 30, from?: string, to?: string): Promise<CertificatesResponse> {
	try {
		const qs = new URLSearchParams();
		qs.set('days', String(days));
		if (from) qs.set('from', from);
		if (to) qs.set('to', to);
		const res = await fetch(`${API_BASE}/api/certificates/expiring?${qs.toString()}`);
		if (!res.ok) return { from: '', to: '', certificates: [], count: 0 };
		return res.json();
	} catch {
		return { from: '', to: '', certificates: [], count: 0 };
	}
}

/**
 * Get self-signed certificates.
 */
export async function getSelfSignedCerts(from?: string, to?: string): Promise<CertificatesResponse> {
	try {
		const res = await fetch(`${API_BASE}/api/certificates/self-signed?${buildTimeQuery(from, to)}`);
		if (!res.ok) return { from: '', to: '', certificates: [], count: 0 };
		return res.json();
	} catch {
		return { from: '', to: '', certificates: [], count: 0 };
	}
}

/**
 * Get issuer change detections.
 */
export async function getIssuerChanges(from?: string, to?: string): Promise<IssuerChangesResponse> {
	try {
		const res = await fetch(`${API_BASE}/api/certificates/issuer-changes?${buildTimeQuery(from, to)}`);
		if (!res.ok) return { from: '', to: '', changes: [], count: 0 };
		return res.json();
	} catch {
		return { from: '', to: '', changes: [], count: 0 };
	}
}

/**
 * Get certificate hero card stats.
 */
export async function getCertStats(from?: string, to?: string): Promise<CertStats> {
	try {
		const res = await fetch(`${API_BASE}/api/certificates/stats?${buildTimeQuery(from, to)}`);
		if (!res.ok) {
			return {
				total_certs: 0,
				expiring_count: 0,
				self_signed_count: 0,
				issuer_changes_count: 0,
				from: '',
				to: '',
			};
		}
		return res.json();
	} catch {
		return {
			total_certs: 0,
			expiring_count: 0,
			self_signed_count: 0,
			issuer_changes_count: 0,
			from: '',
			to: '',
		};
	}
}
