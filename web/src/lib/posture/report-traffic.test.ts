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
// OLD CODE: … protocols({ encryption: { eligible: detail.eligible, encrypted: detail.encrypted } }) … (NET-308: and one_way)
const enc = (detail: EncryptionDetail, names?: Map<string, string>, oneWay = 9200) =>
	encryptionReport(reportData('encryption', { inputs: protocols({ encryption: { eligible: detail.eligible, encrypted: detail.encrypted, one_way: oneWay } }), extras: { encryption: detail }, names }));
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

	it('read a torrent box by its port, not a small labelled service, at that service\'s higher severity (review M1)', () => {
		const h = deviceHint([{ name: 'unknown', count: 790_000 }, { name: 'http', count: 200 }], [{ port: 6881, count: 700_000 }]);
		expect(h.label).toBe(BITTORRENT.label);
		expect(h.fix).toBe(BITTORRENT.fix);
		expect(h.severity).toBe('medium');
		// a labelled top service still wins
		expect(deviceHint([{ name: 'http', count: 900 }, { name: 'unknown', count: 100 }], [{ port: 6881, count: 50 }]).label).toBe('Unencrypted web traffic (HTTP)');
		// no port hint: the labelled service
		expect(deviceHint([{ name: 'unknown', count: 900 }, { name: 'telnet', count: 3 }], [{ port: 40000, count: 900 }]).label).toBe('Telnet remote login');
	});
});

describe('encryptionReport', () => {
	// OLD CODE: it('puts the score formula, payload breakdown and private/local-scope figure in the drivers (R1-7)', …) (NET-308: one-way connections are left out)
	it('scores connections with data both ways, and says what it left out (NET-308)', () => {
		const r = enc(POSTURE_ENCRYPTION);
		expect(r.drivers.formula).toBe('19,800 encrypted ÷ 21,300 connections with data both ways = 93%');
		expect(r.drivers.bars.map((b) => [b.label, b.value])).toEqual([['Encrypted', 19800], ['Unencrypted', 1500], ['Not scored (one way or none)', 9200]]);
		expect(r.drivers.counts).toContain('Left out: 9,200 connections that carried data one way or none, mostly attempts that never got an answer.');
		expect(r.drivers.counts.join(' ')).toContain('180 of the unencrypted connections went to private or local-scope addresses');
		expect(r.drivers.limits).toEqual(['A connection that sends data one way only (a log message, a one-way stream) is left out, even when it is unencrypted.']);
		expect(r.kpis.map((k) => [k.label, k.value, k.sub])).toEqual([
			['Score', '93', 'Good'],
			['Encrypted', '19,800', 'of 21,300 connections with data both ways'],
			['Left out', '9,200', 'carried data one way or none'],
		]);
		expect(r.findings.find((f) => f.key === 'device-192.168.1.20')!.detail).not.toContain('with data both ways');
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
		expect(enc(detail).notes).toEqual([{ text: 'Showing the 3 busiest devices. Other devices on your network made 420 more of these connections.' }]);
		expect(enc(POSTURE_ENCRYPTION).notes).toEqual([]);
	});

	// OLD CODE START — NET-308: one-way connections no longer lower the score, so there is no such step
	// it('explains, at low priority, when most unencrypted connections carried data one way or none', () => { … });
	// OLD CODE END
	it('has no step blaming one-way connections for the score', () => {
		expect(enc(POSTURE_ENCRYPTION).steps.some((s) => /one way or none/.test(s.text))).toBe(false);
	});

	it('reads nothing measured, unattributed and failed per source (R1-9)', () => {
		expect(enc(POSTURE_ENCRYPTION_EMPTY).sources[0]).toMatchObject({ state: 'not-measured', note: expect.stringContaining('Data pipeline now:') });
		const hidden = { ...POSTURE_ENCRYPTION, devices: { lan: 0, other: 0, rows: [] } };
		expect(enc(hidden).sources[0]).toMatchObject({ state: 'unattributed', note: expect.stringContaining('inline bridge mode') });
		const failed = encryptionReport(reportData('encryption', { failed: ['encryption'] }));
		expect(failed.sources[0]).toMatchObject({ state: 'failed', note: "Couldn't load devices sending unencrypted traffic: the request failed." });
		expect(failed.findings).toEqual([]);
		// OLD CODE: expect(failed.kpis[2]).toMatchObject({ value: '—', sub: "Couldn't load" }); (NET-308: Left out is a score input)
		expect(failed.kpis[2]).toMatchObject({ key: 'left-out', value: '0' });
	});

	it('shows no stand-in zero for a KPI whose score input failed, beside the detail that loaded (review M2)', () => {
		const r = encryptionReport(reportData('encryption', { inputs: { failed: ['protocols'] }, extras: { encryption: POSTURE_ENCRYPTION } }));
		expect(r.kpis[1]).toMatchObject({ key: 'encrypted', value: '—', sub: "Couldn't load" });
		// OLD CODE: expect(r.kpis[2]).toMatchObject({ value: '260' }); (NET-308: Left out comes from the failed input)
		expect(r.kpis[2]).toMatchObject({ key: 'left-out', value: '—', sub: "Couldn't load" });
		expect(r.drivers.bars).toEqual([]);
		expect(r.findings.length).toBeGreaterThan(0);
	});
});

