import { describe, it, expect } from 'vitest';
import type { PacketRow } from '$lib/api/packets';
import fixture from './packet-rows.fixture.json';
import { packetStats, serverNames, sourceOf } from './packet-stats';

/** The daemon's own parse of a real TShark 4.0.17 search (daemon/tests/fixtures/packets/search_all.out). */
// JSON infers each row its own field keys; the daemon contract is PacketRow
const ROWS = fixture.rows as unknown as PacketRow[];

function row(n: number, t: string, fields: PacketRow['fields'], len = 60, protocol = 'TCP'): PacketRow {
	return { n, t, len, cap_len: len, md5: '0'.repeat(32), protocol, info: '', fields };
}

/** One TCP packet on `stream` from src to dst; `sni` makes it a Client Hello. */
function tcp(n: number, stream: string, src: string, dst: string, sni?: string): PacketRow {
	const hello: PacketRow['fields'] = sni ? { 'tls.handshake.type': ['1'], 'tls.handshake.extensions_server_name': [sni] } : {};
	return row(n, `1794026197.${String(n).padStart(3, '0')}`, { 'ip.src': [src], 'ip.dst': [dst], 'tcp.stream': [stream], ...hello });
}

describe('packetStats on a real TShark 4.0.17 search', () => {
	const stats = packetStats(ROWS, null);

	it('counts the packets, the exact time from first to last, and frame.len (not the captured length)', () => {
		expect(stats.packets).toBe(6);
		expect(stats.lastedSeconds).toBe('1');
		// Packet 5 was captured short (96 of 1,514 bytes): the sum is of what was on the wire
		expect(stats.bytes).toBe(54 + 54 + 54 + 103 + 1514 + 94);
	});

	it('groups what TShark noticed, with its severity and group named', () => {
		expect(stats.noticed).toEqual([
			{ severity: 'chat', group: 'Sequence', message: 'Connection establish acknowledge (SYN+ACK): server port 443', count: 1, frames: [2] },
			{ severity: 'chat', group: 'Sequence', message: 'Connection establish request (SYN): server port 443', count: 1, frames: [1] },
			{ severity: 'chat', group: 'Sequence', message: 'GET /a\\tb HTTP/1.1\\r\\n', count: 1, frames: [6] },
		]);
	});

	it('ranks senders by bytes, by IP source', () => {
		expect(stats.senders).toEqual([
			{ address: '192.0.2.10', packets: 4, bytes: 54 + 54 + 1514 + 94 },
			{ address: '198.51.100.53', packets: 1, bytes: 103 },
			{ address: '198.51.100.20', packets: 1, bytes: 54 },
		]);
	});

	it('has no direction without a device, and splits out and in with one', () => {
		expect(stats.direction).toBeNull();
		// The bytes it sent are the frame lengths of exactly the packets counted "out"
		const sent = (ip: string) => ROWS.filter((r) => r.fields['ip.src']?.[0] === ip).reduce((n, r) => n + r.len, 0);
		expect(packetStats(ROWS, '192.0.2.10').direction).toEqual({ out: 4, in: 2, other: 0, outBytes: sent('192.0.2.10') });
		expect(packetStats(ROWS, '198.51.100.20').direction).toEqual({ out: 1, in: 3, other: 2, outBytes: sent('198.51.100.20') });
	});

	it('spreads the packets over 60 equal buckets from the first to the last', () => {
		expect(stats.timeline).toHaveLength(60);
		expect(stats.timeline[0].t).toBe('1700000000.000001');
		// 1 s / 60, rounded up to the nanosecond
		expect(stats.timeline[1].t).toBe('1700000000.016667667');
		const filled = stats.timeline.flatMap((b, i) => (b.packets ? [[i, b.packets, b.bytes]] : []));
		expect(filled).toEqual([
			[0, 2, 108],
			[14, 1, 54],
			[29, 1, 103],
			[44, 1, 1514],
			[59, 1, 94],
		]);
	});
});

