import { describe, it, expect } from 'vitest';
import { compareSummary, defaultStarts, lengthMs, localInput, NOT_EXACT, periods, TOO_MANY_LISTED } from './device-compare';
import type { DeviceCompareResponse } from '$api/device-compare';
import { formatBytes } from '$lib/api/logs';

const HOUR = 3_600_000;
const NOW = Date.UTC(2026, 10, 13, 21, 7, 42, 500);
const MINUTE = Date.UTC(2026, 10, 13, 21, 7);

describe('the periods asked for', () => {
	it('writes datetime-local text in local time, to the minute', () => {
		expect(localInput(NOW)).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
		expect(new Date(localInput(NOW)).getTime()).toBe(MINUTE);
	});

	it('defaults to two back-to-back periods, the second ending this minute', () => {
		const { a, b } = defaultStarts(lengthMs('24h'), NOW);
		expect(new Date(a).getTime()).toBe(MINUTE - 48 * HOUR);
		expect(new Date(b).getTime()).toBe(MINUTE - 24 * HOUR);
	});

	it('knows its three lengths', () => {
		expect([lengthMs('1h'), lengthMs('24h'), lengthMs('7d')]).toEqual([HOUR, 24 * HOUR, 168 * HOUR]);
	});

	it('makes each period one length long from its start', () => {
		const { a, b } = defaultStarts(HOUR, NOW);
		expect(periods('192.168.1.30', a, b, HOUR)).toEqual({
			ip: '192.168.1.30',
			a_from: new Date(MINUTE - 2 * HOUR).toISOString(),
			a_to: new Date(MINUTE - HOUR).toISOString(),
			b_from: new Date(MINUTE - HOUR).toISOString(),
			b_to: new Date(MINUTE).toISOString(),
		});
	});

	it.each([
		['', '2026-11-13T20:00'],
		['2026-11-13T19:00', ''],
		['not a time', '2026-11-13T20:00'],
	])('has no periods without two readable starts (%s, %s)', (a, b) => {
		expect(periods('192.168.1.30', a, b, HOUR)).toBeNull();
	});
});

const period = (total_bytes: number) => ({ from: 'a', to: 'b', total_bytes, destinations: 3, list_complete: true, buckets_exact: true });
const list = (total: number) => ({ total, items: [] });
const reply = (fields: Partial<DeviceCompareResponse>): DeviceCompareResponse => ({
	ip: '192.168.1.30',
	a: period(1_200_000_000),
	b: period(3_400_000_000),
	exact: true,
	complete: true,
	new: list(4),
	gone: list(2),
	changed: { ...list(0), partial: false },
	...fields,
});

describe('compareSummary', () => {
	it('says what was new and what was not seen again, then the bytes', () => {
		expect(compareSummary(reply({}), formatBytes)).toBe(
			'In the second period this device started connections to 4 new destinations and none to 2 earlier ones. Bytes went from 1.2 GB to 3.4 GB.',
		);
	});

	it('counts one in the singular and none in words', () => {
		expect(compareSummary(reply({ new: list(1), gone: list(1) }), formatBytes)).toContain('to 1 new destination and none to 1 earlier one.');
		expect(compareSummary(reply({ new: list(0), gone: list(0) }), formatBytes)).toBe(
			'In the second period this device started connections to no new destinations. Bytes went from 1.2 GB to 3.4 GB.',
		);
		expect(compareSummary(reply({ new: list(2_500) }), formatBytes)).toContain('to 2,500 new destinations');
	});

	it('says why new and gone are missing when a list was incomplete', () => {
		const r = reply({ complete: false, new: null, gone: null, changed: { ...list(3), partial: true } });
		expect(compareSummary(r, formatBytes)).toBe(`${TOO_MANY_LISTED} Bytes went from 1.2 GB to 3.4 GB.`);
	});

	it('gives only the totals when the lists were estimates', () => {
		const r = reply({ exact: false, complete: false, new: null, gone: null, changed: null });
		expect(compareSummary(r, formatBytes)).toBe(`${NOT_EXACT} Bytes went from 1.2 GB to 3.4 GB.`);
	});
});
