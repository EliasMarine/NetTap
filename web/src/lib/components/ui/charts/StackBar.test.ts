import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import StackBar from './StackBar.svelte';

const item = (key: string, value: number) => ({ key, label: key, value });
const draw = (items: ReturnType<typeof item>[]) =>
	render(StackBar, { props: { items, formatValue: String, ariaLabel: '34 devices: 14 computers, 12 smart home' } });

describe('StackBar', () => {
	it('draws a segment per item, sized by value, with a hidden legend', () => {
		const { container, getByRole } = draw([item('Smart home', 12), item('Computers', 14), item('Media', 6)]);
		expect(getByRole('img').getAttribute('aria-label')).toBe('34 devices: 14 computers, 12 smart home');
		const segs = [...container.querySelectorAll('.sb-track span')] as HTMLElement[];
		expect(segs.map((s) => [s.className, s.style.flex.split(' ')[0]])).toEqual([
			['c-d1', '14'],
			['c-d2', '12'],
			['c-d3', '6'],
		]);
		const legend = container.querySelector('.sb-legend')!;
		expect(legend.getAttribute('aria-hidden')).toBe('true');
		expect(legend.querySelectorAll('li')[0].textContent).toContain('Computers');
		expect(legend.querySelector('b')?.textContent).toBe('14');
	});

	it('folds past six into "Everything else" and draws no segment for zero', () => {
		const items = 'abcdefgh'.split('').map((k, i) => item(k, 8 - i));
		const { container } = draw([...items, item('zero', 0)]);
		expect(container.querySelectorAll('.sb-track span')).toHaveLength(6);
		expect(container.querySelectorAll('.sb-legend li')[5].textContent).toContain('Everything else');

		const withZero = draw([item('a', 3), item('b', 0)]).container;
		expect(withZero.querySelectorAll('.sb-track span')).toHaveLength(1);
		expect(withZero.querySelectorAll('.sb-legend li')).toHaveLength(2);
	});

	it('renders nothing when there is nothing to show', () => {
		expect(draw([]).container.querySelector('.stackbar')).toBeNull();
		expect(draw([item('a', 0)]).container.querySelector('.stackbar')).toBeNull();
	});
});
