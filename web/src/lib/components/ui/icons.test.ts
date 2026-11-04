import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render } from '@testing-library/svelte';
import { ICONS } from './icons';
import Icon from './Icon.svelte';

const DIR = resolve(process.cwd(), '../nettap-design-system/assets/Icons');
const files = readdirSync(DIR).filter((f) => f.endsWith('.svg'));

describe('icon set', () => {
	it('has exactly the icons in the design system', () => {
		expect(Object.keys(ICONS).sort()).toEqual(files.map((f) => f.replace(/\.svg$/, '')).sort());
	});

	it.each(files)('%s matches its source file', (file) => {
		const inner = readFileSync(resolve(DIR, file), 'utf8').match(/<svg[^>]*>([\s\S]*)<\/svg>/)![1].trim();
		expect(ICONS[file.replace(/\.svg$/, '') as keyof typeof ICONS]).toBe(inner);
	});
});

describe('Icon', () => {
	it('renders the paths as SVG, hidden from assistive tech by default', () => {
		const { container } = render(Icon, { name: 'home' });
		const svg = container.querySelector('svg')!;
		expect(svg.classList.contains('ic')).toBe(true);
		expect(svg.getAttribute('aria-hidden')).toBe('true');
		expect(svg.querySelector('path')?.namespaceURI).toBe('http://www.w3.org/2000/svg');
	});

	it('is a labelled image when given a label', () => {
		const { getByRole } = render(Icon, { name: 'alerts', label: 'Alerts' });
		expect(getByRole('img', { name: 'Alerts' })).toBeTruthy();
	});
});
