import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import BarList, { type BarItem } from './BarList.svelte';

const fills = (container: HTMLElement) => [...container.querySelectorAll<HTMLElement>('.bar-fill')];
const widths = (container: HTMLElement) => fills(container).map((f) => f.style.getPropertyValue('--w'));

describe('BarList', () => {
	it('renders one bar row per item with the figure and its detail', () => {
		const { container } = render(BarList, {
			items: [
				{ key: 'streaming', label: 'Streaming', value: 21.4, display: '21.4 GB', detail: '44%' },
				{ key: 'web', label: 'Web and apps', value: 9.8, display: '9.8 GB' },
			],
		});
		const rows = container.querySelectorAll('ul.bars > li.bar-row');
		expect(rows).toHaveLength(2);
		expect(rows[0].querySelector('.v')).toHaveTextContent('21.4 GB · 44%');
		expect(rows[0].querySelector('.v > b')).toHaveTextContent('21.4 GB');
		expect(rows[1].querySelector('.v')).toHaveTextContent(/^9\.8 GB$/);
		expect(rows[0].querySelector('.bar-track')).toHaveAttribute('aria-hidden', 'true');
	});

	it('scales bars to the largest item', () => {
		const { container } = render(BarList, {
			items: [
				{ key: 'a', label: 'A', value: 20, display: '20' },
				{ key: 'b', label: 'B', value: 5, display: '5' },
				{ key: 'c', label: 'C', value: 0, display: '0' },
				{ key: 'd', label: 'D', value: Number.NaN, display: '-' },
			],
		});
		expect(widths(container)).toEqual(['100.0%', '25.0%', '0.0%', '0.0%']);
	});

	it('draws empty bars when every value is zero', () => {
		const { container } = render(BarList, { items: [{ key: 'a', label: 'A', value: 0, display: '0' }] });
		expect(widths(container)).toEqual(['0.0%']);
	});

	it('uses data-1 by default and the colour a page sets', () => {
		const { container } = render(BarList, {
			items: [
				{ key: 'a', label: 'A', value: 2, display: '2' },
				{ key: 'b', label: 'B', value: 1, display: '1', colour: 4 },
			],
		});
		expect(fills(container)[0]).toHaveClass('c-d1');
		expect(fills(container)[1]).toHaveClass('c-d4');
	});

	it('never aggregates: every item keeps its own row, link and action', async () => {
		const onclick = vi.fn();
		const items: BarItem[] = Array.from({ length: 10 }, (_, i) => ({
			key: `k${i}`,
			label: `Category ${i}`,
			value: 10 - i,
			display: String(10 - i),
			...(i === 0 ? { href: '/traffic/k0' } : i === 9 ? { onclick } : {}),
		}));
		const { container } = render(BarList, { items });
		expect(container.querySelectorAll('.bar-row')).toHaveLength(10);
		expect(screen.getByRole('link', { name: 'Category 0' })).toHaveAttribute('href', '/traffic/k0');
		await fireEvent.click(screen.getByRole('button', { name: 'Category 9' }));
		expect(onclick).toHaveBeenCalledOnce();
		expect(screen.getByText('Category 5').tagName).toBe('SPAN');
	});
});
