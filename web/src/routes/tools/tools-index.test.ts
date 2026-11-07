import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import Page from './+page.svelte';

const HREFS = [
	'/tools/ping',
	'/tools/subnet-calc',
	'/tools/port-reference',
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
		expect(screen.getByRole('heading', { name: 'Network · 3 tools' })).toBeInTheDocument();
		expect(screen.getByRole('heading', { name: 'Analysis · 3 tools' })).toBeInTheDocument();
		expect(screen.getByRole('heading', { name: 'Lookup · 5 tools' })).toBeInTheDocument();
	});

	it('filters by name and by tag, and says when nothing matches', async () => {
		render(Page);
		const field = screen.getByRole('searchbox', { name: 'Search tools' });

		await fireEvent.input(field, { target: { value: 'certificate' } });
		expect(toolLinks()).toEqual(['/tools/ssl-cert']);

		await fireEvent.input(field, { target: { value: 'oui' } });
		expect(toolLinks()).toEqual(['/tools/mac-lookup']);
		expect(screen.queryByRole('heading', { name: /^Network ·/ })).not.toBeInTheDocument();

		await fireEvent.input(field, { target: { value: 'zzz' } });
		expect(toolLinks()).toEqual([]);
		expect(screen.getByText('No tools match "zzz"')).toBeInTheDocument();
	});
});
