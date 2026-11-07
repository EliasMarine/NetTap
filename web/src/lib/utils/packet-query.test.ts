import { describe, it, expect } from 'vitest';
import type { LanPolicy } from '$lib/api/network';
import { inCidr, lanStatus } from '$lib/stores/lan';
import { toNumber } from '$lib/utils/dhcpSubnet';
import {
	filterFor,
	windowFor,
	readUrlState,
	packetsUrl,
	connectionFilter,
	connectionSegments,
	connectionUrl,
	epochNs,
	nsEpoch,
	type PacketQuestion,
	type PacketUrlState,
	type ConnectionRef,
} from './packet-query';

type Q = Pick<PacketQuestion, 'device' | 'other' | 'port' | 'kinds'>;
const q = (over: Partial<Q> = {}): Q => ({ device: null, other: { kind: 'anyone' }, port: null, kinds: [], ...over });
const policy = (subnets: string[]): LanPolicy => ({ version: 'v1', subnets, source: 'env', ipv6: 'not-lan' });
const params = (url: string) => new URL(url, 'https://nettap.local').searchParams;

// ---------------------------------------------------------------------------
// filterFor
// ---------------------------------------------------------------------------

describe('filterFor', () => {
	it('is empty, every packet, when nothing is chosen or All traffic is', () => {
		expect(filterFor(q(), null)).toBe('');
		expect(filterFor(q({ kinds: ['all'] }), null)).toBe('');
		expect(filterFor(q({ kinds: ['all', 'lookups'] }), null)).toBe('');
	});

	it("matches a device both ways and keeps the mockup's Name lookups filter", () => {
		expect(filterFor(q({ device: '192.168.1.70', kinds: ['lookups'] }), null)).toBe(
			'ip.addr == 192.168.1.70 && dns && dns.flags.response == 0',
		);
	});

	it('joins device, other side and port in that order (Main mockup)', () => {
		expect(filterFor(q({ device: '192.168.1.42', other: { kind: 'address', value: ' 203.0.113.45 ' }, port: 443 }), null)).toBe(
			'ip.addr == 192.168.1.42 && ip.addr == 203.0.113.45 && (tcp.port == 443 || udp.port == 443)',
		);
	});

	it('brackets kinds so && and || never depend on precedence', () => {
		expect(filterFor(q({ kinds: ['new-connections', 'pings'] }), null)).toBe(
			'(tcp.flags.syn == 1 && tcp.flags.ack == 0) || icmp.type == 8 || icmp.type == 0',
		);
		expect(filterFor(q({ device: '192.168.1.70', kinds: ['new-connections', 'pings'] }), null)).toBe(
			'ip.addr == 192.168.1.70 && ((tcp.flags.syn == 1 && tcp.flags.ack == 0) || icmp.type == 8 || icmp.type == 0)',
		);
		expect(filterFor(q({ kinds: ['pings', 'pings'] }), null)).toBe('icmp.type == 8 || icmp.type == 0');
	});

	it('takes library filter ids as kinds, so "Use" keeps the device and port', () => {
		expect(filterFor(q({ device: '192.168.1.70', port: 53, kinds: ['dns-failed'] }), null)).toBe(
			'ip.addr == 192.168.1.70 && (tcp.port == 53 || udp.port == 53) && dns.flags.rcode != 0',
		);
	});

	it('refuses a kind it does not know', () => {
		expect(() => filterFor(q({ kinds: ['nope'] }), null)).toThrow('doesn\'t know the kind of traffic “nope”');
	});

	it('uses ipv6.addr for IPv6, in lower case', () => {
		expect(filterFor(q({ device: '2001:DB8::1' }), null)).toBe('ipv6.addr == 2001:db8::1');
		expect(filterFor(q({ other: { kind: 'address', value: 'fe80::1' } }), null)).toBe('ipv6.addr == fe80::1');
	});

	it('refuses a device that is not an address', () => {
		expect(() => filterFor(q({ device: 'kitchen-ipad' }), null)).toThrow("isn't an IP address");
		expect(() => filterFor(q({ device: '192.168.1.070' }), null)).toThrow("isn't an IP address");
	});

	it("matches a site name in the SNI, a DNS name or the HTTP host, as the daemon's canonical name", () => {
		expect(filterFor(q({ other: { kind: 'address', value: ' WWW.Example.com. ' } }), null)).toBe(
			'tls.handshake.extensions_server_name == "www.example.com" || dns.qry.name == "www.example.com" || http.host == "www.example.com"',
		);
		expect(filterFor(q({ device: '192.168.1.70', other: { kind: 'address', value: 'example.com' } }), null)).toBe(
			'ip.addr == 192.168.1.70 && (tls.handshake.extensions_server_name == "example.com" || dns.qry.name == "example.com" || http.host == "example.com")',
		);
	});

	it.each(['exa"mple.com', "exa'mple.com", 'example.com" || 1 || "', 'a b.com', 'example.com;rm', '$(id).com', 'ex\\ample.com', 'a..com'])(
		'refuses the site name %s in plain English',
		(value) => {
			expect(() => filterFor(q({ other: { kind: 'address', value } }), null)).toThrow(
				'A site name can only use letters, digits, dots, hyphens and underscores',
			);
		},
	);

	it('asks for an address when the box is empty', () => {
		expect(() => filterFor(q({ other: { kind: 'address', value: '  ' } }), null)).toThrow('Type an address or a site name.');
	});

	it.each([0, 65536, 1.5, -1, Number.NaN])('refuses port %s', (port) => {
		expect(() => filterFor(q({ port }), null)).toThrow('A port is a whole number from 1 to 65535.');
	});

	it('accepts ports 1 and 65535', () => {
		expect(filterFor(q({ port: 1 }), null)).toBe('tcp.port == 1 || udp.port == 1');
		expect(filterFor(q({ port: 65535 }), null)).toBe('tcp.port == 65535 || udp.port == 65535');
	});
});

