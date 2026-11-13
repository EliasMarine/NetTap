import { describe, it, expect } from 'vitest';
import { SSDP_NAME, isLinkLocal6, rowMatches, serviceName, ssdpPacketsHref, vlanWords } from './service-types';
import { MAX_WINDOW_SECONDS } from '$lib/utils/packet-query';
import { LOCAL_SERVICES } from '../../../e2e/visual/fixtures/local-services';

describe('serviceName', () => {
	it.each([
		['_airplay._tcp', 'AirPlay receiver'],
		['_raop._tcp', 'AirPlay speaker'],
		['_googlecast._tcp', 'Google Cast'],
		['_hue._tcp', 'Philips Hue bridge'],
		['_ipps._tcp', 'Printer (AirPrint/IPP)'],
		['_amzn-wplay._tcp', 'Amazon Fire TV'],
		['_smb._tcp', 'File share (SMB)'],
	])('names %s as %s', (type, name) => {
		expect(serviceName('mdns', type)).toBe(name);
	});

	it('falls back to the raw type for one it does not know', () => {
		expect(serviceName('mdns', '_workstation._tcp')).toBe('_workstation._tcp');
		// an inherited object key is not a name
		expect(serviceName('mdns', '__proto__._tcp')).toBe('__proto__._tcp');
	});

	it('names every SSDP row the same way', () => {
		expect(serviceName('ssdp', '')).toBe(SSDP_NAME);
	});
});

describe('vlanWords', () => {
	it.each([
		[{ vlan: '2', vlan_state: 'tagged' }, '2'],
		[{ vlan: null, vlan_state: 'untagged' }, 'untagged'],
		[{ vlan: null, vlan_state: 'unknown' }, 'not yet known'],
	] as const)('reads %o as %s', (part, words) => {
		expect(vlanWords({ ip: '192.0.2.1', mac: null, name: null, ...part })).toBe(words);
	});
});

describe('rowMatches', () => {
	const [unknown, tv, router] = LOCAL_SERVICES.rows;
	it('matches the plain name, raw type, sender and VLAN words, ignoring case', () => {
		expect(rowMatches(tv, 'airplay RECEIVER')).toBe(true);
		expect(rowMatches(tv, '_airplay._tcp')).toBe(true);
		expect(rowMatches(tv, 'living room tv')).toBe(true);
		expect(rowMatches(router, '10.10.0.1')).toBe(true);
		expect(rowMatches(unknown, 'not yet known')).toBe(true);
		expect(rowMatches(tv, 'mdns')).toBe(true);
		expect(rowMatches(tv, 'hue')).toBe(false);
		expect(rowMatches(tv, '  ')).toBe(true);
	});

	it('finds an SSDP row by its protocol and name', () => {
		const ssdp = LOCAL_SERVICES.rows.find((r) => r.protocol === 'ssdp')!;
		expect(rowMatches(ssdp, 'ssdp')).toBe(true);
		expect(rowMatches(ssdp, 'upnp')).toBe(true);
		expect(rowMatches(tv, 'ssdp')).toBe(false);
	});

	it('reads regex characters as themselves', () => {
		const printer = { ...tv, service_type: '_ipp._tcp' };
		expect(rowMatches(printer, '(airprint')).toBe(true);
		expect(rowMatches(tv, '(')).toBe(false);
		expect(rowMatches(tv, '.*')).toBe(false);
	});
});

describe('ssdpPacketsHref', () => {
	const seen = '2026-11-13T12:00:00.250Z';
	const at = Date.parse(seen) / 1000;
	const params = (href: string | null) => new URL(href!, 'http://x').searchParams;

	it("asks Packet analysis for the sender's SSDP from a minute before its last announcement to five after", () => {
		expect(Object.fromEntries(params(ssdpPacketsHref('192.168.1.44', seen)))).toEqual({
			filter: 'ssdp && ip.src == 192.168.1.44',
			from: String(at - 60),
			to: String(at + 300),
			limit: '100',
		});
		const p = params(ssdpPacketsHref('192.168.1.44', seen));
		expect(Number(p.get('to')) - Number(p.get('from'))).toBeLessThanOrEqual(MAX_WINDOW_SECONDS);
	});

	it('uses the IPv6 field for an IPv6 sender', () => {
		expect(params(ssdpPacketsHref('fe80::1', seen)).get('filter')).toBe('ssdp && ipv6.src == fe80::1');
	});

	it('builds no link for anything but an address, or an unreadable time', () => {
		expect(ssdpPacketsHref('192.168.1.44 || frame', seen)).toBeNull();
		expect(ssdpPacketsHref('host', seen)).toBeNull();
		expect(ssdpPacketsHref('192.168.1.44', 'yesterday')).toBeNull();
	});
});

describe('isLinkLocal6', () => {
	it.each([
		['fe80::1', true],
		['FE80::200:5eff:fe10:12', true],
		['febf::1', true],
		['fec0::1', false],
		['2001:db8::1', false],
		['192.168.1.1', false],
	])('reads %s as %s', (ip, local) => {
		expect(isLinkLocal6(ip)).toBe(local);
	});
});
