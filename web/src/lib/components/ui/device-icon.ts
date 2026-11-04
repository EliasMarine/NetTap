import type { IconName } from './icons';

/**
 * Device category to device-type icon (PLAN.md §4.1: mapped from the existing `category`
 * field, anything unknown gets the generic `devices` icon).
 * The daemon's categories are computer, phone, iot, infrastructure, media and unknown
 * (daemon/api/devices.py `_device_category`, services/device_registry.py). The system's
 * device-type names (tv, nas, gamepad, …) are accepted too, for callers that know more.
 */
const BY_CATEGORY: Record<string, IconName> = {
	computer: 'laptop',
	phone: 'phone',
	iot: 'iot',
	infrastructure: 'infra',
	media: 'tv',
	tv: 'tv',
	laptop: 'laptop',
	nas: 'nas',
	gamepad: 'gamepad',
	tablet: 'tablet',
	camera: 'camera',
	speaker: 'speaker',
	printer: 'printer',
};

export function deviceIcon(category: string | null | undefined): IconName {
	const key = (category ?? '').toLowerCase();
	return Object.hasOwn(BY_CATEGORY, key) ? BY_CATEGORY[key] : 'devices';
}