describe('packetStats edge cases', () => {
	it('is all zero for no packets, and has no "lasted" for one', () => {
		expect(packetStats([], '192.0.2.10')).toEqual({
			packets: 0,
			lastedSeconds: null,
			bytes: 0,
			noticed: [],
			direction: { out: 0, in: 0, other: 0, outBytes: 0 },
			senders: [],
			timeline: [],
		});
		const one = packetStats([ROWS[0]], null);
		expect(one.lastedSeconds).toBeNull();
		// OLD CODE: expect(one.timeline).toEqual([{ t: '1700000000.000001', packets: 1, bytes: 54 }]); (NET-249: and its rows)
		expect(one.timeline).toEqual([{ t: '1700000000.000001', packets: 1, bytes: 54, rows: [0] }]);
	});

	// NET-249: a pick on the chart shows exactly a bucket's packets, so each bucket names its rows
	it("names each bucket's rows, sub-millisecond apart, with the last packet in the last bucket", () => {
		// 600 ns from first to last: buckets of 10 ns; the last packet sits exactly on the 60th bucket's end
		const rows = [
			row(1, '1794026197.000000000', {}),
			row(2, '1794026197.000000009', {}),
			row(3, '1794026197.000000010', {}),
			row(4, '1794026197.000000599', {}),
			row(5, '1794026197.000000600', {}),
		];
		const { timeline } = packetStats(rows, null);
		expect(timeline).toHaveLength(60);
		expect(timeline[0].rows).toEqual([0, 1]);
		expect(timeline[1].rows).toEqual([2]);
		expect(timeline[59].rows).toEqual([3, 4]);
		expect(timeline.reduce((n, b) => n + b.rows.length, 0)).toBe(rows.length);
		for (const b of timeline) expect(b.rows.length).toBe(b.packets);
	});

	it('keeps "lasted" exact past what a float holds, and never negative', () => {
		const rows = [row(1, '1794026231.000000001', { 'ip.src': ['192.0.2.10'] }), row(2, '1794026197.218929', { 'ip.src': ['192.0.2.10'] })];
		expect(packetStats(rows, null).lastedSeconds).toBe('33.781071001');
	});

	it('counts packets with no IP layer as "other", and names their sender by Ethernet address', () => {
		const arp = row(1, '1794026197', { 'eth.src': ['02:00:00:00:00:01'], 'arp.opcode': ['1'] }, 42, 'ARP');
		const bare = row(2, '1794026198', {}, 30, 'Something');
		const stats = packetStats([arp, bare], '192.0.2.10');
		expect(stats.direction).toEqual({ out: 0, in: 0, other: 2, outBytes: 0 });
		expect(stats.senders).toEqual([
			{ address: '02:00:00:00:00:01', packets: 1, bytes: 42 },
			{ address: '', packets: 1, bytes: 30 },
		]);
	});

	it('takes the first IP source (the outer layer of a tunnel), then the hardware address, else nothing', () => {
		expect(sourceOf(row(1, '1', { 'ip.src': ['10.0.0.1', '192.168.1.5'] }))).toBe('10.0.0.1');
		expect(sourceOf(row(1, '1', { 'ipv6.src': ['fe80::1'] }))).toBe('fe80::1');
		expect(sourceOf(row(1, '1', { 'eth.src': ['aa:bb:cc:dd:ee:ff'] }))).toBe('aa:bb:cc:dd:ee:ff');
		expect(sourceOf(row(1, '1', {}))).toBe('');
	});

	it('matches an IPv6 device whatever its letter case', () => {
		const rows = [row(1, '1', { 'ipv6.src': ['2001:db8::a'], 'ipv6.dst': ['2001:db8::1'] })];
		// The Data KPI's "sent by" bytes match by the same rule as the packet counts
		expect(packetStats(rows, ' 2001:DB8::A ').direction).toEqual({ out: 1, in: 0, other: 0, outBytes: rows[0].len });
	});

	it('puts the most severe first and counts packets, not mentions', () => {
		const resent = (n: number) => ({
			'_ws.expert.message': ['This frame is a (suspected) retransmission', 'This frame is a (suspected) retransmission'],
			'_ws.expert.severity': ['6291456', '6291456'],
			'_ws.expert.group': ['33554432', '33554432'],
			'ip.src': [`192.0.2.${n}`],
		});
		const rows = [
			row(15, '1', resent(1)),
			row(22, '2', resent(2)),
			row(30, '3', { '_ws.expert.message': ['Malformed Packet (Exception occurred)'], '_ws.expert.severity': ['8388608'], '_ws.expert.group': ['117440512'] }),
			row(31, '4', { '_ws.expert.message': ['Odd one'], '_ws.expert.severity': ['4194304'] }),
		];
		expect(packetStats(rows, null).noticed).toEqual([
			{ severity: 'error', group: 'Malformed', message: 'Malformed Packet (Exception occurred)', count: 1, frames: [30] },
			{ severity: 'warning', group: 'Sequence', message: 'This frame is a (suspected) retransmission', count: 2, frames: [15, 22] },
			// The lists don't pair up, so its severity and group are not guessed
			{ severity: 'unknown', group: 'unknown', message: 'Odd one', count: 1, frames: [31] },
		]);
	});

	it('refuses a packet time it cannot read rather than chart it somewhere', () => {
		expect(() => packetStats([row(7, '1.2e9', {})], null)).toThrow('Packet 7 has an unreadable time.');
	});
});

