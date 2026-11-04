import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { goto } from '$app/navigation';
import DnsIndex from './dns/+page.svelte';
import WhoisIndex from './whois/+page.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

describe.each([
	['Reverse DNS lookup', DnsIndex, '/lookup/dns/'],
	['WHOIS lookup', WhoisIndex, '/lookup/whois/'],
])('%s index page', (title, Page, prefix) => {
	afterEach(() => vi.mocked(goto).mockClear());

	it('shows the form and the empty result card', () => {
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: title })).toBeInTheDocument();
		expect(screen.getByText('Enter an IP address')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Lookup' })).toBeDisabled();
	});

	it('goes to the result page on Lookup and on Enter, with the address trimmed and encoded', async () => {
		render(Page);
		const field = screen.getByLabelText('IP address');
		await fireEvent.input(field, { target: { value: ' 2001:db8::1 ' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Lookup' }));
		expect(goto).toHaveBeenLastCalledWith(`${prefix}2001%3Adb8%3A%3A1`);
		await fireEvent.keyDown(field, { key: 'Enter' });
		expect(goto).toHaveBeenCalledTimes(2);
	});
});
