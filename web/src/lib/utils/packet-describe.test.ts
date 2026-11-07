import { describe, it, expect } from 'vitest';
import type { PacketRow } from '$lib/api/packets';
import fixture from './packet-rows.fixture.json';
import { describePacket } from './packet-describe';

/** The daemon's own parse of a real TShark 4.0.17 search (daemon/tests/fixtures/packets/search_all.out). */
// JSON infers each row its own field keys; the daemon contract is PacketRow
const ROWS = fixture.rows as unknown as PacketRow[];
const NONE = new Map<string, string>();
const NAMES = new Map([['192.0.2.10', 'Living-room TV']]);

/** A fixture row with some fields replaced (undefined removes one), in the same parsed shape. */
function variant(base: PacketRow, over: Partial<PacketRow> & { set?: Record<string, string[] | undefined> }): PacketRow {
	const fields = { ...base.fields, ...over.set };
	for (const [k, v] of Object.entries(fields)) if (v === undefined) delete fields[k];
	const { set: _set, ...rest } = over;
	return { ...base, ...rest, fields: fields as PacketRow['fields'] };
}

const [SYN, SYNACK, ACK, DNS, SSL, HTTP] = ROWS;

describe('describePacket on a real TShark 4.0.17 search', () => {
	it('describes each row it can, and leaves TLS continuation data to Info', () => {
		expect(ROWS.map((r) => describePacket(r, NONE))).toEqual([
			'192.0.2.10 asked 198.51.100.20 to connect on port 443',
			'198.51.100.20 agreed to connect',
			'192.0.2.10 acknowledged what 198.51.100.20 sent',
			'198.51.100.53 answered example.com with 2 addresses: 192.0.2.80 and 192.0.2.81',
			null,
			'192.0.2.10 sent an unencrypted GET request for example.com/a\\tb',
		]);
	});

	it('uses device names where it has them', () => {
		expect(describePacket(SYN, NAMES)).toBe('Living-room TV asked 198.51.100.20 to connect on port 443');
		expect(describePacket(SYNACK, NAMES)).toBe('198.51.100.20 agreed to connect');
		expect(describePacket(ACK, NAMES)).toBe('Living-room TV acknowledged what 198.51.100.20 sent');
	});
});

describe('describePacket: only unambiguous cases', () => {
	it('gives Info alone for a packet with several IP layers', () => {
		const tunnelled = variant(SYN, { set: { 'ip.src': ['192.0.2.10', '10.0.0.1'], 'ip.dst': ['198.51.100.20', '10.0.0.2'] } });
		expect(describePacket(tunnelled, NONE)).toBeNull();
		const mixed = variant(SYN, { set: { 'ipv6.src': ['2001:db8::1'], 'ipv6.dst': ['2001:db8::2'] } });
		expect(describePacket(mixed, NONE)).toBeNull();
	});

	it('gives Info alone for several TLS handshake messages in one packet', () => {
		const flight = variant(SSL, {
			protocol: 'TLSv1.2',
			info: 'Server Hello, Certificate, Server Hello Done',
			set: { 'tls.handshake.type': ['2', '11', '14'] },
		});
		expect(describePacket(flight, NONE)).toBeNull();
		const twoRecords = variant(SSL, { protocol: 'TLSv1.3', info: 'Application Data, Application Data' });
		expect(describePacket(twoRecords, NONE)).toBeNull();
	});

	it('describes one Client Hello (by its SNI), one Server Hello, and encrypted data', () => {
		const hello = variant(SSL, {
			protocol: 'TLSv1.3',
			info: 'Client Hello (SNI=cdn.example-media.net)',
			set: { 'tls.handshake.type': ['1'], 'tls.handshake.extensions_server_name': ['cdn.example-media.net'] },
		});
		expect(describePacket(hello, NAMES)).toBe('Living-room TV asked cdn.example-media.net to start encryption');
		const noSni = variant(hello, { set: { 'tls.handshake.extensions_server_name': undefined } });
		expect(describePacket(noSni, NONE)).toBe('192.0.2.10 asked 198.51.100.20 to start encryption');
		const serverHello = variant(SSL, { protocol: 'TLSv1.3', info: 'Server Hello', set: { 'tls.handshake.type': ['2'] } });
		expect(describePacket(serverHello, NONE)).toBe('192.0.2.10 agreed to start encryption');
		expect(describePacket(variant(SSL, { protocol: 'TLSv1.3', info: 'Application Data' }), NONE)).toBe('192.0.2.10 sent encrypted data');
		const alert = variant(SSL, { protocol: 'TLSv1.2', info: 'Alert (Level: Fatal, Description: Unknown CA)', set: { 'tls.alert_message.desc': ['48'] } });
		expect(describePacket(alert, NONE)).toBeNull();
	});

	it('gives Info alone for a protocol it does not know', () => {
		for (const protocol of ['MDNS', 'SSDP', 'QUIC', 'UDP', 'IGMPv3', 'Something new']) {
			expect(describePacket(variant(HTTP, { protocol }), NONE)).toBeNull();
		}
	});

	it('gives Info alone when TShark flagged the packet above chat (a retransmission)', () => {
		const resent = variant(ACK, {
			set: {
				'tcp.len': ['1448'],
				'_ws.expert.message': ['This frame is a (suspected) retransmission'],
				'_ws.expert.severity': ['6291456'],
				'_ws.expert.group': ['33554432'],
			},
		});
		expect(describePacket(resent, NONE)).toBeNull();
		expect(describePacket(variant(ACK, { set: { '_ws.expert.severity': ['not a number'] } }), NONE)).toBeNull();
	});
});

