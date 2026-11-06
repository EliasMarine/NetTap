import type { RegistryDevice } from '$api/devices-registry';

/**
 * IP → the device's name, for devices NetTap knows a real name for. The registry's
 * display_name falls back to the manufacturer, the MAC or "Unknown" (the daemon's
 * get_display_name); those are not names, so such devices show their IP instead.
 * When DHCP has given one IP to two devices, the one seen most recently wins.
 */
export function namesByIp(devices: readonly RegistryDevice[]): Map<string, string> {
	const named = devices.filter((d) => {
		const name = d.display_name?.trim();
		return !!name && name !== d.manufacturer && name !== d.mac && name !== 'Unknown';
	});
	const oldestFirst = [...named].sort((a, b) => Date.parse(a.last_seen || '') - Date.parse(b.last_seen || '') || 0);
	return new Map(oldestFirst.flatMap((d) => (d.ips ?? []).map((ip) => [ip, d.display_name.trim()] as const)));
}
