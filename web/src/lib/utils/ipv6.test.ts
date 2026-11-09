import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { classify, compress, inspect, parse, slaac, TYPES, type Inspection } from './ipv6';

const ok = (input: string): Inspection => {
	const r = inspect(input);
	if (!r.ok) throw new Error(`${input} should parse: ${r.error}`);
	return r;
};
const error = (input: string): { error: string; hint: 'ipv4' | null } => {
	const r = inspect(input);
	if (r.ok) throw new Error(`${input} should fail`);
	return r;
};
const short = (input: string): string => {
	const p = parse(input);
	if (!p.ok) throw new Error(p.error);
	return compress(p.value);
};

describe('inspect: the examples the page offers', () => {
	it('reads a documentation address and assumes a /64', () => {
		const r = ok('2001:db8::1');
		expect(r.compressed).toBe('2001:db8::1');
		expect(r.expanded).toBe('2001:0db8:0000:0000:0000:0000:0000:0001');
		expect(r.type.key).toBe('documentation');
		expect(r.iface?.kind).toBe('low');
		expect(r.block).toMatchObject({ block: '2001:db8::/64', assumed: true });
		expect(r.reverse).toBe('1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa');
	});

	it('finds the candidate MAC in an EUI-64 link-local address', () => {
		const r = ok('fe80::a00:27ff:fe4e:66a1%eth0');
		expect(r.type.key).toBe('linklocal');
		expect(r.zone).toBe('eth0');
		expect(r.iface).toEqual({ kind: 'eui64', id: 'a00:27ff:fe4e:66a1', mac: '08:00:27:4e:66:a1', localMac: false });
		expect(r.solicited).toBe('ff02::1:ff4e:66a1');
		expect(r.zoneMissing).toBe(false);
		expect(ok('fe80::1').zoneMissing).toBe(true);
	});

	it('writes IPv4-mapped addresses with the IPv4 part dotted', () => {
		const r = ok('::ffff:192.0.2.10');
		expect(r.type.key).toBe('mapped');
		expect(r.compressed).toBe('::ffff:192.0.2.10');
		expect(r.expanded).toBe('0000:0000:0000:0000:0000:ffff:c000:020a');
		expect(r.embedded).toEqual([{ label: 'Embedded IPv4', value: '192.0.2.10' }]);
		expect(r.block).toBeNull();
		expect(ok('0:0:0:0:0:ffff:192.0.2.10').compressed).toBe('::ffff:192.0.2.10');
	});

	it('sizes a typed block', () => {
		const r = ok('2001:db8:abcd::/48');
		expect(r.block).toMatchObject({ block: '2001:db8:abcd::/48', last: '2001:db8:abcd:ffff:ffff:ffff:ffff:ffff', subnets64: '65,536', addresses: null, hostBits: 80, assumed: false });
		expect(ok('2001:db8::/120').block?.addresses).toBe('256');
		expect(ok('2001:db8:abcd:1200::/56').block?.note).toMatch(/home internet providers/);
	});
});

describe('inspect: a network in CIDR versus an address', () => {
	it('reads a prefix ≤ 64 with every later bit zero as a network', () => {
		for (const input of ['2001:db8::/64', '2001:db8:abcd:1200::/56']) {
			const r = ok(input);
			expect(r.isNetwork).toBe(true);
			expect(r.iface).toBeNull();
			expect(r.solicited).toBeNull();
		}
	});

	it('keeps an address inside a block an address, and shows its containing block', () => {
		const r = ok('2001:db8:abcd:1201::/56');
		expect(r.isNetwork).toBe(false);
		expect(r.iface?.kind).toBe('anycast');
		expect(r.block?.block).toBe('2001:db8:abcd:1200::/56');
		expect(ok('2001:db8:abcd::5/48').iface?.kind).toBe('low');
	});

	it('never reads /127 or /128 as a network', () => {
		for (const input of ['2001:db8::1234/128', '2001:db8::2/127', '2001:db8::3/127']) {
			const r = ok(input);
			expect(r.isNetwork).toBe(false);
			expect(r.iface).not.toBeNull();
			expect(r.solicited).not.toBeNull();
		}
		expect(ok('2001:db8::2/127').block?.note).toMatch(/point-to-point/);
	});
});