describe('filterFor: narrowing filters', () => {
	const CHATTER = '!(arp || mdns || ssdp || llmnr || nbns || igmp)';
	const WEB = 'tcp.port == 80 || tcp.port == 443 || udp.port == 443';

	it('ANDs a "Narrow it down" filter onto the kinds instead of ORing it, which would match nearly everything', () => {
		expect(filterFor(q({ kinds: ['sites', 'hide-chatter'] }), null)).toBe(`tls.handshake.type == 1 && (${CHATTER})`);
		expect(filterFor(q({ kinds: ['hide-chatter', 'dns-asked', 'sites', 'web-only'] }), null)).toBe(
			`(dns.flags.response == 0 || tls.handshake.type == 1) && (${CHATTER}) && (${WEB})`,
		);
	});

	it('leaves a narrowing filter alone as it is, and narrows "All traffic" to it', () => {
		expect(filterFor(q({ kinds: ['hide-chatter'] }), null)).toBe(CHATTER);
		expect(filterFor(q({ kinds: ['all', 'web-only'] }), null)).toBe(WEB);
		expect(filterFor(q({ device: '192.168.1.5', kinds: ['web-only'] }), null)).toBe(`ip.addr == 192.168.1.5 && (${WEB})`);
	});

	it('stays under 500 characters for the longest built-in question with a narrowing filter added', () => {
		const f = filterFor(q({ device: '192.168.100.200', other: { kind: 'internet' }, port: 65535, kinds: ['new-connections', 'pings', 'hide-chatter'] }), policy([]));
		expect(f.length).toBeLessThanOrEqual(500);
	});
});

