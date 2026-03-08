import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import DockPanel from './DockPanel.svelte';

describe('DockPanel', () => {
	it('renders the title', () => {
		render(DockPanel, { props: { title: 'Packet Table', panelId: 'table' } });
		expect(screen.getByText('Packet Table')).toBeInTheDocument();
	});

	it('shows minimize, maximize, and popout buttons', () => {
		const { container } = render(DockPanel, {
			props: { title: 'Proto Tree', panelId: 'tree' },
		});
		expect(container.querySelector('[title="Minimize"]')).not.toBeNull();
		expect(container.querySelector('[title="Maximize"]')).not.toBeNull();
		expect(container.querySelector('[title="Pop out"]')).not.toBeNull();
	});

	it('emits onaction when minimize is clicked', async () => {
		const onaction = vi.fn();
		const { container } = render(DockPanel, {
			props: { title: 'Test', panelId: 'test', onaction },
		});
		const btn = container.querySelector('[title="Minimize"]')!;
		await fireEvent.click(btn);
		expect(onaction).toHaveBeenCalledWith('test', 'minimize');
	});

	it('hides content when mode is minimized', () => {
		const { container } = render(DockPanel, {
			props: { title: 'Test', panelId: 'test', mode: 'minimized' },
		});
		const content = container.querySelector('.dock-panel-content');
		expect(content).toBeNull();
	});
});
