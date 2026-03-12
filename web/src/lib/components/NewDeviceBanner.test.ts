import { describe, it, expect } from 'vitest';

/**
 * Tests for NewDeviceBanner component logic.
 *
 * Tests the filtering logic that determines which devices are "new".
 */

// ---------------------------------------------------------------------------
// Reproduced pure logic from NewDeviceBanner.svelte
// ---------------------------------------------------------------------------

interface RegistryDevice {
	mac: string;
	ips: string[];
	hostnames: string[];
	manufacturer: string | null;
	friendly_name: string | null;
	display_name: string;
	category: string;
	first_seen: string;
	last_seen: string;
	is_new: boolean;
}

function filterNewDevices(devices: RegistryDevice[]): RegistryDevice[] {
	return devices.filter((d) => d.is_new);
}

function isVisible(newDevices: RegistryDevice[], dismissed: boolean): boolean {
	return newDevices.length > 0 && !dismissed;
}

function bannerText(count: number): string {
	return `${count} new device${count !== 1 ? 's' : ''} detected`;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('NewDeviceBanner logic', () => {
	const makeDevice = (mac: string, isNew: boolean): RegistryDevice => ({
		mac,
		ips: ['192.168.1.1'],
		hostnames: [],
		manufacturer: null,
		friendly_name: null,
		display_name: mac,
		category: 'unknown',
		first_seen: '2026-03-01T00:00:00Z',
		last_seen: '2026-03-08T12:00:00Z',
		is_new: isNew,
	});

	describe('filterNewDevices', () => {
		it('returns only devices with is_new=true', () => {
			const devices = [
				makeDevice('AA:01', true),
				makeDevice('AA:02', false),
				makeDevice('AA:03', true),
			];

			const result = filterNewDevices(devices);

			expect(result).toHaveLength(2);
			expect(result[0].mac).toBe('AA:01');
			expect(result[1].mac).toBe('AA:03');
		});

		it('returns empty array when no devices are new', () => {
			const devices = [
				makeDevice('AA:01', false),
				makeDevice('AA:02', false),
			];

			const result = filterNewDevices(devices);

			expect(result).toHaveLength(0);
		});

		it('returns empty array for empty input', () => {
			const result = filterNewDevices([]);
			expect(result).toHaveLength(0);
		});
	});

	describe('isVisible', () => {
		it('returns true when there are new devices and not dismissed', () => {
			const newDevices = [makeDevice('AA:01', true)];
			expect(isVisible(newDevices, false)).toBe(true);
		});

		it('returns false when dismissed', () => {
			const newDevices = [makeDevice('AA:01', true)];
			expect(isVisible(newDevices, true)).toBe(false);
		});

		it('returns false when no new devices', () => {
			expect(isVisible([], false)).toBe(false);
		});

		it('returns false when no new devices and dismissed', () => {
			expect(isVisible([], true)).toBe(false);
		});
	});

	describe('bannerText', () => {
		it('uses singular for 1 device', () => {
			expect(bannerText(1)).toBe('1 new device detected');
		});

		it('uses plural for multiple devices', () => {
			expect(bannerText(3)).toBe('3 new devices detected');
		});

		it('uses plural for 0 devices', () => {
			expect(bannerText(0)).toBe('0 new devices detected');
		});
	});
});
