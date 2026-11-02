import type { Device } from '$api/devices';
import type { RegistryDevice } from '$api/devices-registry';

/**
 * Home's device cards (the registry, one card per MAC) with the time range's traffic from the
 * device list (one row per IP), so a card shows what the Devices page shows for its IPs.
 *
 * The registry carries no traffic, so every card read "--". A card none of whose IPs is listed
 * gets a real 0 only when the list is complete and the device was last seen before the range
 * began; otherwise (an excluded or skipped IP, a list cut at its limit, or no list) it stays
 * unknown.
 */
export function withTraffic(
	registry: RegistryDevice[],
	list: Device[] | null,
	listComplete: boolean,
	rangeFrom: string,
): RegistryDevice[] {
	if (!list) return registry;
	const byIp = new Map(list.map((d) => [d.ip, d]));
	return registry.map((device) => {
		const rows = device.ips.flatMap((ip) => byIp.get(ip) ?? []);
		if (rows.length === 0) {
			const quiet = listComplete && Date.parse(device.last_seen) < Date.parse(rangeFrom);
			return quiet ? { ...device, total_bytes: 0, connection_count: 0 } : device;
		}
		return {
			...device,
			total_bytes: rows.reduce((sum, d) => sum + d.total_bytes, 0),
			connection_count: rows.reduce((sum, d) => sum + d.connection_count, 0),
			// the list's newest record, as the Devices page shows it (the registry refreshes on a timer)
			last_seen: [device.last_seen, ...rows.map((d) => d.last_seen)].reduce((a, b) =>
				Date.parse(b) > Date.parse(a) ? b : a,
			),
		};
	});
}
