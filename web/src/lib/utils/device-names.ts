import type { RegistryDevice } from '$api/devices-registry';

// OLD CODE START — NET-200: an owner's name equal to the maker ("Sonos") read as no name
// export function namesByIp(devices: readonly RegistryDevice[]): Map<string, string> {
// 	const named = devices.filter((d) => {
// 		const name = d.display_name?.trim();
// 		return !!name && name !== d.manufacturer && name !== d.mac && name !== 'Unknown';
// 	});
// 	const oldestFirst = [...named].sort((a, b) => Date.parse(a.last_seen || '') - Date.parse(b.last_seen || '') || 0);
// 	return new Map(oldestFirst.flatMap((d) => (d.ips ?? []).map((ip) => [ip, d.display_name.trim()] as const)));
// }
// OLD CODE END

/** The owner's name always counts (NET-200); a discovered one only when it isn't a fallback. */
function realName(d: RegistryDevice): string | null {
	const own = d.custom_name?.trim();
	if (own) return own;
	const name = d.display_name?.trim();
	return name && name !== d.manufacturer && name !== d.mac && name !== 'Unknown' ? name : null;
}

/**
 * IP → the device's name, for devices NetTap knows a real name for. The registry's
 * display_name falls back to the manufacturer, the MAC or "Unknown" (the daemon's
 * get_display_name); those are not names, so such devices show their IP instead.
 * The owner's own name (NET-200) always counts.
 * When DHCP has given one IP to two devices, the one seen most recently wins.
 */
export function namesByIp(devices: readonly RegistryDevice[]): Map<string, string> {
	const named = devices.flatMap((d) => {
		const name = realName(d);
		return name ? [{ device: d, name }] : [];
	});
	const oldestFirst = [...named].sort((a, b) => Date.parse(a.device.last_seen || '') - Date.parse(b.device.last_seen || '') || 0);
	return new Map(oldestFirst.flatMap(({ device, name }) => (device.ips ?? []).map((ip) => [ip, name] as const)));
}
