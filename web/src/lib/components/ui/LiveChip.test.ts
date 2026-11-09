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

	it('NET-237: reads "Not updating" as a warning while stalled, with no pulsing dot', () => {
		const { container } = render(LiveChip, { paused: false, stalled: true });
		const chip = container.querySelector('.chip')!;
		expect(chip).toHaveClass('is-warn');
		expect(chip).not.toHaveClass('live-chip');
		expect(chip).toHaveTextContent('Not updating');
		expect(chip.querySelector('.live-dot')).toBeNull();
	});

	it('paused wins over stalled: no request is being made', () => {
		const { container } = render(LiveChip, { paused: true, stalled: true });
		expect(container.querySelector('.live-chip')).toHaveTextContent('Paused');
	});

	it('reads Paused and adds is-paused', () => {
		const { container } = render(LiveChip, { paused: true });
		const chip = container.querySelector('.live-chip')!;
		expect(chip).toHaveClass('is-paused');
		expect(chip).toHaveTextContent('Paused');
	});
});
