import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import { deviceIcon } from './device-icon';
import DeviceTile from './DeviceTile.svelte';
import { ICONS } from './icons';
import { DEVICE_ICONS } from '$api/devices-registry';

describe('deviceIcon', () => {
	it.each([
		['computer', 'laptop'],
		['phone', 'phone'],
		['iot', 'iot'],
		['infrastructure', 'infra'],
		['media', 'tv'],
		['nas', 'nas'],
		['gamepad', 'gamepad'],
		['Phone', 'phone'],
	])('maps %s to %s', (category, icon) => {
		expect(deviceIcon(category)).toBe(icon);
	});

	it.each(['unknown', '', null, undefined, 'toaster', 'constructor', '__proto__'])(
		'falls back to the generic devices icon for %s',
		(category) => {
			expect(deviceIcon(category)).toBe('devices');
		},
	);
});

// NET-200: an icon the owner picks shows as itself, through deviceIcon and through the tile
describe('owner-picked icons', () => {
	it.each([...DEVICE_ICONS])('maps %s to itself', (icon) => {
		expect(deviceIcon(icon)).toBe(icon);
	});

	it.each([...DEVICE_ICONS])('DeviceTile shows %s when it is the picked icon', (icon) => {
		const { container } = render(DeviceTile, { category: 'unknown', icon });
		const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
		svg.innerHTML = ICONS[icon];
		expect(container.querySelector('.tile svg')!.innerHTML).toBe(svg.innerHTML);
	});
});
