import { describe, it, expect } from 'vitest';
import { deviceIcon } from './device-icon';

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