describe('describePacket: DNS', () => {
	it('counts every answer of a reply with several dns.a, listing three and the rest as a count', () => {
		const five = variant(DNS, {
			set: { 'dns.a': ['192.0.2.80', '192.0.2.81', '192.0.2.82', '192.0.2.83', '192.0.2.84'], 'dns.count.answers': ['5'] },
		});
		expect(describePacket(five, NONE)).toBe('198.51.100.53 answered example.com with 5 addresses: 192.0.2.80, 192.0.2.81, 192.0.2.82 and 2 more');
		const one = variant(DNS, { set: { 'dns.a': ['192.0.2.80'], 'dns.count.answers': ['1'] } });
		expect(describePacket(one, NONE)).toBe('198.51.100.53 answered example.com with 1 address: 192.0.2.80');
	});

	it('counts other names and IPv6 addresses as answers too', () => {
		const viaCname = variant(DNS, {
			set: { 'dns.cname': ['example.cdn.net'], 'dns.a': ['192.0.2.80'], 'dns.aaaa': ['2001:db8::80'], 'dns.count.answers': ['3'] },
		});
		expect(describePacket(viaCname, NONE)).toBe(
			'198.51.100.53 answered example.com with 2 addresses: 192.0.2.80 and 2001:db8::80, by way of 1 other name',
		);
	});

	it('says only the count when some answers are of a kind it has no field for', () => {
		const https = variant(DNS, { set: { 'dns.a': undefined, 'dns.qry.type': ['65'], 'dns.count.answers': ['2'] } });
		expect(describePacket(https, NONE)).toBe('198.51.100.53 answered example.com with 2 answers');
	});

	it('describes a question, an empty answer and the common errors', () => {
		const question = variant(DNS, {
			set: { 'ip.src': ['192.0.2.10'], 'ip.dst': ['198.51.100.53'], 'dns.flags.response': ['0'], 'dns.a': undefined, 'dns.count.answers': ['0'] },
		});
		expect(describePacket(question, NAMES)).toBe('Living-room TV asked 198.51.100.53 to look up example.com');
		const empty = variant(DNS, { set: { 'dns.a': undefined, 'dns.count.answers': ['0'] } });
		expect(describePacket(empty, NONE)).toBe('198.51.100.53 answered that example.com has no records of that kind');
		const nx = variant(DNS, { set: { 'dns.flags.rcode': ['3'], 'dns.a': undefined, 'dns.count.answers': ['0'] } });
		expect(describePacket(nx, NONE)).toBe('198.51.100.53 said there is no such name as example.com');
		expect(describePacket(variant(nx, { set: { 'dns.flags.rcode': ['9'] } }), NONE)).toBeNull();
	});

	it('gives Info alone for several questions, or no answer count', () => {
		expect(describePacket(variant(DNS, { set: { 'dns.qry.name': ['a.example', 'b.example'] } }), NONE)).toBeNull();
		expect(describePacket(variant(DNS, { set: { 'dns.count.answers': undefined } }), NONE)).toBeNull();
	});
});