describe('dnsReport', () => {
	// OLD CODE: … protocols({ dns: { plain: detail.plain, over_tls: detail.over_tls } }) … (NET-308: the score input splits off local)
	const local = { plain: 3300, over_tls: 0 };
	const dns = (detail: DnsDetail) =>
		dnsReport(reportData('dns-security', { inputs: protocols({ dns: { plain: detail.plain - local.plain, over_tls: detail.over_tls, local } }), extras: { 'dns-security': detail } }));
	const resolver = (over: Partial<DnsDetail['resolvers']['plain'][number]>) => ({ ...POSTURE_DNS.resolvers.plain[0], ...over });
	const withResolvers = (plain: DnsDetail['resolvers']['plain'], over: Partial<DnsDetail> = {}): DnsDetail => ({ ...POSTURE_DNS, resolvers: { ...POSTURE_DNS.resolvers, plain }, ...over });

	// OLD CODE: it('splits plain lookups by address scope with the exact filters (R2-3, R2-6)', …) (NET-308: the bars are the score input's)
	it('draws the four DNS bars from the score input, one plain bar for public and unknown (NET-308 R2-2)', () => {
		const r = dns(POSTURE_DNS);
		expect(r.drivers.bars.map((b) => [b.label, b.value])).toEqual([
			['DNS-over-TLS to non-local or unknown addresses', 60],
			['Plain to non-local or unknown addresses', 2100],
			['Plain to your own resolvers, not scored', 3300],
			['DNS-over-TLS to your own resolvers, not scored', 0],
		]);
		expect(r.drivers.bars.some((b) => /unknown$/i.test(b.label) && !/non-local/.test(b.label))).toBe(false);
		expect(r.drivers.formula).toBe('60 DNS-over-TLS ÷ (2,100 plain + 60 DNS-over-TLS), both to non-local or unknown addresses = 3%');
		expect(r.drivers.counts).toContain(
			'Left out: 3,300 plain lookups and 0 DNS-over-TLS connections to your own resolvers (private or local-scope addresses); each one is judged by what it sends out.',
		);
		expect(r.drivers.limits.join(' ')).not.toMatch(/count as plain/);
		expect(r.drivers.limits).toContain("A resolver whose lookups out don't pass NetTap (a router's internet side, say) can't be judged; its lookups are in neither figure.");
		expect(r.drivers.limits).toContain('A private address isn’t proof the resolver is yours: a VPN’s resolver has one too.');
		expect(r.drivers.resolvers?.map((x) => [x.ip, x.kind, x.scope])).toContainEqual(['198.51.100.153', 'DNS-over-TLS', 'Public']);
		expect(r.kpis[2]).toMatchObject({ value: '1,200' });
		// DoT is counted in connections, plain in lookups (review L8)
		expect(r.kpis[1]).toMatchObject({ value: '60', sub: 'connections, beside 2,100 plain lookups' });
	});

	it('judges a forwarding private-address resolver as a resolver, not a device, and leaves its lookups out of the device step (review M3)', () => {
		const piHole = resolver({ ip: '192.168.1.2', upstream: { plain_public: 300, dot: 0 } });
		const d = withResolvers([piHole], {
			plain_scope: { private_local: 4200, unknown: 0, public: 1200 },
			public_devices: { lan: 1200, other: 0, rows: [{ ip: '192.168.1.2', count: 300, resolvers: [{ ip: '1.1.1.1', count: 300, org: null }] }, { ip: '192.168.1.22', count: 900, resolvers: [{ ip: '8.8.8.8', count: 900, org: null }] }] },
		});
		const r = dns(d);
		expect(r.findings.some((f) => f.key === 'public-192.168.1.2')).toBe(false);
		expect(r.findings.find((f) => f.key === 'resolver-192.168.1.2')).toMatchObject({ severity: 'medium', title: 'Private-address resolver also sends plain lookups out' });
		const step = r.steps.find((s) => s.href === '/dns')!;
		expect(step).toMatchObject({ priority: 'medium' });
		expect(step.text).toMatch(/^900 plain lookups went straight to public resolvers/);
	});

	it('judges a local resolver from its own upstream counts, and never asks for encryption it can’t see (R1-2)', () => {
		const findings = (u: { plain_public: number; dot: number } | null) => dns(withResolvers([resolver({ upstream: u })])).findings.filter((f) => f.key.startsWith('resolver-'));
		expect(findings({ plain_public: 0, dot: 60 })[0]).toMatchObject({ severity: 'info', title: 'Private-address resolver uses DNS-over-TLS' });
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
	// NET-308: 255 connections carry an old-protocol label, out of 1,000 (some carry ssl too)
	const patch = (detail: PatchDetail = POSTURE_PATCH) =>
		patchReport(reportData('patch-currency', { inputs: protocols({ services, patch: { legacy: 255, connections: 1000 } }), extras: { 'patch-currency': detail } }));

	// OLD CODE: it('scores from the service labels and shows the unique-connection breakdown beside it (R1-6)', …) (NET-308: it scores connections)
	it('scores each connection once, from the score input', () => {
		const r = patch({ ...POSTURE_PATCH, unique_connections: 255 });
		expect(r.drivers.formula).toBe('100 − (255 old-protocol connections ÷ 1,000 connections × 100) = 75');
		expect(r.kpis[0]).toMatchObject({ value: '75', unit: '%' });
		expect(r.kpis[1]).toMatchObject({ key: 'legacy', value: '255', sub: 'of 1,000 connections' });
		expect(r.drivers.counts).toEqual(['Old protocols: plain HTTP, FTP, Telnet, POP3 and IMAP.']);
		expect(r.drivers.limits).not.toContain('A connection with two labels counts twice in the score.');
		// the per-label bars stay (a two-label connection shows under each label)
		expect(r.drivers.bars.map((b) => [b.key, b.value])).toEqual([['http', 250], ['telnet', 10]]);
	});

	it('makes Telnet/FTP high, HTTP medium, and always ends with automatic updates', () => {
		const r = patch();
		expect(r.steps.map((s) => s.priority)).toEqual(['high', 'medium', 'low']);
		expect(r.findings.find((f) => f.key === 'telnet-192.168.1.31')).toMatchObject({ severity: 'high', devices: [{ ip: '192.168.1.31' }] });
		expect(r.findings.find((f) => f.key === 'http-192.168.1.50')!.fix).toContain('replace the device if the maker no longer updates it');
	});

	it('keeps the device findings and shows no stand-in zeros when the protocols request failed (review M2)', () => {
		const r = patchReport(reportData('patch-currency', { inputs: { failed: ['protocols'] }, extras: { 'patch-currency': POSTURE_PATCH } }));
		expect(r.sources[0].state).toBe('measured');
		expect(r.findings.length).toBe(2);
		expect(r.kpis[1]).toMatchObject({ key: 'legacy', value: '—', sub: "Couldn't load" });
		expect(r.kpis[2]).toMatchObject({ key: 'telnet-ftp', value: '—' });
	});

	it('links a protocol’s truncation note to Log Explorer for that label', () => {
		const detail: PatchDetail = { ...POSTURE_PATCH, protocols: [{ ...POSTURE_PATCH.protocols[0], devices: { ...POSTURE_PATCH.protocols[0].devices, other: 40 } }] };
		const [note] = patch(detail).notes;
		expect(note.text).toMatch(/^HTTP: Showing the 1 busiest devices/);
		expect(params(note.href!).get('query')).toBe('network.protocol:"http"');
	});
});
