import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// PLAN.md §5.4: every text-bearing token is WCAG AA (4.5:1) on every surface, in every variant.
// tokens.css is nettap-design-system/tokens.css verbatim: one Ember block, then Graphite, then Spectrum.
const css = readFileSync(resolve(process.cwd(), 'src/lib/styles/tokens.css'), 'utf8');
const block = css.slice(css.indexOf(':root, [data-theme="ember"]'), css.lastIndexOf('\n:root {'));
const [emberCss, graphiteCss, spectrumCss] = block.split(/\n(?=\[data-theme)/);

const parse = (text: string) =>
	Object.fromEntries([...text.matchAll(/(--[\w-]+):\s*(#[0-9a-f]{6})\b/gi)].map((m) => [m[1], m[2]]));

const ember = parse(emberCss);
const VARIANTS: Record<string, Record<string, string>> = {
	ember,
	graphite: { ...ember, ...parse(graphiteCss) },
	spectrum: { ...ember, ...parse(spectrumCss) },
};

function luminance(hex: string): number {
	const [r, g, b] = [1, 3, 5]
		.map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
		.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
	return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
	const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
	return (hi + 0.05) / (lo + 0.05);
}

const TEXT = ['--text-1', '--text-2', '--text-3', '--accent', '--accent-strong'];
const SEVERITY = ['--sev-critical', '--sev-high', '--sev-medium', '--sev-low', '--sev-info', '--ok'];
const SURFACES = ['--bg', '--surface-1', '--surface-2', '--surface-3'];

describe.each(Object.entries(VARIANTS))('%s tokens', (_name, tokens) => {
	it('defines the background as pure black', () => {
		expect(tokens['--bg']).toBe('#000000');
	});

	it.each([...TEXT, ...SEVERITY])('%s is AA on every surface', (fg) => {
		for (const bg of SURFACES) {
			expect(contrast(tokens[fg], tokens[bg]), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
		}
	});

	it('text on the accent is AA', () => {
		expect(contrast(tokens['--on-accent'], tokens['--accent'])).toBeGreaterThanOrEqual(4.5);
	});

	it('text on the light selected pill is AA', () => {
		expect(contrast(tokens['--on-light'], tokens['--pill-active-bg'])).toBeGreaterThanOrEqual(4.5);
	});
});