describe('describePacket: TCP flags', () => {
	const flags = (hex: string, len = '0') => variant(ACK, { set: { 'tcp.flags': [hex], 'tcp.len': [len] } });

	it('describes a reset, a close and plain data', () => {
		expect(describePacket(flags('0x0014'), NONE)).toBe('192.0.2.10 ended the connection abruptly');
		expect(describePacket(flags('0x0011'), NONE)).toBe('192.0.2.10 closed its side of the connection');
		expect(describePacket(flags('0x0018', '1448'), NONE)).toBe('192.0.2.10 sent 1,448 bytes of data to 198.51.100.20');
	});

	it('gives Info alone for mixed cases: data with a FIN or SYN, urgent data, a missing length', () => {
		expect(describePacket(flags('0x0019', '10'), NONE)).toBeNull();
		expect(describePacket(flags('0x0002', '10'), NONE)).toBeNull();
		expect(describePacket(flags('0x0030'), NONE)).toBeNull();
		expect(describePacket(variant(ACK, { set: { 'tcp.len': undefined } }), NONE)).toBeNull();
	});
});

describe('describePacket: pings, ARP, DHCP and HTTP replies', () => {
	const icmp = (type: string) =>
		variant(SYN, { protocol: 'ICMP', set: { 'tcp.flags': undefined, 'tcp.len': undefined, '_ws.expert.severity': undefined, 'icmp.type': [type] } });

	it('describes a ping and its answer, and nothing else ICMP', () => {
		expect(describePacket(icmp('8'), NAMES)).toBe('Living-room TV pinged 198.51.100.20');
		expect(describePacket(icmp('0'), NONE)).toBe('192.0.2.10 answered a ping from 198.51.100.20');
		expect(describePacket(icmp('11'), NONE)).toBeNull();
	});

	it('describes an ARP question and answer, not a probe', () => {
		const arp = (op: string, target: string): PacketRow => ({
			...SYN,
			protocol: 'ARP',
			fields: { 'eth.src': ['02:00:00:00:00:01'], 'arp.opcode': [op], 'arp.src.proto_ipv4': ['192.0.2.10'], 'arp.dst.proto_ipv4': [target], 'arp.src.hw_mac': ['02:00:00:00:00:01'] },
		});
		expect(describePacket(arp('1', '192.0.2.1'), NAMES)).toBe('Living-room TV asked which device has 192.0.2.1');
		expect(describePacket(arp('2', '192.0.2.1'), NONE)).toBe('02:00:00:00:00:01 answered that it has 192.0.2.10');
		expect(describePacket(arp('1', '192.0.2.10'), NONE)).toBeNull();
	});

	it('describes the DHCP steps it can name exactly', () => {
		const dhcp = (type: string, set: Record<string, string[]> = {}) =>
			variant(SYN, {
				protocol: 'DHCP',
				set: { 'ip.src': ['192.0.2.1'], 'ip.dst': ['255.255.255.255'], 'dhcp.option.dhcp': [type], 'dhcp.hw.mac_addr': ['02:00:00:00:00:09'], '_ws.expert.severity': undefined, ...set },
			});
		expect(describePacket(dhcp('1', { 'dhcp.option.hostname': ['kitchen-ipad'] }), NONE)).toBe('kitchen-ipad asked for an address');
		expect(describePacket(dhcp('2', { 'dhcp.ip.your': ['192.0.2.70'] }), NONE)).toBe('192.0.2.1 offered 192.0.2.70 to 02:00:00:00:00:09');
		expect(describePacket(dhcp('3', { 'dhcp.option.requested_ip_address': ['192.0.2.70'] }), NONE)).toBe('02:00:00:00:00:09 asked to use 192.0.2.70');
		expect(describePacket(dhcp('5', { 'dhcp.ip.your': ['192.0.2.70'] }), NONE)).toBe('192.0.2.1 gave 192.0.2.70 to 02:00:00:00:00:09');
		expect(describePacket(dhcp('6'), NONE)).toBe("192.0.2.1 refused 02:00:00:00:00:09's request");
		expect(describePacket(dhcp('8'), NONE)).toBeNull();
		expect(describePacket(dhcp('2'), NONE)).toBeNull();
	});

	it('describes an HTTP reply, but not a packet that is both or neither', () => {
		const reply = variant(HTTP, {
			set: { 'http.request.method': undefined, 'http.request.uri': undefined, 'http.response.code': ['404'], 'http.response.phrase': ['Not Found'] },
		});
		expect(describePacket(reply, NONE)).toBe('192.0.2.10 answered “404 Not Found” without encryption');
		expect(describePacket(variant(HTTP, { set: { 'http.response.code': ['200'] } }), NONE)).toBeNull();
		expect(describePacket(variant(HTTP, { set: { 'http.request.method': undefined } }), NONE)).toBeNull();
	});
});
