import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import AreaChart, { type AreaSeries } from './AreaChart.svelte';

const DOWN = [0.5, 0.35, 0.25, 0.25, 0.25, 0.35, 0.75, 1.35, 1.6, 1.45, 1.25, 1.35, 1.5, 1.45, 1.35, 1.6, 2, 2.6, 3.2, 3.7, 4.3, 4.7, 3.55, 1.7];
const UP = DOWN.map((v) => v / 10);
const hour = (i: number) => `${String(i).padStart(2, '0')}:00`;
const toSeries = (key: string, colour: 1 | 2, values: number[]): AreaSeries => ({
	key,
	label: key,
	colour,
	points: values.map((v, i) => ({ t: i, v })),
});

function draw(series: AreaSeries[], extra: Record<string, unknown> = {}) {
	return render(AreaChart, {
		props: {
			series,
			formatX: (t: number | string) => hour(Number(t)),
			formatY: (v: number) => (v ? `${v} GB` : '0'),
			formatTip: (i: number) => `${hour(i)} · ${series[0].points[i]?.v} GB`,
			ariaLabel: 'Bandwidth per hour. Busiest hour 21:00, with 4.7 GB downloaded.',
			...extra,
		},
	});
}

const noNaN = (container: HTMLElement) => expect(container.innerHTML).not.toMatch(/NaN|Infinity/);

function hover(svg: SVGSVGElement, clientX: number) {
	svg.getBoundingClientRect = () => ({ left: 0, width: 640, top: 0, height: 220, right: 640, bottom: 220, x: 0, y: 0, toJSON() {} });
	svg.dispatchEvent(new MouseEvent('pointermove', { clientX, bubbles: true }));
}

describe('AreaChart', () => {
	it('draws the design-system structure with a headline label', () => {
		const { container, getByRole } = draw([toSeries('down', 1, DOWN), toSeries('up', 2, UP)], { highlightIndex: 21 });
		expect(getByRole('img').getAttribute('aria-label')).toBe('Bandwidth per hour. Busiest hour 21:00, with 4.7 GB downloaded.');
		expect(container.querySelectorAll('linearGradient.g-1 .st-top, linearGradient.g-2 .st-bot')).toHaveLength(2);
		expect(container.querySelector('.line.ln-1')).not.toBeNull();
		expect(container.querySelector('.line.ln-2')).not.toBeNull();
		// 0–5 GB on round steps: the baseline solid, every line above it dashed
		const grid = [...container.querySelectorAll('line.gl')];
		expect(grid).toHaveLength(6);
		expect(grid[0].classList.contains('dash')).toBe(false);
		expect(grid.slice(1).every((g) => g.classList.contains('dash'))).toBe(true);
		const yLabels = [...container.querySelectorAll('text.ax[text-anchor="end"]')].map((t) => t.textContent);
		expect(yLabels).toEqual(['0', '1 GB', '2 GB', '3 GB', '4 GB', '5 GB']);
		noNaN(container);
	});

	it('marks the headline point with a band, ringed dots and the pill tooltip', () => {
		const { container } = draw([toSeries('down', 1, DOWN), toSeries('up', 2, UP)], { highlightIndex: 21 });
		expect(container.querySelector('rect.band')).not.toBeNull();
		expect(container.querySelectorAll('circle.dot')).toHaveLength(2);
		expect(container.querySelector('.tip-tx')?.textContent).toBe('21:00 · 4.7 GB');
		expect(container.querySelector('.guide')).toBeNull();
	});

	it('thins the x labels so they never overlap', () => {
		const { container } = draw([toSeries('down', 1, DOWN)]);
		const xs = [...container.querySelectorAll('text.ax[text-anchor="middle"]')].map((t) => Number(t.getAttribute('x')));
		expect(xs.length).toBeLessThan(24);
		expect(xs.length).toBeGreaterThan(1);
		xs.slice(1).forEach((x, i) => expect(x - xs[i]).toBeGreaterThanOrEqual(64));
	});

	it('moves the tooltip and a dashed guide with the pointer, and restores the headline on leave', async () => {
		const { container, getByRole } = draw([toSeries('down', 1, DOWN)], { highlightIndex: 21 });
		const svg = getByRole('img') as unknown as SVGSVGElement;
		hover(svg, 50); // the left edge of the plot: hour 0
		await tick();
		expect(container.querySelector('.guide')).not.toBeNull();
		expect(container.querySelector('.tip-tx')?.textContent).toBe('00:00 · 0.5 GB');
		expect(container.querySelector('rect.band')).not.toBeNull();
		svg.dispatchEvent(new MouseEvent('pointerleave'));
		await tick();
		expect(container.querySelector('.guide')).toBeNull();
		expect(container.querySelector('.tip-tx')?.textContent).toBe('21:00 · 4.7 GB');
	});

	it('is not focusable: hover is a mouse enhancement only', () => {
		const { getByRole } = draw([toSeries('down', 1, DOWN)]);
		expect(getByRole('img').hasAttribute('tabindex')).toBe(false);
	});

	it('renders nothing for no series or no points', () => {
		expect(draw([]).container.querySelector('svg')).toBeNull();
		expect(draw([toSeries('down', 1, [])]).container.querySelector('svg')).toBeNull();
	});

	it('draws one point, a constant series, all zeros and gaps without NaN', () => {
		for (const values of [[3], [2, 2, 2, 2], [0, 0, 0], [1, Number.NaN, 3]]) {
			const { container, unmount } = draw([toSeries('down', 1, values)], { highlightIndex: 0 });
			expect(container.querySelector('svg')).not.toBeNull();
			noNaN(container);
			unmount();
		}
	});

	it('ignores a highlight index outside the data', () => {
		const { container } = draw([toSeries('down', 1, DOWN)], { highlightIndex: 99 });
		expect(container.querySelector('rect.band')).toBeNull();
		expect(container.querySelector('.tip-bg')).toBeNull();
	});
});
