/** Fixtures for /api/certificates (daemon/api/certificates.py), reached through the web catch-all. */
import type {
	CertDetail,
	CertDevice,
	CertFinding,
	CertificateOverview,
	CertSite,
	CertStats,
	Certificate,
	CertificatesResponse,
	IssuerChangesResponse,
} from '../../../src/lib/api/certificates.ts';
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

const LEGACY_ROUTES: FixtureRoute[] = [
	{ path: '/api/certificates', empty: list([]), populated: list(CERTS) },
	{ path: '/api/certificates/expiring', empty: list([]), populated: list(byStatus('expiring')) },
	{ path: '/api/certificates/self-signed', empty: list([]), populated: list(byStatus('self-signed')) },
	{ path: '/api/certificates/issuer-changes', empty: CHANGES_EMPTY, populated: CHANGES },
	{ path: '/api/certificates/stats', empty: STATS_EMPTY, populated: STATS },
];

// ---------------------------------------------------------------------------
// /api/certificates/overview (NET-154): the page's one request. The populated reply is the
// approved mockup's network: one finding of each kind, devices' certificates, a quiet switch,
// and one certificate without stored details. Its figures add up (fixtures/certificates.test.ts).
// ---------------------------------------------------------------------------

const LAPTOP = '192.168.1.42';
const DESK = '192.168.1.23';
const IPAD = '192.168.1.70';
const CAMERA = '192.168.1.88';
const PLUG = '192.168.1.61';

interface UseSeed {
	fp: string;
	site: string;
	server: string;
	port: number;
	clients: Record<string, number>;
	statuses: Record<string, number>;
	authority: string | null;
	notAfterDays: number | null;
	extra?: Partial<CertDetail>;
	ago?: number;
}

const USES: UseSeed[] = [
	{ fp: 'C1', site: 'www.example.com', server: '203.0.113.10', port: 443, clients: { [LAPTOP]: 120, [DESK]: 64 }, statuses: { ok: 184 }, authority: 'Example Trust', notAfterDays: 200 },
	{ fp: 'C1B', site: 'www.example.com', server: '203.0.113.10', port: 443, clients: { [LAPTOP]: 2 }, statuses: { 'unable to get local issuer certificate': 2 }, authority: 'Example Unknown', notAfterDays: 365 },
	{ fp: 'C2', site: 'api.example.net', server: '198.51.100.30', port: 443, clients: { [DESK]: 61 }, statuses: { ok: 61 }, authority: 'Google Trust Services', notAfterDays: 85 },
	{ fp: 'C3', site: 'update.vendor-cdn.example', server: '198.51.100.44', port: 443, clients: { [IPAD]: 14 }, statuses: { 'unable to get local issuer certificate': 14 }, authority: 'Vendor Internal CA', notAfterDays: 482 },
	{ fp: 'C4', site: 'cam-cloud.example.net', server: '203.0.113.77', port: 443, clients: { [CAMERA]: 52 }, statuses: { 'certificate has expired': 52 }, authority: 'Example Trust', notAfterDays: -9 },
	{ fp: 'C5', site: 'iot.plugmaker.example', server: '192.0.2.25', port: 443, clients: { [PLUG]: 288 }, statuses: { ok: 288 }, authority: 'Plugmaker Device CA', notAfterDays: 1104, extra: { sig_alg: 'sha1WithRSAEncryption', key_length: 1024 } },
	{ fp: 'C6', site: 'nas.home.example', server: '192.168.1.10', port: 5001, clients: { [LAPTOP]: 20, [IPAD]: 11 }, statuses: { ok: 31 }, authority: "Let's Encrypt", notAfterDays: 12 },
	{ fp: 'C7', site: 'router.lan', server: '192.168.1.1', port: 443, clients: { [LAPTOP]: 9 }, statuses: { 'self signed certificate': 9 }, authority: 'router.lan', notAfterDays: 2950, extra: { self_signed: true, issuer: 'router.lan', issuer_org: '', issuer_full: 'CN=router.lan' } },
	{ fp: 'C8', site: 'printer.lan.example.com', server: '192.168.1.200', port: 443, clients: { [DESK]: 42 }, statuses: { 'self signed certificate': 42 }, authority: 'printer.lan.example.com', notAfterDays: 2900, extra: { self_signed: true, issuer: 'printer.lan.example.com', issuer_org: '', issuer_full: 'CN=printer.lan.example.com' } },
	{ fp: 'C9', site: 'cdn.example-media.net', server: '203.0.113.90', port: 443, clients: { [LAPTOP]: 700, [IPAD]: 300 }, statuses: { ok: 1000 }, authority: 'DigiCert', notAfterDays: 140 },
	{ fp: 'C10', site: 'cdn.example-media.net', server: '203.0.113.91', port: 443, clients: { [LAPTOP]: 204 }, statuses: { ok: 204 }, authority: "Let's Encrypt", notAfterDays: 61 },
	{ fp: 'C11', site: 'static.example-shop.com', server: '198.51.100.7', port: 443, clients: { [DESK]: 6 }, statuses: { ok: 6 }, authority: null, notAfterDays: null },
];

