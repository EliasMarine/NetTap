/** NET-355: the evidence helpers behind the alert drawer's Evidence block. */
import { describe, it, expect } from 'vitest';
import type { Alert } from '$api/alerts';
import type { PacketSearchResult } from '$api/packets';
import {
	alertTimeMs,
	alertEndpoints,
	canonicalIp,
	packetPreview,
	beforeWindow,
	recordedFields,
	trafficOf,
	zeekQuery,
	emptyResultText,
	pcapName,
} from './alert-evidence';

const T = Date.UTC(2026, 10, 23, 1, 40, 44);
const ID = '1:BHcgw+xc46L4m7IOXm9O5K6Vg8o=';

function alert(over: Record<string, unknown> = {}): Alert {
	return {
		_id: 'a1',
		_index: 'arkime_sessions3-261123',
		timestamp: new Date(T).toISOString(),
		acknowledged: false,
		alert: { signature: 'ET EXPLOIT x', signature_id: 2033967, severity: 1 },
		src_ip: '192.168.1.208',
		src_port: 49232,
		dest_ip: '149.154.166.110',
		dest_port: 443,
		proto: 'TCP',
		...over,
	} as Alert;
}

const ends = (a: Alert) => {
	const e = alertEndpoints(a);
	if ('problem' in e) throw new Error(e.problem);
	return e;
};

describe('alertTimeMs', () => {
	it('reads ISO, numeric ms and digit-string ms', () => {
		expect(alertTimeMs(alert())).toBe(T);
		expect(alertTimeMs(alert({ timestamp: T }))).toBe(T);
		expect(alertTimeMs(alert({ timestamp: String(T) }))).toBe(T);
	});
	it('falls back to @timestamp, else null', () => {
		expect(alertTimeMs(alert({ timestamp: '', '@timestamp': new Date(T).toISOString() }))).toBe(T);
		expect(alertTimeMs(alert({ timestamp: 'not a date' }))).toBeNull();
	});
});

describe('alertEndpoints', () => {
	it('uses the flat fields first', () => {
		expect(ends(alert())).toEqual({ proto: 'tcp', srcIp: '192.168.1.208', srcPort: 49232, dstIp: '149.154.166.110', dstPort: 443 });
	});
	it('falls back to ECS, with ports from strings and one-item arrays', () => {
		const a = alert({
			src_ip: undefined, src_port: undefined, dest_ip: undefined, dest_port: undefined, proto: undefined,
			source: { ip: ['10.0.0.2'], port: '5353' },
			destination: { ip: '10.0.0.9', port: [53] },
			network: { transport: 'udp' },
		});
		expect(ends(a)).toEqual({ proto: 'udp', srcIp: '10.0.0.2', srcPort: 5353, dstIp: '10.0.0.9', dstPort: 53 });
	});
	it('refuses a missing or non-IP address and mixed families', () => {
		expect(alertEndpoints(alert({ dest_ip: undefined }))).toHaveProperty('problem');
		expect(alertEndpoints(alert({ dest_ip: 'example.com' }))).toHaveProperty('problem');
		expect(alertEndpoints(alert({ dest_ip: '2001:db8::1' }))).toHaveProperty('problem');
	});
	it('makes IPv6 spellings of one address equal', () => {
		expect(canonicalIp('2001:0db8:0:0:0:0:0:1')).toBe(canonicalIp('2001:db8::1'));
		expect(canonicalIp('2001:db8::1/64')).toBeNull();
		expect(canonicalIp('192.168.001.010')).toBe('192.168.1.10');
		expect(canonicalIp('256.1.1.1')).toBeNull();
	});
});

describe('packetPreview', () => {
	it('builds the exact tuple filter, a minute either side', () => {
		const p = packetPreview(alert());
		if ('problem' in p) throw new Error(p.problem);
		expect(p.exact).toBe(true);
		expect(p.filter).toContain('149.154.166.110');
		expect(p.filter).toContain('443');
		expect(p.from).toBe(String((T - 60_000) / 1000));
		expect(p.to).toBe(String((T + 60_000) / 1000));
		expect(p.label).toMatch(/addresses and ports/);
	});
	it('handles IPv6 and UDP', () => {
		const p = packetPreview(alert({ src_ip: '2001:db8::2', dest_ip: '2001:0db8::0:1', proto: 'udp', dest_port: 53 }));
		if ('problem' in p) throw new Error(p.problem);
		expect(p.exact).toBe(true);
		expect(p.filter).toContain('ipv6');
		expect(p.filter).toContain('2001:db8::1');
	});
	it('falls back to the address pair for ICMP', () => {
		const p = packetPreview(alert({ proto: 'ICMP', src_port: undefined, dest_port: undefined }));
		if ('problem' in p) throw new Error(p.problem);
		expect(p.exact).toBe(false);
		expect(p.label).toMatch(/between the two addresses/);
	});
	it('allows one address with two ports, refuses one address without ports', () => {
		expect(packetPreview(alert({ dest_ip: '192.168.1.208', dest_port: 8080 }))).not.toHaveProperty('problem');
		expect(packetPreview(alert({ dest_ip: '192.168.1.208', proto: 'icmp', src_port: undefined, dest_port: undefined }))).toHaveProperty('problem');
	});
	it('refuses an alert with no time', () => {
		expect(packetPreview(alert({ timestamp: '' }))).toHaveProperty('problem');
	});
	it('has an 11-minute window before the alert', () => {
		expect(beforeWindow(alert())).toEqual({ from: String((T - 660_000) / 1000), to: String(T / 1000) });
	});
});

