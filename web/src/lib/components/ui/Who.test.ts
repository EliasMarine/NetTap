import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import Who from './Who.svelte';
import { ICONS, type IconName } from './icons';

function iconMarkup(name: IconName): string {
	const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
	svg.innerHTML = ICONS[name];
	return svg.innerHTML;
}

describe('Who', () => {
	it('shows the device icon, the name over the mono IP', () => {
		const { container } = render(Who, { name: 'Living-room TV', ip: '192.168.1.42', category: 'media' });
		const who = container.querySelector('.who')!;
		expect(who.querySelector(':scope > svg')!.innerHTML).toBe(iconMarkup('tv'));
		const name = who.querySelector('.two > .who-name.trunc')!;
		expect(name).toHaveTextContent('Living-room TV');
		expect(name).toHaveAttribute('title', 'Living-room TV');
		expect(who.querySelector('.two > .mono')).toHaveTextContent('192.168.1.42');
	});

	it('uses the generic icon and drops the IP line when they are missing', () => {
		const { container } = render(Who, { name: 'Unknown device' });
		expect(container.querySelector('.who > svg')!.innerHTML).toBe(iconMarkup('devices'));
		expect(container.querySelector('.mono')).toBeNull();
	});
});
