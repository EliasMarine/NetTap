import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import Ring from './Ring.svelte';

const draw = (value: number) => render(Ring, { props: { value, ariaLabel: 'Trust score 64 out of 100' } });
const dash = (el: Element | null) => el?.getAttribute('stroke-dasharray')?.split(' ').map(Number) ?? [];

describe('Ring', () => {
	it('draws an accent arc over the track for the score', () => {
		const { container, getByRole } = draw(64);
		expect(getByRole('img').getAttribute('aria-label')).toBe('Trust score 64 out of 100');
		expect(container.querySelector('circle.track')).not.toBeNull();
		const [len, circ] = dash(container.querySelector('circle.prog'));
		expect(len / circ).toBeCloseTo(0.64, 2);
		expect(container.querySelector('.d-num')?.textContent).toBe('64');
		expect(container.querySelector('.d-lbl')?.textContent).toBe('of 100');
	});

	it('draws only the track at 0 and clamps out-of-range or NaN values', () => {
		expect(draw(0).container.querySelector('circle.prog')).toBeNull();
		const over = draw(140).container;
		const [len, circ] = dash(over.querySelector('circle.prog'));
		expect(len).toBeCloseTo(circ, 1);
		expect(over.querySelector('.d-num')?.textContent).toBe('100');
		const bad = draw(Number.NaN).container;
		expect(bad.querySelector('circle.prog')).toBeNull();
		expect(bad.innerHTML).not.toMatch(/NaN/);
	});
});