describe('filterFor: the internet', () => {
	const LOCAL = '0.0.0.0/8 127.0.0.0/8 169.254.0.0/16 224.0.0.0/3';
	// The exact text checked on TShark 4.0.17: commas between the set's blocks, never spaces alone
	const expected = (blocks: string) => {
		const set = `{${blocks.split(' ').join(', ')}}`;
		return `(ip && (!(ip.src in ${set}) || !(ip.dst in ${set}))) || ipv6.addr == 2000::/3`;
	};

	it("can't be told apart before the LAN policy loads", () => {
		expect(() => filterFor(q({ other: { kind: 'internet' } }), null)).toThrow("hasn't loaded your network's address ranges");
	});

	it("is an IPv4 address outside the LAN's subnets and the local-only blocks, or a global IPv6 address", () => {
		expect(filterFor(q({ other: { kind: 'internet' } }), policy(['192.168.1.0/24']))).toBe(expected(`192.168.1.0/24 ${LOCAL}`));
	});

	it('uses every RFC 1918 range when the policy lists no subnets, as lanStatus does', () => {
		expect(filterFor(q({ other: { kind: 'internet' } }), policy([]))).toBe(expected(`10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 ${LOCAL}`));
	});

	it('drops a subnet the LAN rule cannot read, and only parsed numbers reach the filter', () => {
		const f = filterFor(q({ other: { kind: 'internet' } }), policy(['10.0.0.0/33', 'x/8', '010.1.0.0/16', '192.168.1.0/24/ || 1 || x', '10.9.0.0/16']));
		expect(f).toBe(expected(`192.168.1.0/24 10.9.0.0/16 ${LOCAL}`));
	});

	it('brackets the internet when joined to a device', () => {
		const f = filterFor(q({ device: '192.168.1.70', other: { kind: 'internet' } }), policy(['192.168.1.0/24']));
		expect(f).toBe(`ip.addr == 192.168.1.70 && (${expected(`192.168.1.0/24 ${LOCAL}`)})`);
	});

	// The filter's LAN blocks must say "LAN" for exactly the addresses lanStatus does
	it.each([[['192.168.1.0/24']], [[]], [['10.20.0.0/16', '172.16.5.0/24']]])('agrees with lanStatus for policy %j', (subnets) => {
		const lan = policy(subnets);
		const blocks = /ip\.src in \{([^}]*)\}/.exec(filterFor(q({ other: { kind: 'internet' } }), lan))![1].split(', ');
		const local = LOCAL.split(' ');
		const lanBlocks = blocks.filter((b) => !local.includes(b));
		for (const ip of ['192.168.1.9', '192.168.2.9', '10.20.3.4', '10.21.0.1', '172.16.5.7', '172.17.0.1', '8.8.8.8', '203.0.113.45']) {
			const inBlocks = lanBlocks.some((b) => inCidr(toNumber(ip)!, b));
			expect([ip, inBlocks]).toEqual([ip, lanStatus(lan, ip)]);
		}
	});

	it('stays under the daemon\'s 500 characters with the RFC 1918 ranges, a device, a port and two kinds', () => {
		const f = filterFor(q({ device: '192.168.100.200', other: { kind: 'internet' }, port: 65535, kinds: ['new-connections', 'pings'] }), policy([]));
		expect(f.length).toBeLessThanOrEqual(500);
	});
});

describe('filterFor: length', () => {
	it("refuses a filter longer than the daemon's 500 characters, saying how long", () => {
		const many = Array.from({ length: 20 }, (_, i) => `10.${i}.0.0/16`);
		expect(() => filterFor(q({ other: { kind: 'internet' } }), policy(many))).toThrow(
			/^This question needs a filter of \d+ characters, and the packet reader takes 500\. Pick fewer kinds of traffic\.$/,
		);
	});
});

// ---------------------------------------------------------------------------
// Windows and the URL
// ---------------------------------------------------------------------------

describe('windowFor', () => {
	it('ends a "last" window at now, to the millisecond, exactly', () => {
		expect(windowFor({ kind: 'last', seconds: 900 }, 1_794_026_197_218)).toEqual({ from: '1794025297.218', to: '1794026197.218' });
		expect(windowFor({ kind: 'last', seconds: 300 }, 1_794_026_197_000)).toEqual({ from: '1794025897', to: '1794026197' });
		expect(windowFor({ kind: 'last', seconds: 1800 }, 1_794_026_197_001)).toEqual({ from: '1794024397.001', to: '1794026197.001' });
	});

	it('passes a range through untouched', () => {
		expect(windowFor({ kind: 'range', from: '1794026197.218929', to: '1794026200' }, 0)).toEqual({ from: '1794026197.218929', to: '1794026200' });
	});
});

describe('epochNs / nsEpoch', () => {
	it('round-trip exactly, past what a float holds', () => {
		expect(epochNs('1794026197.218929123')).toBe(1_794_026_197_218_929_123n);
		expect(nsEpoch(1_794_026_197_218_929_123n)).toBe('1794026197.218929123');
		expect(nsEpoch(epochNs('1700000000.000001000')!)).toBe('1700000000.000001');
		expect(nsEpoch(0n)).toBe('0');
	});

	it.each(['', 'abc', '1e9', '-5', '1.', '.5', '1.2.3', '123456789012', '1.1234567890', '1700000000\n'])('refuses %j', (t) => {
		expect(epochNs(t)).toBeNull();
	});
});

