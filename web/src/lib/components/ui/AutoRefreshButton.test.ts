import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import AutoRefreshButton from './AutoRefreshButton.svelte';

describe('AutoRefreshButton', () => {
	it('reads "Auto" with its interval while on, and "Paused" while off (Home\'s wording)', () => {
		const { rerender } = render(AutoRefreshButton, { on: true, seconds: 30, ontoggle: () => {} });
		expect(screen.getByRole('button', { name: 'Auto' })).toHaveAttribute('title', 'Refreshes every 30 s');
		rerender({ on: false, seconds: 30, ontoggle: () => {} });
		expect(screen.getByRole('button', { name: 'Paused' })).toHaveAttribute('title', 'Auto-refresh is paused');
	});

	it('calls ontoggle on click', async () => {
		const ontoggle = vi.fn();
		render(AutoRefreshButton, { on: false, seconds: 15, ontoggle });
		await fireEvent.click(screen.getByRole('button', { name: 'Paused' }));
		expect(ontoggle).toHaveBeenCalledOnce();
	});
});
