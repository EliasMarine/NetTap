/** Fixtures for /api/certificates (daemon/api/certificates.py), reached through the web catch-all. */
import type { CertStats, Certificate, CertificatesResponse, IssuerChangesResponse } from '../../../src/lib/api/certificates.ts';
import { DAY, HOUR, iso, MIN, type FixtureRoute } from './types.ts';

const FROM = iso(24 * HOUR);
const TO = iso(0);

interface CertSeed {
	domain: string;
	issuer: string;
	status: Certificate['status'];
	daysLeft: number;
	client: string;
	server: string;
	times: number;
}

const hex = (n: number) => n.toString(16).padStart(2, '0').repeat(32);

function toCert(s: CertSeed, i: number): Certificate {
	const selfSigned = s.status === 'self-signed';
	const subject = `CN=${s.domain}`;
	const issuer = selfSigned ? subject : `CN=${s.issuer}, O=Example Trust`;
	return {
		_id: `fx-cert-${i + 1}`,
		timestamp: iso((i + 1) * 20 * MIN),
		domain: s.domain,
		server_name: s.domain,
		subject,
		issuer,
		not_before: iso(Math.max(30, 365 - s.daysLeft) * DAY),
		not_after: iso(-s.daysLeft * DAY), // a negative age is in the future
		tls_version: 'TLSv12',
		hash_sha256: hex(i + 1),
		source_ip: s.client,
		destination_ip: s.server,
		destination_port: 443,
		validation_status: selfSigned ? 'self signed certificate' : s.status === 'expired' ? 'certificate has expired' : 'ok',
		status: s.status,
		days_until_expiry: s.daysLeft,
		fingerprint: hex(i + 1),
		subject_cn: s.domain,
		subject_full: subject,
		issuer_org: selfSigned ? s.domain : 'Example Trust',
		issuer_full: issuer,
		key_type: 'rsa',
		key_length: 2048,
		sig_alg: 'sha256WithRSAEncryption',
		serial: `0${i + 1}A4F2C1`,
		san_dns: [s.domain],
		server_names: [s.domain],
		clients: [s.client],
		first_seen: iso((i + 2) * DAY),
		last_seen: iso((i + 1) * 20 * MIN),
		times_seen: s.times,
		self_signed: selfSigned,
	};
}

const CERT_SEEDS: CertSeed[] = [
	{ domain: 'www.example.com', issuer: 'Example Trust CA 1', status: 'valid', daysLeft: 200, client: '192.168.1.42', server: '203.0.113.10', times: 184 },
	{ domain: 'api.example.net', issuer: 'Example Trust CA 1', status: 'valid', daysLeft: 85, client: '192.168.1.23', server: '198.51.100.30', times: 61 },
	{ domain: 'mail.example.org', issuer: 'Example Trust CA 2', status: 'expiring', daysLeft: 12, client: '192.168.1.42', server: '192.0.2.25', times: 17 },
	{ domain: 'legacy.example.com', issuer: 'Example Trust CA 2', status: 'expired', daysLeft: -9, client: '192.168.1.80', server: '203.0.113.77', times: 5 },
	{ domain: 'printer.lan.example.com', issuer: '', status: 'self-signed', daysLeft: 2900, client: '192.168.1.23', server: '192.168.1.200', times: 42 },
];

const CERTS = CERT_SEEDS.map(toCert);
const byStatus = (status: Certificate['status']) => CERTS.filter((c) => c.status === status);

const list = (certificates: Certificate[]) => ({ from: FROM, to: TO, certificates, count: certificates.length }) satisfies CertificatesResponse;

const CHANGES_EMPTY = { from: FROM, to: TO, changes: [], count: 0 } satisfies IssuerChangesResponse;
const CHANGES = {
	...CHANGES_EMPTY,
	changes: [
		{
			domain: 'www.example.com',
			issuers: ['CN=Example Trust CA 1, O=Example Trust', 'CN=Unfamiliar Example CA, O=Example Unknown'],
			issuer_count: 2,
			certificates: [CERTS[0], { ...CERTS[0], _id: 'fx-cert-1b', issuer: 'CN=Unfamiliar Example CA, O=Example Unknown', issuer_full: 'CN=Unfamiliar Example CA, O=Example Unknown', issuer_org: 'Example Unknown', fingerprint: hex(99), hash_sha256: hex(99), times_seen: 2 }],
		},
	],
	count: 1,
} satisfies IssuerChangesResponse;

const STATS_EMPTY = { total_certs: 0, expiring_count: 0, expired_count: 0, self_signed_count: 0, issuer_changes_count: 0, from: FROM, to: TO } satisfies CertStats;
const STATS = { total_certs: CERTS.length, expiring_count: 1, expired_count: 1, self_signed_count: 1, issuer_changes_count: 1, from: FROM, to: TO } satisfies CertStats;

export const CERTIFICATE_ROUTES: FixtureRoute[] = [
	{ path: '/api/certificates', empty: list([]), populated: list(CERTS) },
	{ path: '/api/certificates/expiring', empty: list([]), populated: list(byStatus('expiring')) },
	{ path: '/api/certificates/self-signed', empty: list([]), populated: list(byStatus('self-signed')) },
	{ path: '/api/certificates/issuer-changes', empty: CHANGES_EMPTY, populated: CHANGES },
	{ path: '/api/certificates/stats', empty: STATS_EMPTY, populated: STATS },
];
