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

	// NET-362 (RFC 3021): a /31's two addresses are both endpoints, and a /32 is one host; neither has a broadcast
	it('gives a /31 two usable endpoints and no broadcast, and a /32 one host and no broadcast', async () => {
		render(Page);
		const field = screen.getByLabelText('IP address');
		await fireEvent.input(field, { target: { value: '192.0.2.9/31' } });
		expect(fact('CIDR block')).toBe('192.0.2.8/31');
		expect(fact('First usable IP')).toBe('192.0.2.8');
		expect(fact('Last usable IP')).toBe('192.0.2.9');
		expect(fact('Broadcast address')).toBe('None (point-to-point)');
		expect(fact('Usable hosts')).toBe('2');

		await fireEvent.input(field, { target: { value: '192.0.2.9/32' } });
		expect(fact('First usable IP')).toBe('192.0.2.9');
		expect(fact('Last usable IP')).toBe('192.0.2.9');
		expect(fact('Broadcast address')).toBe('None (single host)');

		await fireEvent.input(field, { target: { value: '192.0.2.9/30' } });
		expect(fact('Broadcast address')).toBe('192.0.2.11');
		expect(fact('Last usable IP')).toBe('192.0.2.10');
	});

	it('says the address is invalid, and shows the empty state when there is none', async () => {
		render(Page);
		const field = screen.getByLabelText('IP address');
		await fireEvent.input(field, { target: { value: '300.1.1.1' } });
		expect(screen.getByRole('alert')).toHaveTextContent('Invalid IP address. Enter a valid IPv4 address (e.g. 192.168.1.0).');
		await fireEvent.input(field, { target: { value: '' } });
		expect(screen.getByText('Enter an IP address')).toBeInTheDocument();
	});

	it('sends an IPv6 address to the IPv6 toolkit instead of calling it invalid (NET-218)', async () => {
		render(Page);
		await fireEvent.input(screen.getByLabelText('IP address'), { target: { value: '2001:db8::/64' } });
		expect(screen.queryByRole('alert')).not.toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'The IPv6 toolkit explains it.' })).toHaveAttribute('href', '/tools/ipv6?address=2001%3Adb8%3A%3A%2F64');
	});
});