describe('serverNames', () => {
	const CLIENT = '192.0.2.10';
	const CDN = '203.0.113.45';

	it("names a server from a Client Hello's SNI on its own stream", () => {
		const rows = [tcp(1, '0', CLIENT, CDN), tcp(2, '0', CDN, CLIENT), tcp(4, '0', CLIENT, CDN, 'cdn.example-media.net'), tcp(5, '0', CDN, CLIENT)];
		expect(serverNames(rows)).toEqual(new Map([[CDN, 'cdn.example-media.net']]));
	});

	it('keeps the name when every stream to the server named it the same', () => {
		const rows = [tcp(1, '0', CLIENT, CDN, 'a.example'), tcp(2, '0', CDN, CLIENT), tcp(3, '1', CLIENT, CDN, 'a.example'), tcp(4, '1', CDN, CLIENT)];
		expect(serverNames(rows).get(CDN)).toBe('a.example');
	});

	it("leaves the server unnamed when two streams named it differently (a CDN serving two sites)", () => {
		const rows = [tcp(1, '0', CLIENT, CDN, 'a.example'), tcp(2, '1', CLIENT, CDN, 'b.example')];
		expect(serverNames(rows).size).toBe(0);
	});

	it("leaves it unnamed when one of its streams has no Client Hello in these rows", () => {
		const rows = [tcp(1, '0', CLIENT, CDN, 'a.example'), tcp(2, '0', CDN, CLIENT), tcp(3, '7', CDN, CLIENT)];
		expect(serverNames(rows).size).toBe(0);
	});

	it('only counts a Client Hello over TCP, with one SNI and one IP layer', () => {
		const quic = row(1, '1', { 'ip.src': [CLIENT], 'ip.dst': [CDN], 'udp.stream': ['0'], 'tls.handshake.type': ['1'], 'tls.handshake.extensions_server_name': ['q.example'] });
		const serverHello = row(2, '2', { 'ip.src': [CDN], 'ip.dst': [CLIENT], 'tcp.stream': ['3'], 'tls.handshake.type': ['2'], 'tls.handshake.extensions_server_name': ['s.example'] });
		const twoSni = tcp(3, '4', CLIENT, CDN, 'a.example');
		twoSni.fields['tls.handshake.extensions_server_name'] = ['a.example', 'b.example'];
		const tunnelled = tcp(4, '5', CLIENT, CDN, 'a.example');
		tunnelled.fields['ip.dst'] = [CDN, '10.0.0.2'];
		expect(serverNames([quic]).size).toBe(0);
		expect(serverNames([serverHello]).size).toBe(0);
		expect(serverNames([twoSni]).size).toBe(0);
		expect(serverNames([tunnelled]).size).toBe(0);
	});

	it('counts a Client Hello whose packet also holds other handshake types', () => {
		const both = tcp(1, '0', CLIENT, CDN, 'a.example');
		both.fields['tls.handshake.type'] = ['1', '22'];
		expect(serverNames([both]).get(CDN)).toBe('a.example');
	});

	it('finds nothing in the real fixture, which has no Client Hello', () => {
		expect(serverNames(ROWS).size).toBe(0);
	});
});