describe('recordedFields', () => {
	it('shows the listed fields that are present, as text', () => {
		const a = alert({
			suricata: {
				tls: { sni: 'example.org', ja4: 't13d1516h2_8daaf6152771_02713d6af862' },
				http: { http_method: 'GET', url: '/a?b=1', status: 200, http_user_agent: 'curl/8' },
				dns: { queries: [{ rrname: 'q.example' }], answer: { rrname: 'a.example' } },
				unlisted: { secret: 'x' },
			},
		});
		const rows = recordedFields(a);
		expect(rows.map((r) => r.label)).toEqual(['DNS names', 'Server name', 'TLS fingerprint (JA4)', 'Request', 'Response status', 'User agent']);
		expect(rows.find((r) => r.label === 'DNS names')?.value).toBe('q.example, a.example');
		expect(rows.find((r) => r.label === 'Request')?.value).toBe('GET /a?b=1');
		expect(rows.find((r) => r.label === 'Response status')?.value).toBe('200');
		expect(rows.some((r) => r.value === 'x')).toBe(false);
	});
	it('is empty when nothing is recorded, and truncates a long payload', () => {
		expect(recordedFields(alert())).toEqual([]);
		const long = recordedFields(alert({ payload_printable: 'p'.repeat(2500) }))[0];
		expect(long.label).toBe('Payload');
		expect(long.value).toHaveLength(2001);
		expect(long.value.endsWith('…')).toBe(true);
	});
});

describe('trafficOf', () => {
	it('names both ends and who owns them, as the alert records', () => {
		const t = trafficOf(alert({ network: { application: 'tls' }, destination: { as: { full: 'AS62041 Telegram Messenger LLP' }, geo: { country_name: 'United Kingdom' } } }));
		expect(t).toEqual({
			app: 'TLS',
			from: { ip: '192.168.1.208', port: 49232, owner: '' },
			to: { ip: '149.154.166.110', port: 443, owner: 'AS62041 Telegram Messenger LLP, United Kingdom' },
		});
	});
	it('keeps the alert’s direction for a reply-side alert (the server in source)', () => {
		const t = trafficOf(alert({ src_ip: '149.154.166.110', src_port: 443, dest_ip: '192.168.1.208', dest_port: 49232 }));
		expect(t?.from).toMatchObject({ ip: '149.154.166.110', port: 443 });
		expect(JSON.stringify(t)).not.toMatch(/opened|server/i);
	});
	it('is null without two addresses', () => {
		expect(trafficOf(alert({ src_ip: undefined }))).toBeNull();
	});
});

describe('zeekQuery', () => {
	it('looks up Zeek records by community ID, a day back and 15 minutes on', () => {
		const q = zeekQuery(alert({ network: { community_id: ID } }));
		expect(q?.query).toBe(`network.community_id:"${ID}" AND event.provider:zeek`);
		expect(q?.from).toBe(new Date(T - 86_400_000).toISOString());
		expect(q?.to).toBe(new Date(T + 900_000).toISOString());
		expect(q?.href).toContain('/logs?');
		expect(decodeURIComponent(q?.href ?? '')).toContain(`network.community_id:"${ID}"`);
	});
	it('refuses anything that isn’t a v1 community ID', () => {
		for (const bad of ['', '1:short=', `${ID} OR *`, '1:BHcgw+xc46L4m7IOXm9O5K6Vg8o"=', '2:BHcgw+xc46L4m7IOXm9O5K6Vg8o=']) {
			expect(zeekQuery(alert({ network: { community_id: bad } }))).toBeNull();
		}
	});
});

describe('emptyResultText', () => {
	const r = (over: Partial<PacketSearchResult>) => ({ rows: [], termination: 'eof', complete: true, provisional: false, files: [], skipped_files: [], ...over }) as unknown as PacketSearchResult;
	const file = { id: 'f1' } as unknown as PacketSearchResult['files'][number];
	it('says skipped files first, then a deadline, never "none"', () => {
		expect(emptyResultText(r({ complete: false, skipped_files: [file] as never }))).toMatch(/couldn't be read/);
		expect(emptyResultText(r({ complete: false, termination: 'deadline', skipped_files: [file] as never }))).toMatch(/couldn't be read/);
		expect(emptyResultText(r({ complete: false, termination: 'deadline' }))).toMatch(/stopped before it finished/);
	});
	it('says no capture when nothing was read, no match only after reading a file', () => {
		expect(emptyResultText(r({}))).toBe('No capture was available for this window.');
		expect(emptyResultText(r({ files: [file] }))).toBe('No matching packets in the captures searched.');
		expect(emptyResultText(r({ files: [file], provisional: true }))).toBe('No matching packets in the captures searched so far.');
		expect(emptyResultText(r({ complete: false }))).toMatch(/didn't finish/);
	});
});

it('names the download after the rule and the alert time', () => {
	expect(pcapName(alert())).toBe('alert-2033967-20261123-014044.pcap');
});
