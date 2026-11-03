import { describe, it, expect } from 'vitest';
import { validateDhcpSubnet, staticAddressHint, DEFAULT_DHCP_SUBNET } from './dhcpSubnet';

describe('validateDhcpSubnet', () => {
	it('accepts the default subnet', () => {
		expect(DEFAULT_DHCP_SUBNET).toBe('10.77.0.0/24');
		expect(validateDhcpSubnet(DEFAULT_DHCP_SUBNET, ['192.168.1.50'])).toEqual({ valid: true, error: '' });
	});

	it.each(['10.0.0.0/16', '172.16.0.0/16', '172.31.255.240/28', '192.168.100.0/24'])(
		'accepts private subnet %s',
		(cidr) => {
			expect(validateDhcpSubnet(cidr, []).valid).toBe(true);
		}
	);

	it.each(['', '10.77.0.0', '10.77.0/24', '10.77.0.0/', '256.1.1.0/24', '010.77.0.0/24', ' 10.77.0.0/24', '10.77.0.0/024', 'abc'])(
		'rejects malformed input %j',
		(cidr) => {
			const result = validateDhcpSubnet(cidr, []);
			expect(result.valid).toBe(false);
			expect(result.error).toContain('like 10.77.0.0/24');
		}
	);

	it.each(['10.0.0.0/8', '10.0.0.0/15', '10.77.0.0/29', '10.77.0.0/32'])('rejects prefix outside 16-28: %s', (cidr) => {
		const result = validateDhcpSubnet(cidr, []);
		expect(result.valid).toBe(false);
		expect(result.error).toContain('between /16 and /28');
	});

	it('rejects a host address and suggests the network address', () => {
		const result = validateDhcpSubnet('10.77.0.5/24', []);
		expect(result.valid).toBe(false);
		expect(result.error).toContain('Did you mean 10.77.0.0/24?');
	});

	it.each(['8.8.8.0/24', '172.32.0.0/16', '172.15.0.0/16', '192.169.0.0/16', '100.64.0.0/16'])(
		'rejects public or non-RFC1918 subnet %s',
		(cidr) => {
			const result = validateDhcpSubnet(cidr, []);
			expect(result.valid).toBe(false);
			expect(result.error).toContain('private range');
		}
	);

	it('rejects a subnet that contains a NIC address', () => {
		const result = validateDhcpSubnet('192.168.1.0/24', ['', '192.168.1.50']);
		expect(result.valid).toBe(false);
		expect(result.error).toContain('192.168.1.50');
	});

	it('accepts NIC addresses written with a prefix and ignores junk entries', () => {
		expect(validateDhcpSubnet('192.168.0.0/16', ['192.168.1.50/24']).valid).toBe(false);
		expect(validateDhcpSubnet('10.77.0.0/24', ['192.168.1.50/24', 'not-an-ip', '']).valid).toBe(true);
	});

	it('allows a NIC address just outside the subnet', () => {
		expect(validateDhcpSubnet('10.77.0.0/24', ['10.77.1.1']).valid).toBe(true);
		expect(validateDhcpSubnet('10.77.0.0/23', ['10.77.1.1']).valid).toBe(false);
	});
});

describe('staticAddressHint', () => {
	it('suggests host .20 with the netmask and the router address', () => {
		expect(staticAddressHint({ address: '192.168.1.50/24', gateway: '192.168.1.1' })).toEqual({
			ip: '192.168.1.20',
			mask: '255.255.255.0',
			router: '192.168.1.1',
		});
	});

	it('skips NetTap and the router when they sit on .20', () => {
		expect(staticAddressHint({ address: '10.0.0.20/16', gateway: '10.0.0.21' })).toEqual({
			ip: '10.0.0.22',
			mask: '255.255.0.0',
			router: '10.0.0.21',
		});
	});

	it('uses the first free host in a small network', () => {
		expect(staticAddressHint({ address: '192.168.5.2/29', gateway: '192.168.5.1' })?.ip).toBe('192.168.5.3');
	});

	it.each([
		null,
		{ address: '', gateway: '192.168.1.1' },
		{ address: '192.168.1.50', gateway: '192.168.1.1' },
		{ address: '192.168.1.50/24', gateway: '10.0.0.1' },
		{ address: '192.168.1.1/30', gateway: '192.168.1.2' },
	])('returns null for unusable upstream %j', (upstream) => {
		expect(staticAddressHint(upstream)).toBeNull();
	});
});
