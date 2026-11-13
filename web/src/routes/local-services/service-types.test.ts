import { describe, it, expect } from 'vitest';
import { SSDP_NAME, rowMatches, serviceName, ssdpPacketsHref, vlanWords } from './service-types';
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
});

describe('ssdpPacketsHref', () => {
	const now = Date.UTC(2026, 10, 13, 12, 0, 0);
	it('asks Packet analysis for the sender\'s SSDP over the last 30 minutes', () => {
		const url = new URL(ssdpPacketsHref('192.168.1.44', now), 'http://x');
		expect(Object.fromEntries(url.searchParams)).toEqual({
			filter: 'ssdp && ip.src == 192.168.1.44',
			from: String(now / 1000 - 1800),
			to: String(now / 1000),
			limit: '100',
		});
	});

	it('uses the IPv6 field for an IPv6 sender', () => {
		expect(new URL(ssdpPacketsHref('fe80::1', now), 'http://x').searchParams.get('filter')).toBe('ssdp && ipv6.src == fe80::1');
	});
});
