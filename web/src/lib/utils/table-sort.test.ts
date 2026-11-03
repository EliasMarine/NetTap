import { describe, expect, it } from 'vitest';
import { TableSort, byteSize, compareValues, severityRank, sortRows } from './table-sort.svelte';

describe('compareValues', () => {
	it('orders IP addresses by number, not by text', () => {
		// plain localeCompare put 10.10.0.235 before 10.10.0.26 on the G11's Bandwidth page
		const ips = ['10.10.0.26', '192.168.1.10', '10.10.0.235', '192.168.1.9', '10.10.0.108'];
		expect([...ips].sort(compareValues)).toEqual([
			'10.10.0.26',
			'10.10.0.108',
			'10.10.0.235',
			'192.168.1.9',
			'192.168.1.10',
		]);
	});

	it('orders decimal text by value', () => {
		// tshark gives frame.time_relative as text; the collator alone put 0.000123 after 0.01
		expect(['0.01', '0.000123', '10', '9.5'].sort(compareValues)).toEqual(['0.000123', '0.01', '9.5', '10']);
		expect(compareValues('74', 66)).toBeGreaterThan(0);
	});

	it('orders numbers by value and text without regard to case', () => {
		expect([10, 9, 100].sort(compareValues)).toEqual([9, 10, 100]);
		expect(['beta', 'Alpha', 'gamma'].sort(compareValues)).toEqual(['Alpha', 'beta', 'gamma']);
		expect(['port 80', 'port 8', 'port 443'].sort(compareValues)).toEqual([
			'port 8',
			'port 80',
			'port 443',
		]);
	});
});

describe('sortRows', () => {
	const rows = [{ v: 2 }, { v: null }, { v: 10 }, { v: undefined }, { v: 1 }];

	it('sorts both ways and keeps blanks last in both', () => {
		expect(sortRows(rows, (r) => r.v, 'asc').map((r) => r.v)).toEqual([1, 2, 10, null, undefined]);
		expect(sortRows(rows, (r) => r.v, 'desc').map((r) => r.v)).toEqual([10, 2, 1, null, undefined]);
	});

	it('returns a copy and leaves the input alone', () => {
		const input = [{ v: 2 }, { v: 1 }];
		const out = sortRows(input, (r) => r.v, 'asc');
		expect(out).not.toBe(input);
		expect(input.map((r) => r.v)).toEqual([2, 1]);
	});
});

describe('TableSort', () => {
	type Row = { ip: string; bytes: number };
	const rows: Row[] = [
		{ ip: '192.168.1.9', bytes: 5 },
		{ ip: '192.168.1.10', bytes: 50 },
		{ ip: '192.168.1.2', bytes: 20 },
	];
	const value = (row: Row, key: 'ip' | 'bytes') => row[key];

	it('starts on the given column and flips direction on the same column', () => {
		const sort = new TableSort<'ip' | 'bytes'>('bytes');
		expect(sort.apply(rows, value).map((r) => r.bytes)).toEqual([50, 20, 5]);
		expect(sort.arrow('bytes')).toBe('↓');
		expect(sort.arrow('ip')).toBe('');
		sort.toggle('bytes');
		expect(sort.apply(rows, value).map((r) => r.bytes)).toEqual([5, 20, 50]);
		expect(sort.arrow('bytes')).toBe('↑');
	});

	it('a new column starts descending', () => {
		const sort = new TableSort<'ip' | 'bytes'>('bytes', 'asc');
		sort.toggle('ip');
		expect(sort.key).toBe('ip');
		expect(sort.apply(rows, value).map((r) => r.ip)).toEqual([
			'192.168.1.10',
			'192.168.1.9',
			'192.168.1.2',
		]);
	});
});

describe('severityRank', () => {
	it('ranks Suricata 1 (high) worst and no severity lowest', () => {
		expect([3, 1, undefined, 2].map(severityRank)).toEqual([2, 4, 0, 3]);
	});
});

describe('byteSize', () => {
	it("reads OpenSearch's 1024-based sizes", () => {
		// as text, "100mb" sorted above "1.2gb" on the Infrastructure page
		expect(byteSize('100mb')! < byteSize('1.2gb')!).toBe(true);
		expect(byteSize('512kb')).toBe(512 * 1024);
		expect(byteSize('208b')).toBe(208);
		expect(byteSize('')).toBeNull();
		expect(byteSize(undefined)).toBeNull();
	});
});
