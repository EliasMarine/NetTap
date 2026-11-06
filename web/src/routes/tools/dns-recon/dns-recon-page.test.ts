import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import Page from './+page.svelte';

// OLD CODE START — a store that never emits again, so a later $page emission couldn't be tested
// const nav = vi.hoisted(() => ({ url: new URL('http://localhost/tools/dns-recon') }));
// vi.mock('$app/stores', () => ({
// 	page: { subscribe: (fn: (v: { url: URL }) => void) => (fn({ url: nav.url }), () => {}) },
// }));
// OLD CODE END
const nav = vi.hoisted(() => ({ url: new URL('http://localhost/tools/dns-recon'), subs: new Set<(v: { url: URL; state?: object }) => void>() }));
vi.mock('$app/stores', () => ({
	page: {
		subscribe: (fn: (v: { url: URL }) => void) => {
			nav.subs.add(fn);
			fn({ url: nav.url });
			return () => nav.subs.delete(fn);
		},
	},
}));
const emit = (v: { url: URL; state?: object }) => nav.subs.forEach((fn) => fn(v));

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
	afterEach(() => {
		vi.unstubAllGlobals();
		nav.url = new URL('http://localhost/tools/dns-recon');
	});

	it('fills the domain in from ?domain= without running the lookup', async () => {
		nav.url = new URL('http://localhost/tools/dns-recon?domain=example.com');
		const fetch = stubFetch(RESULT);
		render(Page);
		await vi.waitFor(() => expect(screen.getByLabelText('Domain')).toHaveValue('example.com'));
		expect(fetch).not.toHaveBeenCalled();
	});

	it('keeps what the user typed when $page emits again for the same navigation, and re-applies on a new one', async () => {
		nav.url = new URL('http://localhost/tools/dns-recon?domain=example.com');
		stubFetch(RESULT);
		render(Page);
		const box = screen.getByLabelText('Domain');
		await vi.waitFor(() => expect(box).toHaveValue('example.com'));
		await fireEvent.input(box, { target: { value: 'other.example' } });
		emit({ url: nav.url, state: {} }); // e.g. shallow-routing state, same URL
		await new Promise((r) => setTimeout(r, 0));
		expect(box).toHaveValue('other.example');
		emit({ url: new URL(nav.url.href) }); // the link clicked again
		await vi.waitFor(() => expect(box).toHaveValue('example.com'));
	});

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
