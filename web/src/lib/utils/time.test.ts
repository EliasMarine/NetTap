import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { stripIgnored } from '../../../scripts/check-colors.mjs';
import { formatTime } from './time';

describe('formatTime', () => {
	const t = new Date(2026, 10, 6, 22, 37, 23);

	it('writes en-GB, 24-hour, in each style', () => {
		expect(formatTime(t, 'short')).toBe('6 Nov, 22:37');
		expect(formatTime(t, 'long')).toBe('6 Nov 2026, 22:37:23');
		expect(formatTime(t)).toBe('6 Nov 2026, 22:37:23');
		expect(formatTime(t, 'clock')).toBe('22:37:23');
		expect(formatTime(t, 'date')).toBe('6 Nov 2026');
		expect(formatTime(new Date(2026, 10, 6, 0, 5), 'short')).toBe('6 Nov, 00:05');
	});

	it('takes ISO strings and epoch milliseconds', () => {
		expect(formatTime(t.toISOString(), 'short')).toBe('6 Nov, 22:37');
		expect(formatTime(t.getTime(), 'clock')).toBe('22:37:23');
	});

	it('says "—" for no time and keeps a value that is not a date', () => {
		expect(formatTime(null)).toBe('—');
		expect(formatTime(undefined)).toBe('—');
		expect(formatTime('')).toBe('—');
		expect(formatTime('not a date')).toBe('not a date');
	});
});

// A call with no locale prints in the browser's: "07:00 PM", "11/6/2026", "1,234" or "1.234".
const NO_LOCALE = /\.toLocale(?:Date|Time)?String\(\s*(?:\)|undefined\b|\[\s*\])|new\s+Intl\.(?:DateTimeFormat|NumberFormat)\(\s*(?:\)|undefined\b|\[\s*\])/g;

function sourceFiles(dir: string): string[] {
	return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
		const path = join(dir, e.name);
		if (e.isDirectory()) return sourceFiles(path);
		return /\.(ts|js|svelte)$/.test(e.name) && !/\.(test|spec)\.(ts|js)$/.test(e.name) ? [path] : [];
	});
}

describe('no-locale formatting', () => {
	it('no source file formats a date or number in the browser locale', () => {
		const src = join(process.cwd(), 'src');
		const hits = sourceFiles(src).flatMap((path) => {
			const code = stripIgnored(readFileSync(path, 'utf8')) as string;
			return [...code.matchAll(NO_LOCALE)].map((m) => {
				const line = code.slice(0, m.index).split('\n').length;
				return `${relative(src, path)}:${line} ${m[0]} — use formatTime (utils/time.ts), chartTime or fmt (utils/drilldown.ts)`;
			});
		});
		expect(hits).toEqual([]);
	});

	it('catches each no-locale form and skips comments', () => {
		const find = (code: string) => [...(stripIgnored(code) as string).matchAll(NO_LOCALE)].length;
		expect(find('d.toLocaleString()')).toBe(1);
		expect(find('n.toLocaleString( )')).toBe(1);
		expect(find("d.toLocaleTimeString(undefined, { hour: '2-digit' })")).toBe(1);
		expect(find("d.toLocaleDateString([], { month: 'short' })")).toBe(1);
		expect(find("d.toLocaleString('en-GB', { month: 'short' })")).toBe(0);
		expect(find('new Intl.NumberFormat()')).toBe(1);
		expect(find("new Intl.DateTimeFormat(undefined, { hour: '2-digit' })")).toBe(1);
		expect(find("new Intl.NumberFormat('en-GB')")).toBe(0);
		// a time-zone lookup, not formatting (lib/api/bandwidth.ts)
		expect(find('Intl.DateTimeFormat().resolvedOptions().timeZone')).toBe(0);
		expect(find('// d.toLocaleString()')).toBe(0);
		expect(find('<!-- {d.toLocaleString()} -->')).toBe(0);
	});
});
