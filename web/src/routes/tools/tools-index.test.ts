import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import Page from './+page.svelte';

const HREFS = [
	'/tools/ping',
	'/tools/throughput',
	'/tools/subnet-calc',
	'/tools/ipv6',
	'/tools/port-reference',
	'/tools/dhcp-timeline',
	// OLD CODE: '/tools/tshark', (NET-188: the tool is Packet analysis now)
	'/packets',
	'/tools/cyberchef',
	'/tools/base64',
	'/tools/dns-recon',
	'/lookup/whois',
	'/lookup/dns',
	'/tools/mac-lookup',
	'/tools/ssl-cert',
];

const toolLinks = () => screen.queryAllByRole('link').map((a) => a.getAttribute('href'));

describe('Tools index', () => {
	it('lists every tool as a card link, grouped by category', () => {
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: 'Network tools' })).toBeInTheDocument();
		expect(toolLinks()).toEqual(HREFS);
		// OLD CODE: expect(screen.getByRole('heading', { name: 'Network · 5 tools' })).toBeInTheDocument(); (NET-266)
		expect(screen.getByRole('heading', { name: 'Network · 6 tools' })).toBeInTheDocument();
		expect(screen.getByRole('heading', { name: 'Analysis · 3 tools' })).toBeInTheDocument();
		expect(screen.getByRole('heading', { name: 'Lookup · 5 tools' })).toBeInTheDocument();
	});

	it('filters by name and by tag, and says when nothing matches', async () => {
		render(Page);
		const field = screen.getByRole('searchbox', { name: 'Search tools' });

		await fireEvent.input(field, { target: { value: 'certificate' } });
		expect(toolLinks()).toEqual(['/tools/ssl-cert']);

		await fireEvent.input(field, { target: { value: 'slaac' } });
		expect(toolLinks()).toEqual(['/tools/ipv6']);

		await fireEvent.input(field, { target: { value: 'lease' } });
		expect(toolLinks()).toEqual(['/tools/dhcp-timeline']);

		await fireEvent.input(field, { target: { value: 'oui' } });
		expect(toolLinks()).toEqual(['/tools/mac-lookup']);
		expect(screen.queryByRole('heading', { name: /^Network ·/ })).not.toBeInTheDocument();

		await fireEvent.input(field, { target: { value: 'iperf' } });
		expect(toolLinks()).toEqual(['/tools/throughput']);

		await fireEvent.input(field, { target: { value: 'zzz' } });
		expect(toolLinks()).toEqual([]);
		expect(screen.getByText('No tools match "zzz"')).toBeInTheDocument();
	});
});
