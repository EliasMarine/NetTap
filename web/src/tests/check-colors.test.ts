import { describe, it, expect } from 'vitest';
import { findColorLiterals } from '../../scripts/check-colors.mjs';

const find = (path: string, src: string) =>
	(findColorLiterals(path, src) as { line: number; match: string }[]).map((h) => h.match);

describe('colour gate', () => {
	it('flags hex, rgb/rgba, hsl/hsla and named colours in CSS', () => {
		expect(find('a.css', '.a { color: #fff; background: #ff7a1a; border-color: #ff7a1a80; }')).toEqual([
			'#fff',
			'#ff7a1a',
			'#ff7a1a80',
		]);
		expect(find('a.css', '.a { color: rgba(0, 0, 0, 0.5); fill: hsl(10 20% 30%); }')).toEqual([
			'rgba(',
			'hsl(',
		]);
		expect(find('a.css', '.a { color: white; background: black; }')).toEqual(['white', 'black']);
	});

	it('ignores white-space, tokens and comments, including commented-out OLD CODE', () => {
		const css = [
			'.a { white-space: nowrap; color: var(--text-1); }',
			'/* TOKENS START */ :root { --bg: #000000; } /* TOKENS END */',
			'/* was #ff4757 */',
			'/* OLD CODE START — why */',
			'/* .b { color: #123456; } */',
			'/* OLD CODE END */',
		].join('\n');
		expect(find('a.css', css)).toEqual([]);
	});

	it('still flags live code that sits between OLD CODE markers', () => {
		const css = ['/* OLD CODE START */', '.b { color: #123456; }', '/* OLD CODE END */'].join('\n');
		expect(find('a.css', css)).toEqual(['#123456']);
	});

	it('flags named colours inside inline style strings', () => {
		const svelte = '<span style="color: white">a</span><b style="background:black">b</b>';
		expect(find('a.svelte', svelte)).toEqual(['white', 'black']);
		expect(find('a.ts', 'const s = `color: black`;')).toEqual(['black']);
	});

	it('scans only quoted strings in TS', () => {
		const ts = [
			"const c = '#ff4757';",
			'const d = `rgba(0, 0, 0, ${a})`;',
			"const e = 'white';",
			'// const f = "#00d4ff";',
			'const url = "https://example.com/#abc";',
			'const n = items.length; // see #147',
		].join('\n');
		expect(find('a.ts', ts)).toEqual(['#ff4757', 'rgba(', 'white']);
	});

	it('exempts one line after an allow-next-line marker that gives a reason', () => {
		const ts = [
			'// colour-gate: allow-next-line email HTML cannot use CSS variables',
			"const a = '#f85149';",
			"const b = '#d29922';",
			'// colour-gate: allow-next-line',
			"const c = '#58a6ff';",
		].join('\n');
		expect(find('a.ts', ts)).toEqual(['#d29922', '#58a6ff']);
	});

	it('reports correct line numbers', () => {
		const hits = findColorLiterals('a.ts', "const a = 1;\n\nconst c = '#abcdef';") as {
			line: number;
		}[];
		expect(hits[0].line).toBe(3);
	});

	it('in Svelte, checks <style> as CSS and markup only inside quotes', () => {
		const svelte = [
			'<script lang="ts">',
			"\tconst palette = ['#00d4ff'];",
			'</script>',
			'{#each items as item}<p>PR #147 fixed it</p>{/each}',
			'<svg><rect fill="#ff0000" /></svg>',
			'<a href="#top">Top</a>',
			'<!-- <div style="color: #fff"></div> -->',
			'<style>',
			'\t.x { color: #000; white-space: pre; }',
			'</style>',
		].join('\n');
		expect(find('a.svelte', svelte)).toEqual(['#00d4ff', '#ff0000', '#000']);
	});
});
