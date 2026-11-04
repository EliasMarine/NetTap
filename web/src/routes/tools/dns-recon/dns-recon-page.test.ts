import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import Page from './+page.svelte';

const RESULT = {
	domain: 'example.com',
	records: {
		A: [{ name: 'example.com.', ttl: 300, class: 'IN', type: 'A', value: '93.184.215.14' }],
		MX: [],
	},
	total_records: 1,
	record_types_queried: ['A', 'MX'],
	errors: [],
};

function stubFetch(body: unknown, ok = true) {
	const fetch = vi.fn(async (_url: string, _init?: RequestInit) => ({ ok, status: ok ? 200 : 500, json: async () => body }));
	vi.stubGlobal('fetch', fetch);
	return fetch;
}

async function lookUp() {
	await fireEvent.input(screen.getByLabelText('Domain'), { target: { value: 'example.com' } });
	await fireEvent.click(screen.getByRole('button', { name: 'Lookup' }));
}

describe('DNS reconnaissance page', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('starts empty, with the default record types pressed', async () => {
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: 'DNS reconnaissance' })).toBeInTheDocument();
		expect(screen.getByText('Enter a domain')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'A' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByRole('button', { name: 'PTR' })).toHaveAttribute('aria-pressed', 'false');
		await fireEvent.click(screen.getByRole('button', { name: 'PTR' }));
		expect(screen.getByRole('button', { name: 'PTR' })).toHaveAttribute('aria-pressed', 'true');
	});

	it('shows the loading state while the lookup runs', async () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		await lookUp();
		expect(screen.getByRole('status')).toHaveTextContent('Looking up DNS records');
	});

	it('sends the chosen types and shows one card per type, with a sortable table', async () => {
		const fetch = stubFetch(RESULT);
		render(Page);
		await fireEvent.click(screen.getByRole('button', { name: 'TXT' }));
		await lookUp();

		expect(await screen.findByText('1 records found')).toBeInTheDocument();
		expect(JSON.parse(String(fetch.mock.calls[0][1]?.body)).record_types).toEqual(['A', 'AAAA', 'CNAME', 'MX', 'NS', 'SOA']);
		const table = screen.getByRole('table', { name: 'A records' });
		expect(within(table).getByText('93.184.215.14')).toBeInTheDocument();
		expect(within(table).getAllByRole('columnheader').every((th) => th.hasAttribute('aria-sort'))).toBe(true);
		expect(screen.getByText('No MX records found')).toBeInTheDocument();
	});

	it('shows the error notice when the lookup fails', async () => {
		stubFetch({ error: 'dig timed out' }, false);
		render(Page);
		await lookUp();
		expect(await screen.findByRole('alert')).toHaveTextContent('dig timed out');
	});
});
