import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import Meter from './Meter.svelte';

describe('Meter', () => {
	it('is a named meter from 0 to 100 with a fill at its value', () => {
		render(Meter, { value: 41, label: 'Disk used' });
		const meter = screen.getByRole('meter', { name: 'Disk used' });
		expect(meter).toHaveClass('meter');
		expect(meter).toHaveAttribute('aria-valuenow', '41');
		expect(meter).toHaveAttribute('aria-valuemin', '0');
		expect(meter).toHaveAttribute('aria-valuemax', '100');
		expect((meter.firstElementChild as HTMLElement).style.width).toBe('41%');
	});

	it.each([
		[140, '100'],
		[-5, '0'],
		[Number.NaN, '0'],
	])('clamps %s to %s', (value, expected) => {
		render(Meter, { value, label: 'Encrypted sessions' });
		const meter = screen.getByRole('meter');
		expect(meter).toHaveAttribute('aria-valuenow', expected);
		expect((meter.firstElementChild as HTMLElement).style.width).toBe(`${expected}%`);
	});
});
