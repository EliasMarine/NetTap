import { describe, it, expect } from 'vitest';
import { withTraffic } from './registry-traffic';
import type { Device } from '$api/devices';
import type { RegistryDevice } from '$api/devices-registry';

// Home's device cards read "--" for every device's traffic: the registry has none.

const FROM = '2026-11-01T22:00:00Z';

function reg(mac: string, ips: string[], lastSeen: string): RegistryDevice {
	return {
		mac, ips, hostnames: [], manufacturer: null, friendly_name: null, display_name: mac,
		category: 'unknown', first_seen: '2026-11-01T00:00:00Z', last_seen: lastSeen, is_new: false,
	};
}

function row(ip: string, bytes: number, conns: number, lastSeen: string): Device {
	return {
		ip, mac: null, hostname: null, manufacturer: null, os_hint: null, first_seen: FROM,
		last_seen: lastSeen, total_bytes: bytes, connection_count: conns, protocols: [], alert_count: 0,
	};
}

describe('withTraffic', () => {
	const gateway = reg('D0:21:F9:5E:35:32', ['192.168.1.1', '10.10.0.1'], '2026-11-02T21:00:00+00:00');
	const list = [
		row('192.168.1.1', 1000, 10, '2026-11-02T21:50:00Z'),
		row('10.10.0.1', 500, 5, '2026-11-02T21:40:00Z'),
	];

	it("adds up a device's IPs and takes the newest record as last seen", () => {
		const [card] = withTraffic([gateway], list, true, FROM);
		expect([card.total_bytes, card.connection_count, card.last_seen]).toEqual([1500, 15, '2026-11-02T21:50:00Z']);
	});

	it('gives a real 0 to a device last seen before the range on a complete list', () => {
		const [card] = withTraffic([reg('AA:00:00:00:00:01', ['192.168.1.9'], '2026-11-01T10:00:00+00:00')], list, true, FROM);
		expect([card.total_bytes, card.connection_count]).toEqual([0, 0]);
	});

	it('leaves a device seen in the range but not listed unknown (an excluded IP, say)', () => {
		const appliance = reg('8C:32:23:82:08:55', ['192.168.1.199'], '2026-11-02T17:00:00+00:00');
		expect(withTraffic([appliance], list, true, FROM)[0].total_bytes).toBeUndefined();
	});

	it('leaves unlisted devices unknown when the list stopped at its limit or failed', () => {
		const quiet = reg('AA:00:00:00:00:01', ['192.168.1.9'], '2026-11-01T10:00:00+00:00');
		expect(withTraffic([quiet], list, false, FROM)[0].total_bytes).toBeUndefined();
		expect(withTraffic([quiet], null, true, FROM)[0].total_bytes).toBeUndefined();
	});
});
