import { describe, it, expect } from 'vitest';
import { buildTSharkFilter, getField, asString } from './tshark-filter';

// ---------------------------------------------------------------------------
// getField
// ---------------------------------------------------------------------------

describe('getField', () => {
	it('extracts nested values by dot path', () => {
		const obj = { source: { ip: '192.168.1.1' } };
		expect(getField(obj, 'source.ip')).toBe('192.168.1.1');
	});

	it('returns undefined for missing paths', () => {
		expect(getField({}, 'source.ip')).toBeUndefined();
		expect(getField({ source: {} }, 'source.ip')).toBeUndefined();
	});

	it('handles top-level keys', () => {
		expect(getField({ proto: 'tcp' }, 'proto')).toBe('tcp');
	});
});

// ---------------------------------------------------------------------------
// asString
// ---------------------------------------------------------------------------

describe('asString', () => {
	it('returns string values directly', () => {
		expect(asString('hello')).toBe('hello');
	});

	it('extracts first element from arrays', () => {
		expect(asString(['192.168.1.1', '10.0.0.1'])).toBe('192.168.1.1');
	});

	it('returns empty string for non-string values', () => {
		expect(asString(42)).toBe('');
		expect(asString(null)).toBe('');
		expect(asString(undefined)).toBe('');
	});

	it('returns empty string for empty arrays', () => {
		expect(asString([])).toBe('');
	});
});

// ---------------------------------------------------------------------------
// buildTSharkFilter
// ---------------------------------------------------------------------------

describe('buildTSharkFilter', () => {
	it('builds TCP filter with both IPs and destination port', () => {
		const conn = {
			source: { ip: '192.168.1.10' },
			destination: { ip: '8.8.8.8', port: 443 },
			network: { transport: 'tcp' },
		};
		expect(buildTSharkFilter(conn)).toBe(
			'ip.addr == 192.168.1.10 && ip.addr == 8.8.8.8 && tcp.port == 443',
		);
	});

	it('builds UDP filter with destination port', () => {
		const conn = {
			source: { ip: '192.168.1.10' },
			destination: { ip: '1.1.1.1', port: 53 },
			network: { transport: 'UDP' },
		};
		expect(buildTSharkFilter(conn)).toBe(
			'ip.addr == 192.168.1.10 && ip.addr == 1.1.1.1 && udp.port == 53',
		);
	});

	it('does NOT include ephemeral source port', () => {
		const conn = {
			source: { ip: '192.168.1.10', port: 54321 },
			destination: { ip: '8.8.8.8', port: 443 },
			network: { transport: 'tcp' },
		};
		const filter = buildTSharkFilter(conn);
		expect(filter).not.toContain('54321');
		expect(filter).toContain('tcp.port == 443');
	});

	it('uses ipv6.addr for IPv6 addresses', () => {
		const conn = {
			source: { ip: '2001:db8::1' },
			destination: { ip: '2001:db8::2', port: 443 },
			network: { transport: 'tcp' },
		};
		expect(buildTSharkFilter(conn)).toBe(
			'ipv6.addr == 2001:db8::1 && ipv6.addr == 2001:db8::2 && tcp.port == 443',
		);
	});

	it('handles mixed IPv4 and IPv6 addresses', () => {
		const conn = {
			source: { ip: '192.168.1.10' },
			destination: { ip: '2001:db8::1', port: 80 },
			network: { transport: 'tcp' },
		};
		expect(buildTSharkFilter(conn)).toBe(
			'ip.addr == 192.168.1.10 && ipv6.addr == 2001:db8::1 && tcp.port == 80',
		);
	});

	it('uses bare protocol name for ICMP (no ports)', () => {
		const conn = {
			source: { ip: '192.168.1.10' },
			destination: { ip: '8.8.8.8' },
			network: { transport: 'icmp' },
		};
		expect(buildTSharkFilter(conn)).toBe(
			'ip.addr == 192.168.1.10 && ip.addr == 8.8.8.8 && icmp',
		);
	});

	it('uses bare protocol name for ICMPv6', () => {
		const conn = {
			source: { ip: '2001:db8::1' },
			destination: { ip: '2001:db8::2' },
			network: { transport: 'icmpv6' },
		};
		expect(buildTSharkFilter(conn)).toBe(
			'ipv6.addr == 2001:db8::1 && ipv6.addr == 2001:db8::2 && icmpv6',
		);
	});

	it('never generates icmp.port (invalid TShark field)', () => {
		const conn = {
			source: { ip: '192.168.1.10' },
			destination: { ip: '8.8.8.8', port: 8 },
			network: { transport: 'icmp' },
		};
		const filter = buildTSharkFilter(conn);
		expect(filter).not.toContain('icmp.port');
		expect(filter).toContain('icmp');
	});

	it('falls back to IP-only filter when transport is missing', () => {
		const conn = {
			source: { ip: '192.168.1.10' },
			destination: { ip: '8.8.8.8' },
		};
		expect(buildTSharkFilter(conn)).toBe(
			'ip.addr == 192.168.1.10 && ip.addr == 8.8.8.8',
		);
	});

	it('returns empty string when no fields are available', () => {
		expect(buildTSharkFilter({})).toBe('');
	});

	it('handles OpenSearch array-wrapped values', () => {
		const conn = {
			source: { ip: ['192.168.1.10'] },
			destination: { ip: ['8.8.8.8'], port: 443 },
			network: { transport: ['tcp'] },
		};
		expect(buildTSharkFilter(conn)).toBe(
			'ip.addr == 192.168.1.10 && ip.addr == 8.8.8.8 && tcp.port == 443',
		);
	});
});
