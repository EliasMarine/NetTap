import { describe, it, expect, vi } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { stripIgnored } from '../../../scripts/check-colors.mjs';
import { loadFailed } from './load-failed';

describe('loadFailed', () => {
	it('says the section could not load', () => {
		expect(loadFailed('traffic categories')).toBe("Couldn't load traffic categories: the request failed.");
	});

	it('says older figures are still on screen when stale', () => {
		expect(loadFailed('traffic totals', true)).toBe("Couldn't refresh traffic totals; showing the last figures loaded.");
	});

	it("says when the kept figures loaded: the time today, the day and time before today (NET-348)", () => {
		const now = new Date(2026, 10, 20, 21, 5);
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(now);
		try {
			expect(loadFailed('traffic totals', true, new Date(2026, 10, 20, 20, 41, 30).getTime())).toBe(
				"Couldn't refresh traffic totals; showing figures from 20:41.",
			);
			expect(loadFailed('traffic totals', true, new Date(2026, 10, 19, 23, 58).getTime())).toBe(
				"Couldn't refresh traffic totals; showing figures from 19 Nov, 23:58.",
			);
			// a failure with nothing kept never names a time
			expect(loadFailed('traffic totals', false, now.getTime())).toBe("Couldn't load traffic totals: the request failed.");
		} finally {
			vi.useRealTimers();
		}
	});
});

// NET-192 PR 4: a stale note is the amber status notice everywhere, never a grey line or a red alert box.
describe('stale notes in markup', () => {
	// OLD CODE: const STALE = /\{loadFailed\([^)]*,\s*true\)\}|feedback\(loadFailed\(/; (NET-348: a stale note may pass when its figures loaded)
	const STALE = /\{loadFailed\([^)]*,\s*true(?:,[^)]*)?\)\}|feedback\(loadFailed\(/;
	const AMBER = /<(?:p|div) class="notice is-warn[^"]*" role="status"><Icon name="warn" \/>(?:<span>)?\{loadFailed\(/;

	function svelteFiles(dir: string): string[] {
		return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
			const path = join(dir, e.name);
			return e.isDirectory() ? svelteFiles(path) : e.name.endsWith('.svelte') ? [path] : [];
		});
	}

	it('every one is a .notice.is-warn with role="status" and the warn icon', () => {
		const src = join(process.cwd(), 'src');
		const hits = svelteFiles(src).flatMap((path) => {
			const lines = (stripIgnored(readFileSync(path, 'utf8')) as string).split('\n');
			return lines.flatMap((line, i) => (STALE.test(line) && !AMBER.test(line) ? [`${relative(src, path)}:${i + 1} ${line.trim()}`] : []));
		});
		expect(hits).toEqual([]);
	});

	it('flags the grey line and the red alert box', () => {
		const flagged = (line: string) => STALE.test(line) && !AMBER.test(line);
		expect(flagged(`<p class="note">{loadFailed('ports', true)}</p>`)).toBe(true);
		expect(flagged(`{@render feedback(loadFailed('the storage status', true), true)}`)).toBe(true);
		expect(flagged(`<p class="notice is-warn" role="status">{loadFailed('the capture files', true)}</p>`)).toBe(true);
		expect(flagged(`<p class="notice is-warn load-note" role="status"><Icon name="warn" /><span>{loadFailed('ports', true)}</span></p>`)).toBe(false);
		expect(flagged(`<p class="note">{loadFailed('ports', true, loadedAt.ports)}</p>`)).toBe(true);
	});
});
