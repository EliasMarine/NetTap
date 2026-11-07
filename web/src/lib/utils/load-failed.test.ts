import { describe, it, expect } from 'vitest';
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
});

// NET-192 PR 4: a stale note is the amber status notice everywhere, never a grey line or a red alert box.
describe('stale notes in markup', () => {
	const STALE = /\{loadFailed\([^)]*,\s*true\)\}|feedback\(loadFailed\(/;
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
	});
});
