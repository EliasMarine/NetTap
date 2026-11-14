import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
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

/** A pointer event as a browser sends it; jsdom has no PointerEvent, so isPrimary and pointerId are added. */
function pointerEvent(type: string, clientX: number, { isPrimary = true, pointerId = 1, button = 0 } = {}) {
	const e = new MouseEvent(type, { clientX, bubbles: true, button });
	Object.defineProperties(e, { isPrimary: { value: isPrimary }, pointerId: { value: pointerId } });
	return e;
}

function hover(svg: SVGSVGElement, clientX: number) {
	svg.getBoundingClientRect = () => ({ left: 0, width: 640, top: 0, height: 220, right: 640, bottom: 220, x: 0, y: 0, toJSON() {} });
	// OLD CODE: svg.dispatchEvent(new MouseEvent('pointermove', { clientX, bubbles: true })); (NET-249: the chart reads isPrimary)
	svg.dispatchEvent(pointerEvent('pointermove', clientX));
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

	// NET-270: a picked few minutes has three points; the band was 1.6 slots wide, centred on the end point
	it('keeps the headline band a narrow column inside the plot when there are few points', () => {
		const box = (c: HTMLElement) => {
			const r = c.querySelector('rect.band')!;
			return { x: Number(r.getAttribute('x')), w: Number(r.getAttribute('width')) };
		};
		// jsdom measures nothing, so the chart is 640 wide: the plot runs from 50 to 628
		const [left, right] = [50, 628];
		for (const at of [0, 1, 2]) {
			const { container, unmount } = draw([toSeries('down', 1, [3.1, 0.05, 0])], { highlightIndex: at });
			const { x, w } = box(container);
			expect(x).toBeGreaterThanOrEqual(left);
			expect(x + w).toBeLessThanOrEqual(right + 0.1);
			expect(w).toBeLessThanOrEqual((right - left) / 10 + 0.1);
			expect(w).toBeGreaterThan(0);
			unmount();
		}
		// 24 points: the design's width, 1.6 slots, unchanged
		const { container } = draw([toSeries('down', 1, DOWN)], { highlightIndex: 21 });
		expect(box(container).w).toBeCloseTo(((right - left) / 23) * 1.6, 0);
	});

	it('thins the x labels so they never overlap', () => {
		const { container } = draw([toSeries('down', 1, DOWN)]);
		const xs = [...container.querySelectorAll('text.ax[text-anchor="middle"]')].map((t) => Number(t.getAttribute('x')));
		expect(xs.length).toBeLessThan(24);
		expect(xs.length).toBeGreaterThan(1);
		xs.slice(1).forEach((x, i) => expect(x - xs[i]).toBeGreaterThanOrEqual(64));
	});

	it('spaces long date labels further apart, so "Nov 4, 04:00 PM" never runs into the next one', () => {
		const { container } = draw([toSeries('down', 1, DOWN)], { formatX: (t: number | string) => `Nov 4, ${hour(Number(t))} PM` });
		const xs = [...container.querySelectorAll('text.ax[text-anchor="middle"]')].map((t) => Number(t.getAttribute('x')));
		expect(xs.length).toBeGreaterThan(1);
		// 15 characters at 6.2 px each, plus a 16 px gap
		xs.slice(1).forEach((x, i) => expect(x - xs[i]).toBeGreaterThanOrEqual(15 * 6.2 + 16));
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

	// NET-205: the live chart has missing ticks; `gaps` breaks the line there instead of bridging it
	describe('gaps', () => {
		const NaN_ = Number.NaN;
		const paths = (container: HTMLElement) => {
			const line = container.querySelector('.line.ln-1')!.getAttribute('d') ?? '';
			const area = container.querySelector('path[fill]')!.getAttribute('d') ?? '';
			return { line, area, moves: (line.match(/M/g) ?? []).length, closes: (area.match(/Z/g) ?? []).length };
		};

		it('is off by default: a missing point is bridged by one line, as before', () => {
			const { container } = draw([toSeries('down', 1, [1, 2, NaN_, 3, 4])]);
			expect(paths(container)).toMatchObject({ moves: 1, closes: 1 });
		});

		it('splits the line and the fill in two at an interior missing point', () => {
			const { container } = draw([toSeries('down', 1, [1, 2, NaN_, 3, 4])], { gaps: true });
			expect(paths(container)).toMatchObject({ moves: 2, closes: 2 });
			noNaN(container);
		});

		it('leaves a long outage empty: two runs, nothing drawn across it', () => {
			const values = [1, 2, ...Array(100).fill(NaN_), 3, 4];
			const { container } = draw([toSeries('down', 1, values)], { gaps: true });
			const { line, moves } = paths(container);
			expect(moves).toBe(2);
			// the second run starts at the 103rd point's x, not straight after the second
			const starts = [...line.matchAll(/M([\d.]+),/g)].map((m) => Number(m[1]));
			expect(starts[1] - starts[0]).toBeGreaterThan(100 * ((640 - 62) / 103) - 1);
		});

		it('starts after leading padding, with one run', () => {
			const values = [...Array(148).fill(NaN_), 5, 6];
			const { container } = draw([toSeries('down', 1, values)], { gaps: true });
			const { line, moves } = paths(container);
			expect(moves).toBe(1);
			expect(Number(line.match(/^M([\d.]+),/)![1])).toBeGreaterThan(600);
			noNaN(container);
		});

		it('draws a lone point between two gaps as a dot, with no fill', () => {
			const { container } = draw([toSeries('down', 1, [1, NaN_, 2, NaN_, 3])], { gaps: true });
			const { line, moves, closes } = paths(container);
			expect(moves).toBe(3);
			expect((line.match(/h0/g) ?? []).length).toBe(3);
			expect(closes).toBe(0);
			noNaN(container);
		});

		it('draws the same paths either way when nothing is missing', () => {
			const off = paths(draw([toSeries('down', 1, DOWN)]).container);
			const on = paths(draw([toSeries('down', 1, DOWN)], { gaps: true }).container);
			expect(on.line).toBe(off.line);
			expect(on.area).toBe(off.area);
		});

		it('draws axes but no line when every point is missing', () => {
			const { container } = draw([toSeries('down', 1, Array(150).fill(NaN_))], { gaps: true });
			expect(container.querySelector('svg')).not.toBeNull();
			expect(paths(container).line).toBe('');
			noNaN(container);
		});
	});

	// NET-249: with onpick, a click, a drag or the keyboard picks points; without it nothing changes
	describe('picking', () => {
		// 640 px wide, plot from 50 to 628 px: 24 points 578 / 23 px apart
		const SLOT = 578 / 23;
		const at = (i: number) => 50 + i * SLOT;
		const rect = { left: 0, width: 640, top: 0, height: 220, right: 640, bottom: 220, x: 0, y: 0, toJSON() {} };

		function setup(extra: Record<string, unknown> = {}) {
			const onpick = vi.fn();
			const view = draw([toSeries('down', 1, DOWN)], { onpick, ...extra });
			const svg = view.container.querySelector('svg')!;
			svg.getBoundingClientRect = () => rect;
			const group = view.getByRole('group');
			const pointer = (type: string, clientX: number, extra = {}) => svg.dispatchEvent(pointerEvent(type, clientX, extra));
			const key = (k: string, shiftKey = false, repeat = false) => fireEvent.keyDown(group, { key: k, shiftKey, repeat });
			const live = () => view.container.querySelector('[aria-live="polite"]')!.textContent;
			return { ...view, onpick, svg, group, pointer, key, live };
		}

		it('without onpick it is a picture: role img, not focusable, no group', () => {
			const { container, getByRole, queryByRole } = draw([toSeries('down', 1, DOWN)]);
			expect(getByRole('img').hasAttribute('tabindex')).toBe(false);
			expect(queryByRole('group')).toBeNull();
			expect(container.querySelector('[tabindex]')).toBeNull();
			expect(container.querySelector('[aria-live]')).toBeNull();
		});

		it('with onpick it is one focusable group that says how to use it', () => {
			const { group, queryByRole } = setup();
			expect(group.getAttribute('tabindex')).toBe('0');
			expect(group.getAttribute('aria-label')).toBe(
				'Bandwidth per hour. Busiest hour 21:00, with 4.7 GB downloaded. Use the left and right arrow keys to choose a point, Shift with an arrow key to choose a range, and Enter to open it.',
			);
			// the group carries the headline, so the drawing is hidden from screen readers
			expect(queryByRole('img')).toBeNull();
		});

		it('a click picks that one point', async () => {
			const { pointer, onpick } = setup();
			pointer('pointerdown', at(5));
			pointer('pointerup', at(5));
			expect(onpick).toHaveBeenCalledExactlyOnceWith(5, 5);
		});

		it('a drag picks the range, in either direction, and draws it as a band', async () => {
			const { pointer, onpick, container } = setup();
			pointer('pointerdown', at(3));
			pointer('pointermove', at(8));
			await tick();
			expect(container.querySelector('rect.band.pick')).not.toBeNull();
			pointer('pointerup', at(8));
			pointer('pointerdown', at(8));
			pointer('pointerup', at(3));
			expect(onpick.mock.calls).toEqual([
				[3, 8],
				[3, 8],
			]);
			await tick();
			expect(container.querySelector('rect.band.pick')).toBeNull();
		});

		it('a movement under 4 px is a click, even across the line between two points', () => {
			const { pointer, onpick } = setup();
			const edge = 50 + 5.5 * SLOT - 1; // still point 5; 3 px on is point 6
			pointer('pointerdown', edge);
			pointer('pointerup', edge + 3);
			expect(onpick).toHaveBeenCalledExactlyOnceWith(5, 5);
		});

		it('Escape during a drag cancels it', async () => {
			const { pointer, key, onpick } = setup();
			pointer('pointerdown', at(3));
			pointer('pointermove', at(8));
			await key('Escape');
			pointer('pointerup', at(8));
			expect(onpick).not.toHaveBeenCalled();
		});

		it('a cancelled pointer (the page scrolled instead) picks nothing', () => {
			const { pointer, onpick } = setup();
			pointer('pointerdown', at(3));
			pointer('pointermove', at(8));
			pointer('pointercancel', at(8));
			pointer('pointerup', at(8));
			expect(onpick).not.toHaveBeenCalled();
		});

		it('ignores a right button', () => {
			const { pointer, onpick } = setup();
			pointer('pointerdown', at(3), { button: 2 });
			pointer('pointerup', at(3), { button: 2 });
			expect(onpick).not.toHaveBeenCalled();
		});

		it('a second finger neither starts, moves nor ends the drag the first one started', () => {
			const { pointer, onpick } = setup();
			pointer('pointerdown', at(9), { isPrimary: false, pointerId: 2 });
			pointer('pointerup', at(9), { isPrimary: false, pointerId: 2 });
			expect(onpick).not.toHaveBeenCalled();
			pointer('pointerdown', at(3));
			pointer('pointermove', at(12), { isPrimary: false, pointerId: 2 });
			pointer('pointercancel', at(12), { isPrimary: false, pointerId: 2 });
			pointer('pointerup', at(12), { isPrimary: false, pointerId: 2 });
			expect(onpick).not.toHaveBeenCalled();
			pointer('pointermove', at(5));
			pointer('pointerup', at(5));
			expect(onpick).toHaveBeenCalledExactlyOnceWith(3, 5);
		});

		it('a held Enter opens one moment, not one per repeat', async () => {
			const { key, onpick } = setup();
			await key('ArrowRight');
			await key('Enter');
			await key('Enter', false, true);
			await key(' ', false, true);
			expect(onpick).toHaveBeenCalledOnce();
		});

		it('focus leaving the chart clears its point, range and spoken line', async () => {
			const { key, group, live, container, onpick } = setup({ highlightIndex: 21 });
			await key('Home');
			await key('ArrowRight', true);
			expect(container.querySelector('.tip-tx')?.textContent).toBe('01:00 · 0.35 GB');
			await fireEvent.blur(group);
			expect(live()).toBe('');
			expect(container.querySelector('rect.band.pick')).toBeNull();
			expect(container.querySelector('.guide')).toBeNull();
			// the headline is back, and Enter on return opens it, not the old range
			expect(container.querySelector('.tip-tx')?.textContent).toBe('21:00 · 4.7 GB');
			await key('Enter');
			expect(onpick).toHaveBeenCalledExactlyOnceWith(21, 21);
		});

		it('arrows move the point (with its tooltip and a spoken line), Home and End jump, Enter opens it', async () => {
			const { key, onpick, live, container } = setup();
			await key('ArrowRight');
			expect(live()).toBe('00:00 · 0.5 GB');
			expect(container.querySelector('.tip-tx')?.textContent).toBe('00:00 · 0.5 GB');
			expect(container.querySelector('.guide')).not.toBeNull();
			await key('ArrowRight');
			await key('Enter');
			expect(onpick).toHaveBeenLastCalledWith(1, 1);
			await key('ArrowLeft');
			await key('ArrowLeft'); // stops at the first point
			await key(' ');
			expect(onpick).toHaveBeenLastCalledWith(0, 0);
			await key('End');
			expect(live()).toBe('23:00 · 1.7 GB');
			await key('ArrowRight'); // stops at the last point
			await key('Enter');
			expect(onpick).toHaveBeenLastCalledWith(23, 23);
			await key('Home');
			await key('Enter');
			expect(onpick).toHaveBeenLastCalledWith(0, 0);
		});

		it('the first arrow starts next to the headline point', async () => {
			const { key, onpick } = setup({ highlightIndex: 21 });
			await key('ArrowRight');
			await key('Enter');
			expect(onpick).toHaveBeenCalledExactlyOnceWith(22, 22);
		});

		it('Shift with the arrows picks a range from where it started; Escape clears it', async () => {
			const { key, onpick, live, container } = setup();
			await key('End');
			await key('ArrowLeft', true);
			await key('ArrowLeft', true);
			expect(live()).toBe('from 21:00 · 4.7 GB to 23:00 · 1.7 GB');
			expect(container.querySelector('rect.band.pick')).not.toBeNull();
			await key('Enter');
			expect(onpick).toHaveBeenLastCalledWith(21, 23);
			// a plain arrow drops the range
			await key('ArrowLeft');
			await key('Enter');
			expect(onpick).toHaveBeenLastCalledWith(20, 20);
			await key('ArrowLeft', true);
			await key('Escape');
			expect(live()).toBe('');
			expect(container.querySelector('rect.band.pick')).toBeNull();
			onpick.mockClear();
			await key('Enter'); // nothing chosen and no headline: nothing to open
			expect(onpick).not.toHaveBeenCalled();
		});

		it('new data between pointer-down and pointer-up cancels the drag', async () => {
			const { pointer, onpick, rerender } = setup();
			pointer('pointerdown', at(3));
			pointer('pointermove', at(8));
			await rerender({ series: [toSeries('down', 1, UP)] });
			pointer('pointerup', at(8));
			expect(onpick).not.toHaveBeenCalled();
		});

		it('a new, shorter series between a keyboard range and Enter clears the range and keeps the point inside it', async () => {
			const { key, onpick, rerender } = setup();
			await key('End');
			await key('ArrowLeft', true);
			await rerender({ series: [toSeries('down', 1, DOWN.slice(0, 10))] });
			await key('Enter');
			expect(onpick).toHaveBeenCalledExactlyOnceWith(9, 9);
		});
	});

	it('ignores a highlight index outside the data', () => {
		const { container } = draw([toSeries('down', 1, DOWN)], { highlightIndex: 99 });
		expect(container.querySelector('rect.band')).toBeNull();
		expect(container.querySelector('.tip-bg')).toBeNull();
	});
});