const sum = (counts: Record<string, number>): number => Object.values(counts).reduce((a, b) => a + b, 0);
const busiest = (counts: Record<string, number>): string[] => Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k]) => k);
const isLocal = (ip: string): boolean => ip.startsWith('192.168.');
const verified = (statuses: Record<string, number>): boolean => Object.keys(statuses).length > 0 && Object.keys(statuses).every((s) => s === 'ok');

function detailOf(u: UseSeed, i: number): CertDetail {
	const known = u.authority !== null;
	const last = iso((u.ago ?? i + 1) * 20 * MIN);
	return {
		fingerprint: u.fp,
		details_available: known,
		subject: known ? u.site : '',
		subject_cn: known ? u.site : '',
		subject_full: known ? `CN=${u.site}` : '',
		issuer: known ? `${u.authority} R1` : '',
		issuer_org: known ? (u.authority ?? '') : '',
		issuer_full: known ? `CN=${u.authority} R1, O=${u.authority}` : '',
		not_before: known ? iso(300 * DAY) : '',
		not_after: u.notAfterDays === null ? '' : iso(-u.notAfterDays * DAY),
		key_type: known ? 'rsa' : '',
		key_length: known ? 2048 : null,
		sig_alg: known ? 'sha256WithRSAEncryption' : '',
		serial: known ? `0${i + 1}A4F2C1` : '',
		san_dns: known ? [u.site] : [],
		self_signed: false,
		authority: u.authority,
		sessions: sum(u.statuses),
		first_seen: iso(6 * DAY + i * HOUR),
		last_seen: last,
		statuses: u.statuses,
		verified: verified(u.statuses),
		tls_versions: { TLSv12: sum(u.statuses) },
		sites: [u.site],
		sites_total: 1,
		servers: [u.server],
		servers_total: 1,
		clients: busiest(u.clients),
		clients_total: Object.keys(u.clients).length,
		...u.extra,
	};
}

const DETAILS = USES.map(detailOf);
const detailByFp = Object.fromEntries(DETAILS.map((d) => [d.fingerprint, d]));

function finding(kind: CertFinding['kind'], severity: CertFinding['severity'], fp: string, extra: Partial<CertFinding> = {}): CertFinding {
	const u = USES.find((x) => x.fp === fp)!;
	return {
		id: `${kind}:${u.site}:${fp}`,
		kind,
		severity,
		site_id: u.site,
		site: u.site,
		server: u.server,
		servers: [u.server],
		fingerprint: fp,
		sessions: sum(u.statuses),
		last_seen: detailByFp[fp].last_seen,
		clients: busiest(u.clients),
		clients_total: Object.keys(u.clients).length,
		...extra,
	};
}

const FINDINGS: CertFinding[] = [
	finding('unverified-alongside-verified', 'high', 'C1B', { failed: { 'unable to get local issuer certificate': 2 }, authority: 'Example Unknown', other_authority: 'Example Trust' }),
	finding('expired-at-use', 'medium', 'C4', { not_after: detailByFp.C4.not_after }),
	finding('unverified', 'medium', 'C3', { failed: { 'unable to get local issuer certificate': 14 }, authority: 'Vendor Internal CA', other_authority: null }),
	finding('weak', 'low', 'C5', { weaknesses: ['SHA-1 signature', '1024-bit RSA key'] }),
	finding('device-expiry', 'low', 'C6', { id: 'device-expiry:192.168.1.10:5001:nas.home.example:C6', port: 5001, not_after: detailByFp.C6.not_after, days_left: 12 }),
];

const WORST: Record<string, CertFinding['severity']> = {};
for (const f of FINDINGS) WORST[f.site_id] ??= f.severity;

