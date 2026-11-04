import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import DeviceTile from './DeviceTile.svelte';
import { ICONS, type IconName } from './icons';

function iconMarkup(name: IconName): string {
	const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
	svg.innerHTML = ICONS[name];
	return svg.innerHTML;
}

describe('DeviceTile', () => {
	it.each<[string | undefined, IconName]>([
		['phone', 'phone'],
		['computer', 'laptop'],
		['media', 'tv'],
		['iot', 'iot'],
		['infrastructure', 'infra'],
		['unknown', 'devices'],
		[undefined, 'devices'],
	])('shows the icon for category %s', (category, icon) => {
		const { container } = render(DeviceTile, { category });
		const tile = container.querySelector('span.tile')!;
		expect(tile).not.toHaveClass('lg');
		expect(tile.querySelector('svg')!.innerHTML).toBe(iconMarkup(icon));
		expect(tile.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
	});

	it('grows to the large tile', () => {
		const { container } = render(DeviceTile, { category: 'nas', size: 'lg' });
		expect(container.querySelector('.tile')).toHaveClass('lg');
	});
});