describe('readUrlState / packetsUrl', () => {
	const base: PacketUrlState = { filter: 'dns', from: '1794026000.5', to: '1794026900', limit: 250, device: null, conn: null };

	it('is null on a first visit', () => {
		expect(readUrlState(new URLSearchParams())).toBeNull();
	});

	it.each<PacketUrlState>([
		base,
		{ ...base, filter: '', limit: 100 },
		{ ...base, filter: 'http.host == "a&b=c#d" && !(ip.addr == 10.0.0.1)', limit: 1000, device: '192.168.1.42' },
		{ ...base, device: '2001:db8::1', conn: { start: '1794026001.218929', duration: null, segment: 0, exact: false } },
		{ ...base, conn: { start: '1794020000', duration: 8040.123456, segment: 3, exact: true } },
		{ ...base, from: '1794026000', to: '1794027800' },
	])('round-trips %j', (state) => {
		const url = packetsUrl(state);
		expect(url.startsWith('/packets?')).toBe(true);
		expect(readUrlState(params(url))).toEqual(state);
	});

	it('reads a URL without a filter as every packet', () => {
		expect(readUrlState(params('/packets?from=1&to=2&limit=100'))?.filter).toBe('');
	});

	it.each([
		['a bad from', 'from=abc&to=1794026900&limit=100'],
		['a float-style epoch', 'from=1.79e9&to=1794026900&limit=100'],
		['a missing to', 'from=1794026000&limit=100'],
		['a limit of 500', 'from=1794026000&to=1794026900&limit=500'],
		['a limit of 1000.0', 'from=1794026000&to=1794026900&limit=1000.0'],
		['no limit', 'from=1794026000&to=1794026900'],
		['from = to', 'from=1794026000&to=1794026000&limit=100'],
		['from after to', 'from=1794026900&to=1794026000&limit=100'],
		['a window 1 ns over 1800 s', 'from=1794026000&to=1794027800.000000001&limit=100'],
		['a device that is not an IP', 'from=1794026000&to=1794026900&limit=100&device=tv'],
		['a connection without a segment', 'from=1794026000&to=1794026900&limit=100&conn=1794026001&exact=1'],
		['a negative segment', 'from=1794026000&to=1794026900&limit=100&conn=1794026001&dur=10&seg=-1&exact=1'],
		['a segment past the end', 'from=1794026000&to=1794026900&limit=100&conn=1794026001&dur=10&seg=1&exact=1'],
		['a bad connection start', 'from=1794026000&to=1794026900&limit=100&conn=soon&dur=10&seg=0&exact=1'],
		['a negative duration', 'from=1794026000&to=1794026900&limit=100&conn=1794026001&dur=-1&seg=0&exact=1'],
		['an empty duration', 'from=1794026000&to=1794026900&limit=100&conn=1794026001&dur=&seg=0&exact=1'],
		['a duration over a year', 'from=1794026000&to=1794026900&limit=100&conn=1794026001&dur=99999999999&seg=0&exact=1'],
		['a connection without exact', 'from=1794026000&to=1794026900&limit=100&conn=1794026001&dur=10&seg=0'],
		['exact=true', 'from=1794026000&to=1794026900&limit=100&conn=1794026001&dur=10&seg=0&exact=true'],
		['an empty exact', 'from=1794026000&to=1794026900&limit=100&conn=1794026001&dur=10&seg=0&exact='],
		['exact=2', 'from=1794026000&to=1794026900&limit=100&conn=1794026001&dur=10&seg=0&exact=2'],
	])('refuses %s rather than guess', (_name, query) => {
		expect(readUrlState(new URLSearchParams(query))).toBeNull();
	});

	it('accepts a connection with exact=1 or exact=0, and ignores exact without one', () => {
		const query = 'from=1794026000&to=1794026900&limit=100&conn=1794026001&dur=10&seg=0';
		expect(readUrlState(new URLSearchParams(`${query}&exact=1`))?.conn?.exact).toBe(true);
		expect(readUrlState(new URLSearchParams(`${query}&exact=0`))?.conn?.exact).toBe(false);
		expect(readUrlState(new URLSearchParams('from=1794026000&to=1794026900&limit=100&exact=1'))?.conn).toBeNull();
	});

	it('accepts a window of exactly 1800 s', () => {
		expect(readUrlState(new URLSearchParams('from=1794026000.5&to=1794027800.5&limit=100'))).not.toBeNull();
	});
});

