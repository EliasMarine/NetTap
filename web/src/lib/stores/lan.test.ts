import { describe, it, expect, vi, afterEach } from 'vitest';
import { get } from 'svelte/store';
import type { LanPolicy } from '$lib/api/network';
// OLD CODE START: ipv4ToNumber came from './lan'; the maths is utils/dhcpSubnet.ts's now OLD CODE END
import { toNumber as ipv4ToNumber } from '$lib/utils/dhcpSubnet';
import { LAN_REFRESH_MS, addressHref, domainHref, inCidr, ipHref, isIpAddress, isLan, lanPolicy, lanStatus } from './lan';

// NET-160: a link goes to a device page only when the daemon's own LAN policy says so

const policy = (subnets: string[], version = 'v1'): LanPolicy => ({ version, subnets, source: 'env', ipv6: 'not-lan' });

describe('LAN policy maths', () => {
	it('reads dotted quads only', () => {
		expect(ipv4ToNumber('0.0.0.0')).toBe(0);
		expect(ipv4ToNumber('255.255.255.255')).toBe(2 ** 32 - 1);
		// leading zeros are rejected, as the daemon's parser does
		for (const bad of ['256.1.1.1', '1.2.3', '1.2.3.4.5', '2001:db8::1', 'a.b.c.d', '', '1.2.3.-4', '192.168.01.1']) {
			expect(ipv4ToNumber(bad)).toBeNull();
		}
	});

	it('includes the network and broadcast addresses of a block, and nothing either side', () => {
		const net = '192.168.1.0/24';
		expect(inCidr(ipv4ToNumber('192.168.1.0')!, net)).toBe(true);
		expect(inCidr(ipv4ToNumber('192.168.1.255')!, net)).toBe(true);
		expect(inCidr(ipv4ToNumber('192.168.0.255')!, net)).toBe(false);
		expect(inCidr(ipv4ToNumber('192.168.2.0')!, net)).toBe(false);
	});

	it('treats /0 as everything and /32 as one address', () => {
		expect(inCidr(ipv4ToNumber('8.8.8.8')!, '0.0.0.0/0')).toBe(true);
		expect(inCidr(ipv4ToNumber('255.255.255.255')!, '0.0.0.0/0')).toBe(true);
		expect(inCidr(ipv4ToNumber('10.1.2.3')!, '10.1.2.3/32')).toBe(true);
		expect(inCidr(ipv4ToNumber('10.1.2.4')!, '10.1.2.3/32')).toBe(false);
	});

	it('rejects malformed CIDRs instead of matching them', () => {
		const ip = ipv4ToNumber('10.0.0.1')!;
		for (const bad of ['10.0.0.0', '10.0.0.0/33', '10.0.0.0/x', 'nonsense/8']) expect(inCidr(ip, bad)).toBe(false);
	});

	it('uses the listed subnets, and every RFC 1918 range when there are none', () => {
		const listed = policy(['192.168.50.0/24']);
		expect(lanStatus(listed, '192.168.50.7')).toBe(true);
		expect(lanStatus(listed, '10.0.0.1')).toBe(false);
		const rfc = policy([]);
		for (const ip of ['10.0.0.1', '172.16.0.1', '172.31.255.255', '192.168.0.1']) expect(lanStatus(rfc, ip)).toBe(true);
		for (const ip of ['172.32.0.1', '8.8.8.8', '192.169.0.1']) expect(lanStatus(rfc, ip)).toBe(false);
	});

	it('never calls IPv6 LAN, as the daemon does', () => {
		expect(lanStatus(policy([]), 'fd00::1')).toBe(false);
		expect(lanStatus(policy(['0.0.0.0/0']), 'fe80::1')).toBe(false);
	});

	it('knows nothing before the policy loads, and sends links to the address page', () => {
		expect(lanStatus(null, '192.168.1.5')).toBeNull();
		expect(addressHref(null, '192.168.1.5')).toBe('/address/192.168.1.5');
	});

	it('sends LAN addresses to the device page and the rest to the address page, encoded', () => {
		const p = policy([]);
		expect(addressHref(p, '192.168.1.5')).toBe('/devices/192.168.1.5');
		expect(addressHref(p, '203.0.113.9')).toBe('/address/203.0.113.9');
		expect(addressHref(p, '2001:db8::1')).toBe('/address/2001%3Adb8%3A%3A1');
	});

	it('links a domain by the name the daemon matches: no trailing dot, lower case', () => {
		expect(domainHref('WWW.Example.COM.')).toBe('/domain/www.example.com');
		expect(domainHref('example.com')).toBe('/domain/example.com');
		expect(domainHref('a b')).toBe('/domain/a%20b');
	});
});

