import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import Sparkline from './Sparkline.svelte';

const VALUES = [3, 4, 2, 5, 7, 9, 12, 10, 6, 4];

describe('Sparkline', () => {
	it('is decorative by default: an accent line with ring dots at both ends', () => {
		const { container } = render(Sparkline, { props: { values: VALUES, width: 200 } });
		const svg = container.querySelector('svg')!;
		expect(svg.getAttribute('aria-hidden')).toBe('true');
		expect(svg.hasAttribute('role')).toBe(false);
		expect(container.querySelector('path.line.ln-spark')?.getAttribute('d')).toMatch(/^M/);
		const dots = [...container.querySelectorAll('circle.ring-dot')].map((d) => Number(d.getAttribute('cx')));
		expect(dots).toEqual([4, 196]);
		expect(container.querySelector('linearGradient.g-band')).toBeNull();
	});

	it('marks a window with the accent band and puts the dots at its ends', () => {
		const { container } = render(Sparkline, { props: { values: VALUES, band: [5, 8], width: 200 } });
		expect(container.querySelector('linearGradient.g-band .st-top')).not.toBeNull();
		const rect = container.querySelector('rect')!;
		expect(Number(rect.getAttribute('width'))).toBeGreaterThan(0);
		const dots = [...container.querySelectorAll('circle.ring-dot')].map((d) => Number(d.getAttribute('cx')));
		expect(dots[0]).toBeCloseTo(Number(rect.getAttribute('x')), 0);
		expect(dots).toHaveLength(2);
	});

	it('is an image with its label when given one', () => {
		const { getByRole } = render(Sparkline, { props: { values: VALUES, ariaLabel: 'Bandwidth, busiest 18:00–22:00' } });
		expect(getByRole('img').getAttribute('aria-label')).toBe('Bandwidth, busiest 18:00–22:00');
	});

	it('renders nothing for no values and no NaN for one, flat, zero or gapped values', () => {
		expect(render(Sparkline, { props: { values: [] } }).container.querySelector('svg')).toBeNull();
		for (const values of [[5], [2, 2, 2], [0, 0, 0], [1, Number.NaN, 3]]) {
			const { container, unmount } = render(Sparkline, { props: { values, band: [0, 2] } });
			expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
			unmount();
		}
	});
});
