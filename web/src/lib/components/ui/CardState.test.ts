import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import CardState from './CardState.svelte';
import { ICONS, type IconName } from './icons';

/** The markup an icon renders, serialised the way the DOM serialises it. */
function iconMarkup(name: IconName): string {
	const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
	svg.innerHTML = ICONS[name];
	return svg.innerHTML;
}

describe('CardState loading', () => {
	it('is a busy status with skeleton blocks and a hidden "Loading" name', () => {
		const { container } = render(CardState, { state: 'loading' });
		const status = screen.getByRole('status');
		expect(status).toHaveClass('skel-wrap');
		expect(status).toHaveAttribute('aria-busy', 'true');
		expect(status.querySelector('.sr-only')).toHaveTextContent('Loading');
		expect(container.querySelectorAll('.skel')).toHaveLength(3);
	});

	it('uses the title as its accessible text', () => {
		render(CardState, { state: 'loading', title: 'Loading bandwidth' });
		expect(screen.getByRole('status')).toHaveTextContent('Loading bandwidth');
	});
});

describe('CardState empty', () => {
	it('shows the icon tile, heading, sentence and one action button', async () => {
		const onaction = vi.fn();
		const { container } = render(CardState, {
			state: 'empty',
			title: 'No devices seen yet',
			message: 'Devices appear here once NetTap sees their traffic.',
			actionLabel: 'Open Go Live',
			onaction,
		});
		const state = container.querySelector('.state')!;
		expect(state).not.toHaveClass('is-error');
		expect(state).not.toHaveAttribute('role');
		expect(state.querySelector('.state-ic svg')!.innerHTML).toBe(iconMarkup('empty'));
		expect(screen.getByRole('heading', { level: 3, name: 'No devices seen yet' })).toBeInTheDocument();
		expect(screen.getByText('Devices appear here once NetTap sees their traffic.')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Open Go Live' }));
		expect(onaction).toHaveBeenCalledOnce();
	});

	it('links the action when given an href, and takes a custom icon', () => {
		const { container } = render(CardState, {
			state: 'empty',
			title: 'No alerts in this window',
			actionLabel: 'Open Go Live',
			href: '/go-live',
			icon: 'alerts',
		});
		const link = screen.getByRole('link', { name: 'Open Go Live' });
		expect(link).toHaveAttribute('href', '/go-live');
		expect(link).toHaveClass('btn');
		expect(container.querySelector('.state-ic svg')!.innerHTML).toBe(iconMarkup('alerts'));
	});

	it('has no action without a label', () => {
		render(CardState, { state: 'empty', title: 'Nothing here', onaction: vi.fn() });
		expect(screen.queryByRole('button')).toBeNull();
	});
});

describe('CardState error', () => {
	it('is an alert with the warn icon and a Try again button wired to the retry callback', async () => {
		const onaction = vi.fn();
		const { container } = render(CardState, {
			state: 'error',
			title: "Couldn't load alerts: the request failed.",
			message: 'Check that the NetTap daemon is running on the System page.',
			onaction,
		});
		const alert = screen.getByRole('alert');
		expect(alert).toHaveClass('state', 'is-error');
		expect(alert.querySelector('.state-ic svg')!.innerHTML).toBe(iconMarkup('warn'));
		expect(screen.getByRole('heading', { name: "Couldn't load alerts: the request failed." })).toBeInTheDocument();
		const retry = screen.getByRole('button', { name: 'Try again' });
		expect(retry.querySelector('svg')!.innerHTML).toBe(iconMarkup('refresh'));
		await fireEvent.click(retry);
		expect(onaction).toHaveBeenCalledOnce();
		expect(container.querySelector('a')).toBeNull();
	});

	it('has a default heading, a custom action label, and no button without a callback', () => {
		const { unmount } = render(CardState, { state: 'error', onaction: vi.fn(), actionLabel: 'Reload' });
		expect(screen.getByRole('heading', { name: "Couldn't load this: the request failed." })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument();
		unmount();
		render(CardState, { state: 'error' });
		expect(screen.queryByRole('button')).toBeNull();
	});
});
