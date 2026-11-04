import { describe, it, expect } from 'vitest';
import { groupByType } from './device-types';
import type { RegistryDevice } from '$api/devices-registry';

function reg(mac: string, category: string, lastSeen: string): RegistryDevice {
	return {
		mac, ips: [], hostnames: [], manufacturer: null, friendly_name: null, display_name: mac,
		category, first_seen: '2026-11-01T00:00:00Z', last_seen: lastSeen, is_new: false,
	};
}

describe('groupByType', () => {
	it('groups in the fixed type order and leaves out empty groups', () => {
		const groups = groupByType([
			reg('a', 'iot', '2026-11-02T00:00:00Z'),
			reg('b', 'computer', '2026-11-02T00:00:00Z'),
			reg('c', 'media', '2026-11-02T00:00:00Z'),
		]);
		expect(groups.map((g) => g.key)).toEqual(['computer', 'media', 'iot']);
		expect(groups.map((g) => g.label)).toEqual(['Computers', 'Media', 'IoT devices']);
	});

	it('puts the most recently seen device first in each group', () => {
		const [group] = groupByType([
			reg('old', 'phone', '2026-11-01T00:00:00Z'),
			reg('new', 'phone', '2026-11-03T00:00:00Z'),
			reg('mid', 'phone', '2026-11-02T00:00:00Z'),
		]);
		expect(group.devices.map((d) => d.mac)).toEqual(['new', 'mid', 'old']);
	});

	// Home's grid silently dropped media and any other category it didn't list
	it('files an unlisted or empty category under Unknown, so no device is lost', () => {
		const groups = groupByType([reg('x', 'printer', '2026-11-02T00:00:00Z'), reg('y', '', '2026-11-02T00:00:00Z')]);
		expect(groups).toHaveLength(1);
		expect(groups[0].key).toBe('unknown');
		expect(groups[0].devices.map((d) => d.mac).sort()).toEqual(['x', 'y']);
	});

	it('returns no groups for no devices and leaves the input untouched', () => {
		expect(groupByType([])).toEqual([]);
		const input = [reg('b', 'phone', '2026-11-01T00:00:00Z'), reg('a', 'phone', '2026-11-02T00:00:00Z')];
		groupByType(input);
		expect(input.map((d) => d.mac)).toEqual(['b', 'a']);
	});
});
