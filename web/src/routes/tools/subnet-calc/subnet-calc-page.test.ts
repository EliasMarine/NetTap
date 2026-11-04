import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import Page from './+page.svelte';

const fact = (label: string) => screen.getByText(label).nextElementSibling?.textContent;

describe('Subnet calculator page', () => {
	it('calculates the default block as facts', () => {
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: 'Subnet calculator' })).toBeInTheDocument();
		expect(fact('CIDR block')).toBe('192.168.1.0/24');
		expect(fact('Broadcast address')).toBe('192.168.1.255');
		expect(fact('Usable hosts')).toBe((254).toLocaleString());
		expect(fact('Netmask')).toBe('255.255.255.0');
	});

	it('takes the prefix from the address when it is written as CIDR', async () => {
		render(Page);
		await fireEvent.input(screen.getByLabelText('IP address'), { target: { value: '10.0.0.5/30' } });
		expect(fact('CIDR block')).toBe('10.0.0.4/30');
		expect(fact('Usable hosts')).toBe('2');
	});

	it('says the address is invalid, and shows the empty state when there is none', async () => {
		render(Page);
		const field = screen.getByLabelText('IP address');
		await fireEvent.input(field, { target: { value: '300.1.1.1' } });
		expect(screen.getByRole('alert')).toHaveTextContent('Invalid IP address. Enter a valid IPv4 address (e.g. 192.168.1.0).');
		await fireEvent.input(field, { target: { value: '' } });
		expect(screen.getByText('Enter an IP address')).toBeInTheDocument();
	});
});
