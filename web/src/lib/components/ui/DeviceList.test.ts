import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import DeviceList, { type DeviceListItem } from './DeviceList.svelte';

const ITEMS: DeviceListItem[] = [
	{ key: 'tv', name: 'Living-room TV', ip: '192.168.1.42', category: 'media', value: 14.2, display: '14.2 GB', href: '/devices/192.168.1.42' },
	{ key: 'laptop', name: 'Work laptop', ip: '192.168.1.23', category: 'computer', value: 7.1, display: '7.1 GB', href: '/devices/192.168.1.23' },
];

const miniWidths = (container: HTMLElement) =>
	[...container.querySelectorAll<HTMLElement>('.mini > span')].map((s) => s.style.getPropertyValue('--w'));

describe('DeviceList link mode', () => {
	it('links each row to its device page with tile, name, IP and value', () => {
		const { container } = render(DeviceList, { items: ITEMS });
		const link = screen.getByRole('link', { name: /Living-room TV/ });
		expect(link).toHaveClass('dev');
		expect(link).toHaveAttribute('href', '/devices/192.168.1.42');
		expect(link.querySelector('.tile')).toBeInTheDocument();
		expect(link.querySelector('.dev-name')).toHaveTextContent('Living-room TV');
		expect(link.querySelector('.dev-ip.mono')).toHaveTextContent('192.168.1.42');
		expect(link.querySelector('.dev-v')).toHaveTextContent('14.2 GB');
		expect(container.querySelectorAll('ul.dev-list > li')).toHaveLength(2);
	});

	it('scales the mini bars to the top device, or to max when given', () => {
		const { container, unmount } = render(DeviceList, { items: ITEMS });
		expect(miniWidths(container)).toEqual(['100.0%', '50.0%']);
		unmount();
		const second = render(DeviceList, { items: ITEMS, max: 28.4 });
		expect(miniWidths(second.container)).toEqual(['50.0%', '25.0%']);
	});

	it('renders a row without href as plain content, not a link', () => {
		const { container } = render(DeviceList, { items: [{ ...ITEMS[0], href: undefined }] });
		expect(screen.queryByRole('link')).toBeNull();
		expect(container.querySelector('div.dev')).toHaveTextContent('Living-room TV');
	});
});

describe('DeviceList select mode', () => {
	it('makes each row a toggle button and reports the chosen device', async () => {
		const onselect = vi.fn();
		render(DeviceList, { items: ITEMS, mode: 'select', selectedKey: 'laptop', onselect });
		expect(screen.queryByRole('link')).toBeNull();
		const tv = screen.getByRole('button', { name: /Living-room TV/ });
		const laptop = screen.getByRole('button', { name: /Work laptop/ });
		expect(tv).toHaveClass('dev');
		expect(tv).toHaveAttribute('aria-pressed', 'false');
		expect(laptop).toHaveAttribute('aria-pressed', 'true');
		await fireEvent.click(tv);
		expect(onselect).toHaveBeenCalledExactlyOnceWith(ITEMS[0]);
	});
});

describe('DeviceList sparkline', () => {
	it('swaps the mini bar for a decorative sparkline', () => {
		const { container } = render(DeviceList, {
			items: [{ ...ITEMS[0], display: '38.2 Mbps', spark: [1, 4, 2, 8] }],
			mode: 'select',
		});
		expect(container.querySelector('.mini')).toBeNull();
		const svg = container.querySelector('.dev-v svg')!;
		expect(svg).toHaveAttribute('aria-hidden', 'true');
		const points = svg.querySelector('polyline')!.getAttribute('points')!.split(' ');
		expect(points).toHaveLength(4);
		expect(points[0]).toBe('2.0,23.0'); // first point at the left, lowest value at the bottom
		expect(points[3]).toBe('70.0,3.0'); // last point at the right, highest value at the top
	});

	it('keeps the bar when there are too few points for a line', () => {
		const { container } = render(DeviceList, { items: [{ ...ITEMS[0], spark: [5] }] });
		expect(container.querySelector('svg polyline')).toBeNull();
		expect(container.querySelector('.mini')).toBeInTheDocument();
	});
});

// NET-200: a row's tile shows the owner's photo
describe('DeviceList pictures', () => {
	it("passes an item's photo to its tile", () => {
		const { container } = render(DeviceList, { items: [{ ...ITEMS[0], picture: '/api/devices/registry/AA:BB:CC:DD:EE:FF/picture?v=1' }] });
		expect(container.querySelector('.tile img')).toHaveAttribute('src', '/api/devices/registry/AA:BB:CC:DD:EE:FF/picture?v=1');
	});
});
