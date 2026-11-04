import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import LiveChip from './LiveChip.svelte';

describe('LiveChip', () => {
	it('reads Live with a decorative pulsing dot', () => {
		const { container } = render(LiveChip, { paused: false });
		const chip = container.querySelector('.chip.live-chip')!;
		expect(chip).not.toHaveClass('is-paused');
		expect(chip).toHaveTextContent('Live');
		expect(chip.querySelector('.live-dot')).toHaveAttribute('aria-hidden', 'true');
	});

	it('reads Paused and adds is-paused', () => {
		const { container } = render(LiveChip, { paused: true });
		const chip = container.querySelector('.live-chip')!;
		expect(chip).toHaveClass('is-paused');
		expect(chip).toHaveTextContent('Paused');
	});
});