// ---------------------------------------------------------------------------
// A connection from Connections
// ---------------------------------------------------------------------------

const conn = (over: Partial<ConnectionRef> = {}): ConnectionRef => ({
	proto: 'tcp',
	srcIp: '192.168.1.42',
	srcPort: 51834,
	dstIp: '203.0.113.45',
	dstPort: 443,
	start: '1794026197.218929',
	duration: 34,
	...over,
});

describe('connectionFilter', () => {
	it('tells two simultaneous connections between the same hosts apart', () => {
		const one = connectionFilter(conn({ srcPort: 51834 }));
		const two = connectionFilter(conn({ srcPort: 51835 }));
		expect(one).toEqual({
			filter:
				'(ip.src == 192.168.1.42 && tcp.srcport == 51834 && ip.dst == 203.0.113.45 && tcp.dstport == 443) || ' +
				'(ip.src == 203.0.113.45 && tcp.srcport == 443 && ip.dst == 192.168.1.42 && tcp.dstport == 51834)',
			exact: true,
			label: 'the TCP connection from 192.168.1.42 port 51834 to 203.0.113.45 port 443',
		});
		// Each names only its own client port, in both directions
		expect(one.filter.match(/5183\d/g)).toEqual(['51834', '51834']);
		expect(two.filter.match(/5183\d/g)).toEqual(['51835', '51835']);
	});

	it('uses udp.* for UDP and ipv6.* for IPv6', () => {
		expect(connectionFilter(conn({ proto: 'UDP', srcIp: '2001:DB8::5', srcPort: 5353, dstIp: '2001:db8::1', dstPort: 53 })).filter).toBe(
			'(ipv6.src == 2001:db8::5 && udp.srcport == 5353 && ipv6.dst == 2001:db8::1 && udp.dstport == 53) || ' +
				'(ipv6.src == 2001:db8::1 && udp.srcport == 53 && ipv6.dst == 2001:db8::5 && udp.dstport == 5353)',
		);
	});

	it('falls back to all traffic between the two addresses when a port is missing', () => {
		for (const c of [conn({ srcPort: null }), conn({ dstPort: null }), conn({ proto: 'icmp', srcPort: 8, dstPort: 0 })]) {
			expect(connectionFilter(c)).toEqual({
				filter: 'ip.addr == 192.168.1.42 && ip.addr == 203.0.113.45',
				exact: false,
				label: 'all traffic between these two addresses (no exact connection)',
			});
		}
	});

	it('refuses addresses it cannot put in a filter, or two families', () => {
		expect(() => connectionFilter(conn({ srcIp: 'tv.local' }))).toThrow("isn't an IP address");
		expect(() => connectionFilter(conn({ dstIp: '2001:db8::1' }))).toThrow('one family');
	});
});

