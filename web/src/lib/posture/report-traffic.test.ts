import { describe, it, expect } from 'vitest';
import { EMPTY_DATA, scoreCategories, type PostureInputs, type PostureSlug } from './score';
import type { ExtraKey, PostureExtras, ReportData } from './report';
import { deviceHint, dnsReport, encryptionReport, patchReport, BITTORRENT, UNKNOWN_HINT } from './report-traffic';
import type { DnsDetail, EncryptionDetail, PatchDetail } from '$api/posture';
import { POSTURE_DNS, POSTURE_ENCRYPTION, POSTURE_ENCRYPTION_EMPTY, POSTURE_PATCH } from '../../../e2e/visual/fixtures/traffic';

const WIN = { from: '2026-11-15T06:00:00.000Z', to: '2026-11-16T06:00:00.000Z' };
function reportData(slug: PostureSlug, o: { inputs?: Partial<PostureInputs>; extras?: PostureExtras; failed?: ExtraKey[]; names?: Map<string, string> } = {}): ReportData {
	const inputs: PostureInputs = { ...EMPTY_DATA, failed: [], health: { health: null, failed: false }, ...o.inputs };
	return { window: WIN, inputs, category: scoreCategories(inputs).find((c) => c.slug === slug)!, extras: o.extras ?? {}, failed: o.failed ?? [], names: o.names ?? new Map() };
}
const protocols = (over: Partial<PostureInputs['protocols']>): Partial<PostureInputs> => ({ protocols: { ...EMPTY_DATA.protocols, ...over } });
const enc = (detail: EncryptionDetail, names?: Map<string, string>) =>
	encryptionReport(reportData('encryption', { inputs: protocols({ encryption: { eligible: detail.eligible, encrypted: detail.encrypted } }), extras: { encryption: detail }, names }));
const params = (href: string) => new URL(href, 'http://x').searchParams;

describe('hints', () => {
	it('come from the top service, else the top port, never lowered by a port or destination (R1-1)', () => {
		// http with a LAN port 8080 keeps HTTP's medium, and says nothing about what the device is
		const h = deviceHint([{ name: 'http', count: 9 }], [{ port: 8080, count: 9 }]);
		expect(h.severity).toBe('medium');
		expect(h.what).not.toMatch(/camera|printer|router is/i);
		expect(deviceHint([{ name: 'unknown', count: 5 }], [{ port: 51413, count: 5 }])).toBe(BITTORRENT);
		expect(deviceHint([], [{ port: 6885, count: 1 }])).toBe(BITTORRENT);
		expect(deviceHint([{ name: 'unknown', count: 5 }], [{ port: 23, count: 5 }]).severity).toBe('high');
		expect(deviceHint([], [{ port: 40000, count: 1 }])).toBe(UNKNOWN_HINT);
	});
});

