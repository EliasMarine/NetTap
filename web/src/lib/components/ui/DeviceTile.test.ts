import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
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

// NET-200: the owner's photo or picked icon
describe('DeviceTile picture and icon', () => {
	it("shows the owner's photo in place of the icon, as decoration", () => {
		const { container } = render(DeviceTile, { category: 'phone', picture: '/api/devices/registry/AA:BB:CC:DD:EE:FF/picture?v=0123456789abcdef' });
		const img = container.querySelector('.tile img')!;
		expect(img).toHaveAttribute('src', '/api/devices/registry/AA:BB:CC:DD:EE:FF/picture?v=0123456789abcdef');
		expect(img).toHaveAttribute('alt', '');
		expect(img).toHaveAttribute('width', '36');
		expect(container.querySelector('.tile svg')).toBeNull();
	});

	it('sizes the photo to the large tile', () => {
		const { container } = render(DeviceTile, { size: 'lg', picture: '/p?v=1' });
		expect(container.querySelector('.tile img')).toHaveAttribute('height', '72');
	});

	it('falls back to the icon when the photo fails to load', async () => {
		const { container } = render(DeviceTile, { category: 'phone', picture: '/p?v=1' });
		await fireEvent.error(container.querySelector('.tile img')!);
		expect(container.querySelector('.tile img')).toBeNull();
		expect(container.querySelector('.tile svg')!.innerHTML).toBe(iconMarkup('phone'));
	});

	it("uses the owner's icon over the category's", () => {
		const { container } = render(DeviceTile, { category: 'phone', icon: 'printer' });
		expect(container.querySelector('.tile svg')!.innerHTML).toBe(iconMarkup('printer'));
	});
});
