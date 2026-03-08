import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import ResizeDivider from './ResizeDivider.svelte';

describe('ResizeDivider', () => {
	it('renders a horizontal divider by default', () => {
		const { container } = render(ResizeDivider, {
			props: { direction: 'horizontal', ondrag: vi.fn() },
		});
		const el = container.querySelector('.resize-divider');
		expect(el).not.toBeNull();
		expect(el?.classList.contains('horizontal')).toBe(true);
	});

	it('renders a vertical divider', () => {
		const { container } = render(ResizeDivider, {
			props: { direction: 'vertical', ondrag: vi.fn() },
		});
		const el = container.querySelector('.resize-divider');
		expect(el?.classList.contains('vertical')).toBe(true);
	});

	it('calls ondrag during pointer move after pointerdown', async () => {
		const ondrag = vi.fn();
		const { container } = render(ResizeDivider, {
			props: { direction: 'horizontal', ondrag },
		});
		const el = container.querySelector('.resize-divider')!;

		await fireEvent.pointerDown(el, { clientX: 100, clientY: 200, pointerId: 1 });
		await fireEvent.pointerMove(document, { clientX: 100, clientY: 250, pointerId: 1 });
		await fireEvent.pointerUp(document, { pointerId: 1 });

		expect(ondrag).toHaveBeenCalled();
	});
});