describe('encryptionReport', () => {
	it('puts the score formula, payload breakdown and private/local-scope figure in the drivers (R1-7)', () => {
		const r = enc(POSTURE_ENCRYPTION);
		expect(r.drivers.formula).toBe('19,800 encrypted ÷ 21,300 connections that can be encrypted = 93%');
		expect(r.drivers.bars.map((b) => [b.key, b.value])).toEqual([['encrypted', 19800], ['both', 260], ['other', 1240]]);
		expect(r.drivers.counts.join(' ')).toContain('180 of the unencrypted connections went to private or local-scope addresses');
		expect(r.drivers.limits.join(' ')).toMatch(/one-way attempt.*counts as unencrypted/);
		expect(r.drivers.limits.join(' ')).toMatch(/one way only, none, or wasn't measured/);
		expect(r.sources).toEqual([{ key: 'devices', label: 'Devices sending unencrypted traffic', state: 'measured' }]);
	});

	it('starts with a device that makes at least half the unencrypted connections, with its hint', () => {
		const r = enc(POSTURE_ENCRYPTION, new Map([['192.168.1.20', 'Laptop']]));
		const start = r.steps.find((s) => s.text.startsWith('Start with'));
		expect(start).toMatchObject({ priority: 'high' });
		expect(start!.text).toContain('Start with Laptop: 73% of the unencrypted connections.');
		expect(start!.text).toContain("NetTap's rule can't see a torrent app's own encryption");
		const laptop = r.findings.find((f) => f.key === 'device-192.168.1.20')!;
		expect(laptop).toMatchObject({ title: 'Ports BitTorrent apps use', severity: 'low', devices: [{ ip: '192.168.1.20', name: 'Laptop' }] });
	});

	it('links a Telnet bucket found only by its port to Log Explorer with its own query, the exclusions and the window (R1-3, R2-5)', () => {
		const query = '(network.protocol:("telnet") OR destination.port:(23)) AND NOT x';
		const detail: EncryptionDetail = {
			...POSTURE_ENCRYPTION,
			excluded_ips: ['192.168.1.199'],
			unencrypted: { ...POSTURE_ENCRYPTION.unencrypted, services: [{ name: 'unknown', count: 1500 }], risky: { ...POSTURE_ENCRYPTION.unencrypted.risky, telnet: { count: 3, logs_query: query } } },
		};
		const step = enc(detail).steps.find((s) => s.text.includes('Telnet'))!;
		expect(step.priority).toBe('high');
		const p = params(step.href!);
		expect(new URL(step.href!, 'http://x').pathname).toBe('/logs');
		expect(Object.fromEntries(p)).toEqual({ type: 'zeek.conn', query, exclude_src: '192.168.1.199', from: detail.from, to: detail.to, range: '24h' });
	});

	it('says how many more connections the devices past the busiest ten made (R1-3)', () => {
		const detail = { ...POSTURE_ENCRYPTION, devices: { ...POSTURE_ENCRYPTION.devices, other: 420 } };
		expect(enc(detail).notes).toEqual([{ text: 'Showing the 10 busiest devices. Other devices on your network made 420 more of these connections.' }]);
		expect(enc(POSTURE_ENCRYPTION).notes).toEqual([]);
	});

	it('explains, at low priority, when most unencrypted connections carried data one way or none', () => {
		const low = enc(POSTURE_ENCRYPTION).steps.find((s) => s.priority === 'low')!;
		expect(low.text).toMatch(/^83% of the unencrypted connections carried data one way or none/);
	});

	it('reads nothing measured, unattributed and failed per source (R1-9)', () => {
		expect(enc(POSTURE_ENCRYPTION_EMPTY).sources[0]).toMatchObject({ state: 'not-measured', note: expect.stringContaining('Data pipeline now:') });
		const hidden = { ...POSTURE_ENCRYPTION, devices: { lan: 0, other: 0, rows: [] } };
		expect(enc(hidden).sources[0]).toMatchObject({ state: 'unattributed', note: expect.stringContaining('inline bridge mode') });
		const failed = encryptionReport(reportData('encryption', { failed: ['encryption'] }));
		expect(failed.sources[0]).toMatchObject({ state: 'failed', note: "Couldn't load devices sending unencrypted traffic: the request failed." });
		expect(failed.findings).toEqual([]);
		expect(failed.kpis[2]).toMatchObject({ value: '—', sub: "Couldn't load" });
	});
});

describe('dnsReport', () => {
	const dns = (detail: DnsDetail) => dnsReport(reportData('dns-security', { inputs: protocols({ dns: { plain: detail.plain, over_tls: detail.over_tls } }), extras: { 'dns-security': detail } }));
	const resolver = (over: Partial<DnsDetail['resolvers']['plain'][number]>) => ({ ...POSTURE_DNS.resolvers.plain[0], ...over });
	const withResolvers = (plain: DnsDetail['resolvers']['plain'], over: Partial<DnsDetail> = {}): DnsDetail => ({ ...POSTURE_DNS, resolvers: { ...POSTURE_DNS.resolvers, plain }, ...over });

	it('splits plain lookups by address scope with the exact filters (R2-3, R2-6)', () => {
		const r = dns(POSTURE_DNS);
		expect(r.drivers.bars.map((b) => [b.label, b.value])).toEqual([
			['DNS-over-TLS', 60],
			['Plain, to private or local-scope addresses', 4200],
			['Plain, to public addresses', 1200],
			['Plain, address unknown', 0],
		]);
		expect(r.drivers.resolvers?.map((x) => [x.ip, x.kind, x.scope])).toContainEqual(['198.51.100.153', 'DNS-over-TLS', 'Public']);
		expect(r.kpis[2]).toMatchObject({ value: '1,200' });
	});

	it('judges a local resolver from its own upstream counts, and never asks for encryption it can’t see (R1-2)', () => {
		const findings = (u: { plain_public: number; dot: number } | null) => dns(withResolvers([resolver({ upstream: u })])).findings.filter((f) => f.key.startsWith('resolver-'));
		expect(findings({ plain_public: 0, dot: 60 })[0]).toMatchObject({ severity: 'info', title: 'Your resolver uses DNS-over-TLS' });
		expect(findings({ plain_public: 30, dot: 60 })[0]).toMatchObject({ severity: 'medium', fix: 'Set its upstream to encrypted only (DNS-over-TLS or DNS-over-HTTPS).' });
		const unknown = findings({ plain_public: 0, dot: 0 })[0];
		expect(unknown.detail).toContain("Unknown: NetTap saw no lookups leaving it; it may use DNS-over-HTTPS, or its upstream isn't visible");
		expect(unknown.fix).not.toMatch(/turn on encryption/i);
		// a public resolver gets no upstream finding
		expect(findings(null)).toEqual([]);
	});

	it('steps up the public-resolver step at 1,000 lookups, and links it to the DNS page', () => {
		expect(dns(POSTURE_DNS).steps[0]).toMatchObject({ priority: 'high', href: '/dns' });
		const fewer = withResolvers(POSTURE_DNS.resolvers.plain, { plain_scope: { private_local: 4200, unknown: 0, public: 999 } });
		expect(dns(fewer).steps[0]).toMatchObject({ priority: 'medium' });
	});

	it('suggests a local resolver only from exact counts: none in private/local scope, no DoT, some public (R2-3)', () => {
		const advice = (d: DnsDetail) => dns(d).steps.some((s) => s.text.includes('run a local resolver'));
		const publicOnly = withResolvers([], { over_tls: 0, plain_scope: { private_local: 0, unknown: 0, public: 500 } });
		expect(advice(publicOnly)).toBe(true);
		// a local resolver ranked 11th is absent from the list but still counted in private_local
		expect(advice({ ...publicOnly, plain_scope: { private_local: 12, unknown: 0, public: 500 } })).toBe(false);
		// nothing observed going to public addresses: no change step at all
		const quiet = withResolvers([resolver({ upstream: { plain_public: 0, dot: 5 } })], { over_tls: 0, plain_scope: { private_local: 900, unknown: 0, public: 0 }, public_devices: { lan: 0, other: 0, rows: [] } });
		expect(dns(quiet).steps).toEqual([]);
	});

	it('links its truncation note to the DNS page', () => {
		const d = { ...POSTURE_DNS, public_devices: { ...POSTURE_DNS.public_devices, other: 75 } };
		expect(dns(d).notes).toEqual([{ text: expect.stringContaining('made 75 more'), href: '/dns' }]);
	});
});

describe('patchReport', () => {
	const services = [
		{ name: 'http', count: 250 },
		{ name: 'telnet', count: 10 },
		{ name: 'ssl', count: 740 },
	];
	const patch = (detail: PatchDetail = POSTURE_PATCH) => patchReport(reportData('patch-currency', { inputs: protocols({ services }), extras: { 'patch-currency': detail } }));

	it('scores from the service labels and shows the unique-connection breakdown beside it (R1-6)', () => {
		const r = patch({ ...POSTURE_PATCH, unique_connections: 255 });
		expect(r.drivers.formula).toBe('100 − (260 old-protocol labels ÷ 1,000 labels × 100) = 74');
		expect(r.kpis[0]).toMatchObject({ value: '74', unit: '%' });
		expect(r.drivers.counts).toContain('Connections with an old-protocol label, each counted once: 255.');
		expect(r.drivers.limits).toContain('A connection with two labels counts twice in the score.');
	});

	it('makes Telnet/FTP high, HTTP medium, and always ends with automatic updates', () => {
		const r = patch();
		expect(r.steps.map((s) => s.priority)).toEqual(['high', 'medium', 'low']);
		expect(r.findings.find((f) => f.key === 'telnet-192.168.1.31')).toMatchObject({ severity: 'high', devices: [{ ip: '192.168.1.31' }] });
		expect(r.findings.find((f) => f.key === 'http-192.168.1.50')!.fix).toContain('replace the device if the maker no longer updates it');
	});

	it('links a protocol’s truncation note to Log Explorer for that label', () => {
		const detail: PatchDetail = { ...POSTURE_PATCH, protocols: [{ ...POSTURE_PATCH.protocols[0], devices: { ...POSTURE_PATCH.protocols[0].devices, other: 40 } }] };
		const [note] = patch(detail).notes;
		expect(note.text).toMatch(/^HTTP: Showing the 10 busiest devices/);
		expect(params(note.href!).get('query')).toBe('network.protocol:"http"');
	});
});