function sitesOf(): CertSite[] {
	const bySite = new Map<string, UseSeed[]>();
	for (const u of USES) bySite.set(u.site, [...(bySite.get(u.site) ?? []), u]);
	return [...bySite.entries()]
		.map(([site, uses]) => {
			const statuses: Record<string, number> = {};
			const clients: Record<string, number> = {};
			for (const u of uses) {
				for (const [s, n] of Object.entries(u.statuses)) statuses[s] = (statuses[s] ?? 0) + n;
				for (const [c, n] of Object.entries(u.clients)) clients[c] = (clients[c] ?? 0) + n;
			}
			const servers = [...new Set(uses.map((u) => u.server))];
			const scopes = new Set(servers.map((s) => (isLocal(s) ? 'local' : 'public')));
			const details = uses.map((u) => detailByFp[u.fp]);
			return {
				id: site,
				name: site,
				server: null,
				sessions: sum(statuses),
				first_seen: details.map((d) => d.first_seen).sort()[0],
				last_seen: details.map((d) => d.last_seen).sort().at(-1)!,
				statuses,
				verified: verified(statuses),
				scope: scopes.size === 1 ? ([...scopes][0] as CertSite['scope']) : 'mixed',
				certificates: [...uses].sort((a, b) => sum(b.statuses) - sum(a.statuses)).map((u) => u.fp),
				certificates_total: uses.length,
				clients: busiest(clients),
				clients_total: Object.keys(clients).length,
				servers,
				servers_total: servers.length,
				authorities: [...new Set(uses.map((u) => u.authority).filter((a): a is string => a !== null))].sort(),
				worst: WORST[site] ?? null,
			};
		})
		.sort((a, b) => b.sessions - a.sessions || a.id.localeCompare(b.id));
}

const DEVICES: CertDevice[] = USES.filter((u) => isLocal(u.server)).map((u) => {
	const d = detailByFp[u.fp];
	return {
		id: `${u.server}:${u.port}:${u.site}`,
		server: u.server,
		port: u.port,
		site_id: u.site,
		site: u.site,
		fingerprint: u.fp,
		details_available: d.details_available,
		authority: u.authority,
		not_after: d.not_after || null,
		days_left: u.notAfterDays,
		self_signed: d.self_signed,
		statuses: u.statuses,
		verified: d.verified,
		sessions: d.sessions,
		last_seen: d.last_seen,
		certificates_total: 1,
		clients: d.clients,
		clients_total: d.clients_total,
	};
});

function overview(populated: boolean): CertificateOverview {
	const sites = populated ? sitesOf() : [];
	const certificates = populated ? [...DETAILS].sort((a, b) => b.last_seen.localeCompare(a.last_seen)) : [];
	const findings = populated ? FINDINGS : [];
	const devices = populated ? [...DEVICES].sort((a, b) => (a.days_left ?? Infinity) - (b.days_left ?? Infinity)) : [];
	const sessions = certificates.reduce((n, c) => n + c.sessions, 0);
	const withDetails = certificates.filter((c) => c.details_available).reduce((n, c) => n + c.sessions, 0);
	const bySeverity = (s: CertFinding['severity']) => findings.filter((f) => f.severity === s).length;
	return {
		from: iso(7 * DAY),
		to: iso(0),
		summary: {
			certificates: certificates.length,
			certificates_without_details: certificates.filter((c) => !c.details_available).length,
			sites: sites.length,
			sessions,
			sessions_with_details: withDetails,
			sessions_without_details: sessions - withDetails,
			findings: { high: bySeverity('high'), medium: bySeverity('medium'), low: bySeverity('low'), total: findings.length },
			local_certificates: new Set(devices.map((d) => d.fingerprint)).size,
			local_endpoints: devices.length,
			soonest_local_expiry_days: devices.length ? Math.min(...devices.map((d) => d.days_left ?? Infinity)) : null,
		},
		sites,
		sites_total: sites.length,
		sites_truncated: false,
		findings,
		findings_total: findings.length,
		findings_truncated: false,
		devices,
		devices_total: devices.length,
		devices_truncated: false,
		quiet_switches: populated
			? [{ site_id: 'cdn.example-media.net', site: 'cdn.example-media.net', server: null, authorities: ['DigiCert', "Let's Encrypt"], certificates: ['C9', 'C10'] }]
			: [],
		details: populated ? detailByFp : {},
	};
}

export const OVERVIEW_EMPTY = overview(false);
export const OVERVIEW = overview(true);

export const CERTIFICATE_ROUTES: FixtureRoute[] = [
	...LEGACY_ROUTES,
	{ path: '/api/certificates/overview', empty: OVERVIEW_EMPTY, populated: OVERVIEW },
];
