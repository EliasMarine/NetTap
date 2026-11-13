import { describe, it, expect, vi, beforeEach } from 'vitest';
import { goto } from '$app/navigation';
import { bucketWords, narrowTo, pickedLine, withoutWindow } from './narrow-page';
import { toTimeChart as timeChart } from './chart-pick';
import type { TimeChart } from './drilldown';

vi.mock('$app/navigation', () => ({ goto: vi.fn(async () => {}) }));

const WIN = { from: '2026-11-13T10:00:00.000Z', to: '2026-11-13T10:04:59.999Z' };
const chart = (values: number[]): TimeChart => ({ from: WIN.from, to: WIN.to, times: values.map((_, i) => `2026-11-13T10:0${i}:00.000Z`), values, step: 60_000 });
const ALERTS = { lead: 'This window now shows', one: 'alert', many: 'alerts' };

describe('timeChart (NET-249)', () => {
	it('holds a reply whose bucket and window it knows', () => {
		expect(timeChart({ ...WIN, interval: '1m' }, ['a'], [1])).toEqual({ ...WIN, times: ['a'], values: [1], step: 60_000 });
	});

	it('leaves a chart with an unknown bucket or no window as a picture', () => {
		expect(timeChart({ ...WIN, interval: '10m' }, [], [])).toBeNull();
		expect(timeChart({ ...WIN }, [], [])).toBeNull();
		expect(timeChart({ from: '', to: '', interval: '5m' }, [], [])).toBeNull();
	});
});

describe('narrowTo (NET-249)', () => {
	beforeEach(() => vi.mocked(goto).mockClear());
	const target = () => new URL(String(vi.mocked(goto).mock.calls[0][0]), 'http://x');

	it('keeps the page and its other parameters, sets the window and the figure, and drops an older figure', async () => {
		await narrowTo(new URL('http://x/dns?domain=a.example&bytes=9'), null, WIN, '24h', 'count', 12);
		const url = target();
		expect(url.pathname).toBe('/dns');
		expect(Object.fromEntries(url.searchParams)).toEqual({ domain: 'a.example', from: WIN.from, to: WIN.to, range: '24h', count: '12' });
		expect(vi.mocked(goto).mock.calls[0][1]).toMatchObject({ replaceState: false });
	});

	it("keeps the URL's own range, and replaces the history entry for the window already on screen", async () => {
		await narrowTo(new URL(`http://x/dns?from=${WIN.from}&to=${WIN.to}&range=7d&count=3`), WIN, WIN, '24h', 'count', 4);
		expect(target().searchParams.get('range')).toBe('7d');
		expect(target().searchParams.get('count')).toBe('4');
		expect(vi.mocked(goto).mock.calls[0][1]).toMatchObject({ replaceState: true });
	});

	it('replaces a range that is not one of ours', async () => {
		await narrowTo(new URL('http://x/dns?range=15m'), null, WIN, '6h', 'bytes', 1);
		expect(target().searchParams.get('range')).toBe('6h');
	});
});

describe('withoutWindow (NET-249)', () => {
	it('drops the window, its range and the picked figure, and keeps the rest', () => {
		expect(withoutWindow(new URL(`http://x/dns?domain=a&from=${WIN.from}&to=${WIN.to}&range=7d&count=3&bytes=4`))).toBe('/dns?domain=a');
		expect(withoutWindow(new URL(`http://x/devices/10.0.0.2?from=${WIN.from}&to=${WIN.to}`))).toBe('/devices/10.0.0.2');
	});
});

describe('pickedLine, the shared receiver (NET-249)', () => {
	it('says nothing when the narrowed chart totals the figure picked', () => {
		expect(pickedLine(6, chart([1, 2, 3]), ALERTS)).toBeNull();
		expect(pickedLine(1500, chart([1000, 500]), 'bytes')).toBeNull();
	});

	it('states the difference in records, and why', () => {
		expect(pickedLine(5, chart([1, 2, 3]), ALERTS)).toBe(
			'You clicked 5. This window now shows 6 alerts (1 more). Records can be logged after a figure is counted (a connection is logged when it ends), and old records are deleted to free disk space.',
		);
	});

	it('states the difference in bytes', () => {
		expect(pickedLine(3_000_000, chart([1_000_000, 1_000_000]), 'bytes')).toMatch(/^You clicked 3\.0 MB\. This window now shows 2\.0 MB \(1\.0 MB less\)\. Records can be logged/);
	});

	it('has nothing to compare without a figure or a chart reply for the window (loading, failed or superseded)', () => {
		expect(pickedLine(null, chart([1]), ALERTS)).toBeNull();
		expect(pickedLine(5, null, ALERTS)).toBeNull();
	});
});

describe('bucketWords (NET-249)', () => {
	it("names the bucket the reply echoes, else the one asked for, and an echo off the table as written", () => {
		expect(bucketWords('1m', '5 minutes')).toBe('minute');
		expect(bucketWords('3h', 'hour')).toBe('3 hours');
		expect(bucketWords(undefined, '5 minutes')).toBe('5 minutes');
		expect(bucketWords(null, 'hour')).toBe('hour');
		expect(bucketWords('10m', 'minute')).toBe('10m');
	});
});
