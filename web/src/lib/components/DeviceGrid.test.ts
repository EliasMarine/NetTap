import { describe, it, expect } from 'vitest';

/**
 * Tests for DeviceGrid component logic.
 *
 * Tests the pure grouping, sorting, and formatting functions.
 */

// ---------------------------------------------------------------------------
// Reproduced pure logic from DeviceGrid.svelte
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
	total_bytes?: number;
	connection_count?: number;
}

const CATEGORIES = [
	{ key: 'computer', label: 'Computers', icon: 'monitor' },
	{ key: 'phone', label: 'Phones & Tablets', icon: 'phone' },
	{ key: 'iot', label: 'IoT Devices', icon: 'cpu' },
	{ key: 'infrastructure', label: 'Infrastructure', icon: 'server' },
	{ key: 'unknown', label: 'Unknown', icon: 'help' },
] as const;

function groupDevices(devices: RegistryDevice[]): Record<string, RegistryDevice[]> {
	const groups: Record<string, RegistryDevice[]> = {};
	for (const cat of CATEGORIES) {
		groups[cat.key] = [];
	}
	for (const device of devices) {
		const cat = device.category || 'unknown';
		if (!groups[cat]) groups[cat] = [];
		groups[cat].push(device);
	}
	for (const key of Object.keys(groups)) {
		groups[key].sort((a, b) =>
			new Date(b.last_seen).getTime() - new Date(a.last_seen).getTime()
		);
	}
	return groups;
}

function formatBytes(bytes: number | undefined): string {
	if (!bytes || bytes <= 0) return '--';
	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	const i = Math.floor(Math.log(bytes) / Math.log(1024));
	const value = bytes / Math.pow(1024, i);
	return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[i]}`;
}

function timeAgo(iso: string): string {
	if (!iso) return '--';
	const diffMs = Date.now() - new Date(iso).getTime();
	const mins = Math.floor(diffMs / 60000);
	if (mins < 1) return 'just now';
	if (mins < 60) return `${mins}m ago`;
	const hrs = Math.floor(mins / 60);
	if (hrs < 24) return `${hrs}h ago`;
	const days = Math.floor(hrs / 24);
	return `${days}d ago`;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DeviceGrid logic', () => {
	// -- Device grouping ------------------------------------------------------

	describe('groupDevices', () => {
		const makeDevice = (mac: string, category: string, lastSeen: string): RegistryDevice => ({
			mac,
			ips: ['192.168.1.1'],
			hostnames: [],
			manufacturer: null,
			friendly_name: null,
			display_name: mac,
			category,
			first_seen: '2026-01-01T00:00:00Z',
			last_seen: lastSeen,
			is_new: false,
		});

		it('groups devices by category', () => {
			const devices = [
				makeDevice('AA:01', 'computer', '2026-03-08T00:00:00Z'),
				makeDevice('AA:02', 'phone', '2026-03-08T00:00:00Z'),
				makeDevice('AA:03', 'computer', '2026-03-08T00:00:00Z'),
				makeDevice('AA:04', 'iot', '2026-03-08T00:00:00Z'),
			];

			const groups = groupDevices(devices);

			expect(groups['computer']).toHaveLength(2);
			expect(groups['phone']).toHaveLength(1);
			expect(groups['iot']).toHaveLength(1);
			expect(groups['infrastructure']).toHaveLength(0);
			expect(groups['unknown']).toHaveLength(0);
		});

		it('sorts devices within group by last_seen descending', () => {
			const devices = [
				makeDevice('AA:01', 'computer', '2026-03-01T00:00:00Z'),
				makeDevice('AA:02', 'computer', '2026-03-08T00:00:00Z'),
				makeDevice('AA:03', 'computer', '2026-03-05T00:00:00Z'),
			];

			const groups = groupDevices(devices);

			expect(groups['computer'][0].mac).toBe('AA:02');
			expect(groups['computer'][1].mac).toBe('AA:03');
			expect(groups['computer'][2].mac).toBe('AA:01');
		});

		it('handles empty device list', () => {
			const groups = groupDevices([]);

			for (const cat of CATEGORIES) {
				expect(groups[cat.key]).toHaveLength(0);
			}
		});

		it('puts unknown-category devices into unknown group', () => {
			const devices = [
				makeDevice('AA:01', '', '2026-03-08T00:00:00Z'),
			];

			const groups = groupDevices(devices);

			expect(groups['unknown']).toHaveLength(1);
		});
	});

	// -- formatBytes ----------------------------------------------------------

	describe('formatBytes', () => {
		it('returns -- for undefined', () => {
			expect(formatBytes(undefined)).toBe('--');
		});

		it('returns -- for zero', () => {
			expect(formatBytes(0)).toBe('--');
		});

		it('returns -- for negative values', () => {
			expect(formatBytes(-100)).toBe('--');
		});

		it('formats bytes', () => {
			expect(formatBytes(500)).toBe('500 B');
		});

		it('formats KB', () => {
			expect(formatBytes(2048)).toBe('2.0 KB');
		});

		it('formats MB', () => {
			expect(formatBytes(5242880)).toBe('5.0 MB');
		});
	});

	// -- timeAgo --------------------------------------------------------------

	describe('timeAgo', () => {
		it('returns -- for empty string', () => {
			expect(timeAgo('')).toBe('--');
		});

		it('returns "just now" for recent timestamps', () => {
			const now = new Date().toISOString();
			expect(timeAgo(now)).toBe('just now');
		});

		it('returns minutes for timestamps less than an hour old', () => {
			const fiveMinAgo = new Date(Date.now() - 5 * 60 * 1000).toISOString();
			expect(timeAgo(fiveMinAgo)).toBe('5m ago');
		});

		it('returns hours for timestamps less than a day old', () => {
			const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
			expect(timeAgo(twoHoursAgo)).toBe('2h ago');
		});

		it('returns days for older timestamps', () => {
			const threeDaysAgo = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString();
			expect(timeAgo(threeDaysAgo)).toBe('3d ago');
		});
	});

	// -- CATEGORIES -----------------------------------------------------------

	describe('CATEGORIES', () => {
		it('has 5 categories', () => {
			expect(CATEGORIES).toHaveLength(5);
		});

		it('includes computer, phone, iot, infrastructure, unknown', () => {
			const keys = CATEGORIES.map((c) => c.key);
			expect(keys).toContain('computer');
			expect(keys).toContain('phone');
			expect(keys).toContain('iot');
			expect(keys).toContain('infrastructure');
			expect(keys).toContain('unknown');
		});
	});
});
