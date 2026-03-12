import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import FloatingPanel from './FloatingPanel.svelte';

describe('FloatingPanel', () => {
	it('renders with title and close button', () => {
		render(FloatingPanel, {
			props: { title: 'Protocol Tree', panelId: 'tree', onclose: vi.fn() },
		});
		expect(screen.getByText('Protocol Tree')).toBeInTheDocument();
		expect(screen.getByTitle('Dock panel')).not.toBeNull();
	});

	it('calls onclose when close button is clicked', async () => {
		const onclose = vi.fn();
		render(FloatingPanel, {
			props: { title: 'Test', panelId: 'test', onclose },
		});
		await fireEvent.click(screen.getByTitle('Dock panel'));
		expect(onclose).toHaveBeenCalledWith('test');
	});

	it('positions at provided coordinates', () => {
		const { container } = render(FloatingPanel, {
			props: { title: 'Test', panelId: 'test', x: 100, y: 50, width: 600, height: 400, onclose: vi.fn() },
		});
		const el = container.querySelector('.floating-panel') as HTMLElement;
		expect(el.style.left).toBe('100px');
		expect(el.style.top).toBe('50px');
	});
});
