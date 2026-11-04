import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import Bytes from './Bytes.svelte';

const MAX = 2_410_000_000;

function barWidth(value: number, max = MAX): number {
	const { container, unmount } = render(Bytes, { value, max, display: 'x' });
	const width = parseFloat((container.querySelector('.mini > span') as HTMLElement).style.getPropertyValue('--w'));
	unmount();
	return width;
}

describe('Bytes', () => {
	it('shows the formatted value over a decorative mini bar', () => {
		const { container } = render(Bytes, { value: 6144, max: MAX, display: '6 KB' });
		const cell = container.querySelector('.bytes')!;
		expect(cell.firstElementChild).toHaveTextContent('6 KB');
		expect(cell.querySelector('.mini')).toHaveAttribute('aria-hidden', 'true');
	});

	it('scales the bar on a log scale, as the system preview does', () => {
		expect(barWidth(MAX)).toBe(100);
		expect(barWidth(5_033_164)).toBeCloseTo(71.5, 0);
		expect(barWidth(6144)).toBeCloseTo(40.4, 0);
		expect(barWidth(60)).toBeCloseTo(19.1, 0);
	});

	it('draws no bar for zero, negative or a zero max, and never more than full', () => {
		expect(barWidth(0)).toBe(0);
		expect(barWidth(-5)).toBe(0);
		expect(barWidth(100, 0)).toBe(0);
		expect(barWidth(500, 100)).toBe(100);
	});
});
