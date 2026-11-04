import type { RegistryDevice } from '$api/devices-registry';

export interface TypeGroup {
	key: string;
	label: string;
	devices: RegistryDevice[];
}

/** The daemon's categories, in the order Home's device grid showed them (media included). */
const TYPES: { key: string; label: string }[] = [
	{ key: 'computer', label: 'Computers' },
	{ key: 'phone', label: 'Phones and tablets' },
	{ key: 'media', label: 'Media' },
	{ key: 'iot', label: 'IoT devices' },
	{ key: 'infrastructure', label: 'Infrastructure' },
	{ key: 'unknown', label: 'Unknown' },
];

/**
 * The By type view: device cards grouped by category, most recently seen first in each group.
 * Home's DeviceGrid dropped any category outside its list (media among them); here an
 * unlisted or empty category goes under Unknown, so every card shows.
 */
export function groupByType(devices: readonly RegistryDevice[]): TypeGroup[] {
	const known = new Set(TYPES.map((t) => t.key));
	const byType = new Map<string, RegistryDevice[]>();
	for (const device of devices) {
		const key = known.has(device.category) ? device.category : 'unknown';
		byType.set(key, [...(byType.get(key) ?? []), device]);
	}
	return TYPES.filter((t) => byType.has(t.key)).map((t) => ({
		...t,
		devices: [...(byType.get(t.key) ?? [])].sort((a, b) => Date.parse(b.last_seen) - Date.parse(a.last_seen)),
	}));
}
