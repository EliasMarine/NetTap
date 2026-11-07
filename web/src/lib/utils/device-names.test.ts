import { describe, it, expect } from 'vitest';
import { namesByIp } from './device-names';
import type { RegistryDevice } from '$api/devices-registry';

const device = (over: Partial<RegistryDevice>): RegistryDevice => ({
	mac: 'aa:bb:cc:00:00:01',
	ips: ['192.168.1.10'],
	hostnames: [],
	manufacturer: 'Apple, Inc.',
	friendly_name: null,
	display_name: 'Kitchen iPad',
	category: 'phone',
	first_seen: '2026-11-01T00:00:00Z',
	last_seen: '2026-11-05T00:00:00Z',
	is_new: false,
	...over,
});

describe('namesByIp', () => {
	it('maps every IP of a named device to its name', () => {
		const names = namesByIp([device({ ips: ['192.168.1.10', 'fe80::1'] })]);
		expect(names.get('192.168.1.10')).toBe('Kitchen iPad');
		expect(names.get('fe80::1')).toBe('Kitchen iPad');
	});

	it('treats the manufacturer, MAC and "Unknown" fallbacks as no name', () => {
		const names = namesByIp([
			device({ ips: ['10.0.0.1'], display_name: 'Apple, Inc.' }),
			device({ ips: ['10.0.0.2'], display_name: 'aa:bb:cc:00:00:01' }),
			device({ ips: ['10.0.0.3'], display_name: 'Unknown', manufacturer: null }),
			device({ ips: ['10.0.0.4'], display_name: '  ' }),
		]);
		expect(names.size).toBe(0);
	});

	it('gives a shared IP to the device seen most recently', () => {
		const names = namesByIp([
			device({ display_name: 'New phone', last_seen: '2026-11-05T10:00:00Z' }),
			device({ display_name: 'Old laptop', last_seen: '2026-10-01T10:00:00Z' }),
		]);
		expect(names.get('192.168.1.10')).toBe('New phone');
	});

	it('copes with no devices and no IPs', () => {
		expect(namesByIp([]).size).toBe(0);
		expect(namesByIp([device({ ips: [] })]).size).toBe(0);
	});

	// NET-200
	it("always takes the owner's name, even when it is the maker's", () => {
		const names = namesByIp([device({ ips: ['10.0.0.9'], manufacturer: 'Sonos', display_name: 'Sonos', custom_name: 'Sonos' })]);
		expect(names.get('10.0.0.9')).toBe('Sonos');
	});
});
