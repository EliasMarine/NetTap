import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import KpiCard from './KpiCard.svelte';
import { ICONS, type IconName } from './icons';

function iconMarkup(name: IconName): string {
	const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
	svg.innerHTML = ICONS[name];
	return svg.innerHTML;
}

describe('KpiCard', () => {
	it('renders label, icon, value and unit in the system structure', () => {
		const { container } = render(KpiCard, { label: 'Bandwidth', icon: 'bandwidth', value: '39.2', unit: 'GB' });
		const card = container.querySelector('article.card.kpi')!;
		expect(card.querySelector('.kpi-top > span')).toHaveTextContent('Bandwidth');
		expect(card.querySelector('.kpi-top > svg')!.innerHTML).toBe(iconMarkup('bandwidth'));
		expect(card.querySelector('.kpi-num')).toHaveTextContent('39.2GB');
		expect(card.querySelector('.kpi-num > .kpi-unit')).toHaveTextContent('GB');
		expect(card.querySelector('.kpi-meta')).toBeNull();
		expect(card.querySelector('.kpi-sub')).toBeNull();
		expect(card.querySelector('.kpi-foot')).toBeNull();
	});

	it('shows a numeric value with no unit', () => {
		const { container } = render(KpiCard, { label: 'Active devices', icon: 'devices', value: 34 });
		expect(container.querySelector('.kpi-num')).toHaveTextContent('34');
		expect(container.querySelector('.kpi-unit')).toBeNull();
	});

	it('shows a neutral down delta with its comparison window', () => {
		const { container } = render(KpiCard, {
			label: 'Bandwidth',
			icon: 'bandwidth',
			value: '39.2',
			delta: { text: '−13%', direction: 'down' },
			comparison: 'vs previous 24 h',
		});
		const chip = container.querySelector('.kpi-meta > .chip')!;
		expect(chip).toHaveTextContent('−13%');
		expect(chip).not.toHaveClass('is-warn');
		expect(chip.querySelector('svg')!.innerHTML).toBe(iconMarkup('down'));
		expect(container.querySelector('.kpi-meta')).toHaveTextContent('vs previous 24 h');
	});

	it('marks a bad rise is-warn with the up arrow', () => {
		const { container } = render(KpiCard, {
			label: 'Alerts',
			icon: 'alerts',
			value: 37,
			delta: { text: '+48%', direction: 'up', bad: true },
			comparison: 'vs previous 24 h',
		});
		const chip = container.querySelector('.chip')!;
		expect(chip).toHaveClass('is-warn');
		expect(chip.querySelector('svg')!.innerHTML).toBe(iconMarkup('up'));
	});

	it('shows a source note when there is no comparison, and the sub line', () => {
		const { container } = render(KpiCard, {
			label: 'Active devices',
			icon: 'devices',
			value: 34,
			note: 'from Changelog',
			sub: '↓ 31.8 GB down · ↑ 7.4 GB up',
		});
		expect(container.querySelector('.kpi-meta')).toHaveTextContent('from Changelog');
		expect(container.querySelector('.kpi-meta .chip')).toBeNull();
		expect(container.querySelector('.kpi-sub')).toHaveTextContent('↓ 31.8 GB down · ↑ 7.4 GB up');
	});

	it('makes the whole card one link when given an href', () => {
		const { container } = render(KpiCard, { label: 'Alerts', icon: 'alerts', value: 37, href: '/alerts', class: 'c-3' });
		const link = screen.getByRole('link');
		expect(link).toHaveAttribute('href', '/alerts');
		expect(link).toHaveClass('card', 'kpi', 'c-3');
		expect(link).toHaveTextContent('Alerts');
		expect(container.querySelector('article')).toBeNull();
	});

	it('renders the foot snippet in .kpi-foot', () => {
		const foot = createRawSnippet(() => ({ render: () => '<div class="stackbar">bar</div>' }));
		const { container } = render(KpiCard, { label: 'Active devices', icon: 'devices', value: 34, foot });
		expect(container.querySelector('.kpi-foot > .stackbar')).toBeInTheDocument();
	});
});