describe('inspect: tunnels and embedded IPv4', () => {
	it('unscrambles the RFC 4380 Teredo example', () => {
		const r = ok('2001:0:4136:e378:8000:63bf:3fff:fdd2');
		expect(r.type.key).toBe('teredo');
		expect(r.embedded.map((e) => e.value)).toEqual(['65.54.227.120', '192.0.2.45', '40000']);
		expect(r.iface).toBeNull();
	});

	it('reads 6to4 and NAT64', () => {
		expect(ok('2002:c000:20a::1').embedded[0].value).toBe('192.0.2.10');
		expect(ok('64:ff9b::198.51.100.7').embedded[0].value).toBe('198.51.100.7');
	});
});

describe('compress (RFC 5952)', () => {
	it.each([
		['2001:0db8:0000:0000:0001:0000:0000:0001', '2001:db8::1:0:0:1'], // the first of two equal runs
		['2001:db8:0:1:1:1:1:1', '2001:db8:0:1:1:1:1:1'], // a single zero group stays
		['2001:DB8:0:0:0:0:2:1', '2001:db8::2:1'],
		['::', '::'],
		['1::', '1::'],
		['0:0:0:0:0:0:0:1', '::1'],
		['1:2:3:4:5:6:7::', '1:2:3:4:5:6:7:0'],
		['[2001:db8::1]:443', '2001:db8::1'],
	])('%s → %s', (input, expected) => {
		expect(short(input)).toBe(expected);
	});
});

describe('classify', () => {
	it.each([
		['fd12:3456:789a::1', 'ula'],
		['2606:4700:4700::1111', 'global'],
		['fec0::1', 'sitelocal'],
		['4000::1', 'reserved'],
		['ff02::fb', 'multicast'],
		['::1', 'loopback'],
		['::', 'unspecified'],
		// Longest prefix wins where ranges overlap
		['3fff::1', 'documentation-2'],
		['2001:2::1', 'benchmarking'],
		['64:ff9b:1::1', 'nat64-local'],
		['100:0:0:1::1', 'dummy'],
		['100::1', 'discard'],
		['2001:5::1', 'ietf'],
		['2001:1::1', 'pcp-anycast'],
		['2001:1::4', 'ietf'],
		['2001::1', 'teredo'],
		['2620:4f:8000::1', 'as112-direct'],
		['2620:4f:8001::1', 'global'],
		['5f00::1', 'srv6'],
	])('%s is %s', (input, key) => {
		expect(ok(input).type.key).toBe(key);
	});

	it('notes how a ULA prefix was chosen', () => {
		expect(ok('fd12:3456:789a::1').ulaNote).toMatch(/at random/);
		expect(ok('fc00::1').ulaNote).toMatch(/reserved/);
	});

	it('reads the interface ID only as a pattern', () => {
		expect(ok('2001:db8::').iface?.kind).toBe('anycast'); // no prefix typed: an address, not a network
		expect(ok('2001:db8::1:2:3:4').iface?.kind).toBe('random');
		expect(classify(parseOk('2001:db8::')).key).toBe('documentation');
	});
});

describe('the IANA special-purpose registry snapshot', () => {
	// The registry's own CSV, downloaded 2026-11-08: every row must have a range, with the same reachability
	const csv = readFileSync(resolve(process.cwd(), 'src/lib/utils/iana-ipv6-special-registry.csv'), 'utf8').trim().split('\n').slice(1);
	const rows = csv.map((line) => {
		const cols = line.split(',');
		return { block: cols[0].replace(/\s*\[\d+\]/, ''), reachable: cols[8].replace(/\s*\[\d+\]/, '').trim() };
	});

	it('has 25 rows', () => {
		expect(rows).toHaveLength(25);
	});

	it.each(rows)('$block has a range with matching reachability', ({ block, reachable }) => {
		const [net, len] = block.split('/');
		const value = parseOk(net);
		const range = TYPES.find((t) => t.value === value && t.len === Number(len));
		expect(range, `no range for ${block}`).toBeDefined();
		const expected = reachable === 'True' ? true : reachable === 'False' ? false : null;
		expect(range?.globallyReachable).toBe(expected);
	});
});