describe('connectionSegments', () => {
	const START = '1794026197.218929';

	it('keeps a fractional start to the exact digit: start − 1 s to start + duration + 1 s', () => {
		expect(connectionSegments(START, 12.5)).toEqual([
			{ index: 0, count: 1, from: '1794026196.218929', to: '1794026210.718929', label: 'the whole connection (12 s)' },
		]);
		expect(connectionSegments('1794026197.218929001', 0)[0]).toMatchObject({ from: '1794026196.218929001', to: '1794026198.218929001' });
	});

	it('gives a 29 min 58 s (1,798 s) connection one window of exactly 1,800 s', () => {
		expect(connectionSegments('1794026000', 1798)).toEqual([
			{ index: 0, count: 1, from: '1794025999', to: '1794027799', label: 'the whole connection (29 min 58 s)' },
		]);
	});

	it('cuts a 29 min 59 s (1,799 s) connection into two segments', () => {
		expect(connectionSegments('1794026000', 1799)).toEqual([
			{ index: 0, count: 2, from: '1794025999', to: '1794027799', label: 'minutes 0 to 30 of a 29 min 59 s connection' },
			{ index: 1, count: 2, from: '1794027799', to: '1794027800', label: 'minute 30 to the end of a 29 min 59 s connection' },
		]);
	});

	it('cuts an hours-long connection into 30-minute segments, the last shorter, end to end', () => {
		const segs = connectionSegments('1794020000.5', 8040.25);
		expect(segs.map((s) => [s.from, s.to])).toEqual([
			['1794019999.5', '1794021799.5'],
			['1794021799.5', '1794023599.5'],
			['1794023599.5', '1794025399.5'],
			['1794025399.5', '1794027199.5'],
			['1794027199.5', '1794028041.75'],
		]);
		expect(segs.map((s) => s.label)).toEqual([
			'minutes 0 to 30 of a 2 h 14 min connection',
			'minutes 30 to 60 of a 2 h 14 min connection',
			'minutes 60 to 90 of a 2 h 14 min connection',
			'minutes 90 to 120 of a 2 h 14 min connection',
			'minute 120 to the end of a 2 h 14 min connection',
		]);
		expect(segs.every((s) => s.count === 5)).toBe(true);
		const last = segs[4];
		expect(epochNs(last.to)! - epochNs(last.from)!).toBe(842_250_000_000n);
	});

	it('gives a connection of unknown length one 60 s window from start − 1 s', () => {
		expect(connectionSegments(START, null)).toEqual([
			{ index: 0, count: 1, from: '1794026196.218929', to: '1794026256.218929', label: "the first minute (the connection's length isn't recorded)" },
		]);
	});

	it('labels lengths without overstating them', () => {
		expect(connectionSegments('100', 0)[0].label).toBe('the whole connection (under 1 s)');
		expect(connectionSegments('100', 59.9)[0].label).toBe('the whole connection (59 s)');
		expect(connectionSegments('100', 120)[0].label).toBe('the whole connection (2 min)');
		expect(connectionSegments('100', 7200)[0].label).toBe('minutes 0 to 30 of a 2 h connection');
	});

	it('refuses a bad start or duration', () => {
		expect(() => connectionSegments('soon', 10)).toThrow("isn't an epoch time");
		expect(() => connectionSegments(START, -1)).toThrow('zero seconds to a year');
		expect(() => connectionSegments(START, Number.POSITIVE_INFINITY)).toThrow('zero seconds to a year');
	});
});

describe('connectionUrl', () => {
	const lan = policy(['192.168.1.0/24']);

	it('opens the connection with its exact filter, window, 1,000 packets and the LAN side as the device', () => {
		const state = readUrlState(params(connectionUrl(conn(), lan)));
		expect(state).toEqual({
			filter: connectionFilter(conn()).filter,
			from: '1794026196.218929',
			to: '1794026232.218929',
			limit: 1000,
			device: '192.168.1.42',
			conn: { start: '1794026197.218929', duration: 34, segment: 0, exact: true },
		});
	});

	it('anchors on the LAN side whichever end opened it', () => {
		const reply = conn({ srcIp: '203.0.113.45', srcPort: 443, dstIp: '192.168.1.42', dstPort: 51834 });
		expect(readUrlState(params(connectionUrl(reply, lan)))?.device).toBe('192.168.1.42');
	});

	it('has no device when both or neither side is on the LAN, or the policy has not loaded', () => {
		expect(readUrlState(params(connectionUrl(conn({ dstIp: '192.168.1.1' }), lan)))?.device).toBeNull();
		expect(readUrlState(params(connectionUrl(conn({ srcIp: '198.51.100.1' }), lan)))?.device).toBeNull();
		expect(readUrlState(params(connectionUrl(conn(), null)))?.device).toBeNull();
	});

	it("keeps a connection without ports marked inexact after a reload, whatever the filter says", () => {
		const url = connectionUrl(conn({ srcPort: null }), lan);
		const state = readUrlState(params(url));
		expect(state?.conn?.exact).toBe(false);
		expect(state?.filter).toBe('ip.addr == 192.168.1.42 && ip.addr == 203.0.113.45');
		// The user edits the filter; exactness still comes from the URL, not the text
		const edited = readUrlState(params(packetsUrl({ ...state!, filter: `${state!.filter} && tcp.srcport == 51834` })));
		expect(edited?.conn?.exact).toBe(false);
	});

	it('opens a later segment of a long connection, and refuses one that does not exist', () => {
		const c = conn({ start: '1794020000', duration: 8040 });
		const state = readUrlState(params(connectionUrl(c, lan, 4)));
		expect(state).toMatchObject({ from: '1794027199', to: '1794028041', conn: { segment: 4 } });
		expect(() => connectionUrl(c, lan, 5)).toThrow('no segment 6');
	});
});