describe('isIpAddress', () => {
	it.each([
		['192.168.1.5', true],
		[' 10.0.0.1 ', true],
		['2001:db8::1', true],
		['::1', true],
		['::ffff:192.0.2.1', true],
		['192.168.1', false],
		['tcp:443', false],
		['dns', false],
		['a:b', false],
		['fe80::1%eth0', false],
		['', false],
	])('%s is an address: %s', (text, expected) => {
		expect(isIpAddress(text)).toBe(expected);
	});
});

describe('LAN policy store', () => {
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	function stubPolicies(...replies: (LanPolicy | null)[]) {
		let i = 0;
		const fetchMock = vi.fn(async () => {
			const body = replies[Math.min(i++, replies.length - 1)];
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 404, json: async () => ({}) };
		});
		vi.stubGlobal('fetch', fetchMock);
		return fetchMock;
	}

	it('loads on first use, refetches every 5 minutes and takes a new version', async () => {
		vi.useFakeTimers();
		const fetchMock = stubPolicies(policy(['192.168.1.0/24'], 'v1'), policy(['10.0.0.0/8'], 'v2'));
		const seen: (LanPolicy | null)[] = [];
		const stop = lanPolicy.subscribe((p) => seen.push(p));
		await vi.waitFor(() => expect(get(isLan)('192.168.1.5')).toBe(true));
		expect(get(ipHref)('192.168.1.5')).toBe('/devices/192.168.1.5');
		expect(fetchMock).toHaveBeenCalledWith('/api/network/lan');

		await vi.advanceTimersByTimeAsync(LAN_REFRESH_MS);
		await vi.waitFor(() => expect(get(isLan)('192.168.1.5')).toBe(false));
		expect(get(isLan)('10.2.3.4')).toBe(true);
		expect(get(ipHref)('192.168.1.5')).toBe('/address/192.168.1.5');
		stop();
	});

	it('keeps the same policy object while the version is unchanged', async () => {
		vi.useFakeTimers();
		stubPolicies(policy(['192.168.1.0/24'], 'same'));
		const seen: (LanPolicy | null)[] = [];
		const stop = lanPolicy.subscribe((p) => seen.push(p));
		await vi.waitFor(() => expect(seen.at(-1)?.version).toBe('same'));
		const count = seen.length;
		await vi.advanceTimersByTimeAsync(LAN_REFRESH_MS);
		expect(seen.length).toBe(count);
		stop();
	});

	it('keeps the same object across a resubscribe while the version holds', async () => {
		vi.useFakeTimers();
		stubPolicies(policy(['192.168.7.0/24'], 'resub'));
		const seen: (LanPolicy | null)[] = [];
		let stop = lanPolicy.subscribe((p) => seen.push(p));
		await vi.waitFor(() => expect(seen.at(-1)?.version).toBe('resub'));
		const first = seen.at(-1);
		stop();
		stop = lanPolicy.subscribe((p) => seen.push(p));
		await vi.advanceTimersByTimeAsync(0);
		expect(seen.at(-1)).toBe(first);
		stop();
	});

	it('stops refetching after the last unsubscribe, and ignores a reply that lands after it', async () => {
		vi.useFakeTimers();
		let answer: (v: unknown) => void = () => {};
		const fetchMock = vi.fn(() => new Promise((r) => (answer = r)));
		vi.stubGlobal('fetch', fetchMock);
		const seen: (LanPolicy | null)[] = [];
		const stop = lanPolicy.subscribe((p) => seen.push(p));
		expect(fetchMock).toHaveBeenCalledTimes(1);
		stop();
		answer({ ok: true, status: 200, json: async () => policy(['10.9.0.0/16'], 'late') });
		await vi.advanceTimersByTimeAsync(LAN_REFRESH_MS * 2);
		expect(fetchMock).toHaveBeenCalledTimes(1);
		expect(seen.some((p) => p?.version === 'late')).toBe(false);
		// a new subscriber starts from the last policy, never the late one
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		expect(get(lanPolicy)?.version).not.toBe('late');
	});

	it('keeps the last policy when a refetch fails', async () => {
		vi.useFakeTimers();
		stubPolicies(policy(['172.20.0.0/16'], 'v9'), null);
		const stop = lanPolicy.subscribe(() => {});
		await vi.waitFor(() => expect(get(isLan)('172.20.1.1')).toBe(true));
		await vi.advanceTimersByTimeAsync(LAN_REFRESH_MS);
		expect(get(isLan)('172.20.1.1')).toBe(true);
		stop();
	});
});