describe('multicast', () => {
	it('names known groups and the scope', () => {
		const r = ok('ff02::fb');
		expect(r.group).toMatch(/mDNS/);
		expect(r.reach).toBe('This network segment');
		expect(r.block).toBeNull();
		expect(r.iface).toBeNull();
		expect(ok('ff0e::101').reach).toBe('The whole internet');
	});

	it('explains solicited-node groups', () => {
		expect(ok('ff02::1:ff4e:66a1').group).toMatch(/…4e:66a1/);
	});
});

describe('errors say what is wrong', () => {
	it.each([
		['1::2::3', /Only one ::/],
		['2001:db8::g', /isn't hex/],
		['12345::', /too long/],
		['1:2:3:4:5:6:7', /Only 7 groups/],
		['1:2:3:4:5:6:7:8:9', /too many/],
		['1:2:3:4:5:6:7::8', /at most seven/],
		['1.2.3.4::', /only allowed at the very end/],
		['::ffff:300.1.1.1', /valid IPv4 ending/],
		['::ffff:010.1.1.1', /valid IPv4 ending/],
		['2001:db8::/129', /0 to 128/],
		['2001:db8::/1/2', /Only one \//],
		['fe80::1%eth 0', /interface name/],
		[':1::', /empty group/],
		['1:::2', /empty group/],
		['hello', /groups of hex digits/],
	])('%s', (input, pattern) => {
		expect(error(input).error).toMatch(pattern);
	});

	it('points IPv4 at the Subnet calculator', () => {
		expect(error('192.168.1.1')).toMatchObject({ hint: 'ipv4', error: expect.stringMatching(/Subnet calculator/) });
	});

	it('returns an empty error for blank input', () => {
		expect(error('   ').error).toBe('');
	});
});

describe('slaac', () => {
	it('builds link-local and prefixed addresses', () => {
		expect(slaac('08:00:27:4e:66:a1')).toMatchObject({ ok: true, address: 'fe80::a00:27ff:fe4e:66a1' });
		expect(slaac('b8-27-eb-12-34-56', '2001:db8:1:2::/64')).toMatchObject({ ok: true, address: '2001:db8:1:2:ba27:ebff:fe12:3456' });
		expect(slaac('b827.eb12.3456', '2001:db8:1:2::')).toMatchObject({ ok: true, address: '2001:db8:1:2:ba27:ebff:fe12:3456' });
	});

	it('round-trips: the MAC read back from the address is the one it was built from', () => {
		const built = slaac('3c:22:fb:01:02:03');
		if (!built.ok) throw new Error(built.error);
		expect(ok(built.address).iface?.mac).toBe('3c:22:fb:01:02:03');
	});

	it.each([
		['08:00:27', '', /12 hex digits/],
		['01:00:5e:00:00:fb', '', /multicast \(group\) MAC/],
		['08:00:27:4e:66:a1', '2001:db8::/56', /\/64/],
		['08:00:27:4e:66:a1', '2001:db8::1234/64', /last 64 bits must be zero/],
		['08:00:27:4e:66:a1', 'ff02::/64', /Multicast addresses aren't built with SLAAC/],
		['08:00:27:4e:66:a1', '::/64', /Unspecified/],
		['08:00:27:4e:66:a1', '100::/64', /Discard-only/],
		['08:00:27:4e:66:a1', 'nonsense', /Network prefix:/],
	])('refuses %s on "%s"', (mac, prefix, pattern) => {
		const r = slaac(mac, prefix);
		expect(r.ok).toBe(false);
		if (!r.ok) expect(r.error).toMatch(pattern);
	});

	it('flags a locally administered candidate MAC', () => {
		expect(ok('fe80::ff:fe00:1').iface).toMatchObject({ kind: 'eui64', localMac: true });
	});
});

function parseOk(s: string): bigint {
	const p = parse(s);
	if (!p.ok) throw new Error(p.error);
	return p.value;
}
