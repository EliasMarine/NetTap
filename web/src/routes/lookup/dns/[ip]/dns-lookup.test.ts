import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { readable, get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/lookup/dns/8.8.8.8'), params: { ip: '8.8.8.8' } }),
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const record = (hostname: string | null) => ({ ip: '8.8.8.8', hostname, aliases: [], addresses: ['8.8.8.8'], error: null });
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });

function deferred<T>() {
	let resolve!: (v: T) => void;
	const promise = new Promise<T>((r) => (resolve = r));
	return { promise, resolve };
}

afterEach(() => vi.unstubAllGlobals());

describe('DNS lookup page', () => {
	it('shows the loading state while the lookup is pending', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		expect(screen.getByRole('status')).toHaveTextContent('Looking up DNS records');
	});

	it('shows the result as facts and links to the related lookups', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => ok(record('dns.google'))));
		render(Page);
		expect(await screen.findByText('dns.google')).toBeInTheDocument();
		expect(screen.getByText('Reverse DNS (PTR)')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'WHOIS lookup' })).toHaveAttribute('href', '/lookup/whois/8.8.8.8');
		expect(screen.getByRole('heading', { level: 1, name: 'DNS lookup' })).toBeInTheDocument();
	});

	it('says so when there is no reverse record', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => ok(record(null))));
		render(Page);
		expect(await screen.findByText('No reverse DNS record')).toBeInTheDocument();
	});

	it('shows the error state when the request fails, and the daemon error when it reports one', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) })));
		const first = render(Page);
		expect(await screen.findByRole('heading', { name: 'Lookup failed' })).toBeInTheDocument();
		expect(screen.getByRole('alert')).toHaveTextContent('Lookup failed');
		first.unmount();

		vi.stubGlobal('fetch', vi.fn(async () => ok({ ...record(null), error: 'Resolver timed out' })));
		render(Page);
		expect(await screen.findByText('Resolver timed out')).toBeInTheDocument();
	});
});

describe('DNS lookup page refresh contract', () => {
	it('reports ok after a lookup and failed after a failed one', async () => {
		const fetch = vi.fn(async () => ok(record('dns.google')));
		vi.stubGlobal('fetch', fetch);
		render(Page);
		await screen.findByText('dns.google');
		expect(get(pageRefresh)).toMatchObject({ available: true, status: 'ok' });

		fetch.mockImplementationOnce(async () => ({ ok: false, status: 502, json: async () => ({}) }) as never);
		expect(await refreshPage()).toBe('failed');
		expect(get(pageRefresh).status).toBe('failed');
	});

	it('drops an older response that lands after a newer one', async () => {
		const slow = deferred<unknown>();
		const fast = deferred<unknown>();
		vi.stubGlobal('fetch', vi.fn().mockReturnValueOnce(slow.promise).mockReturnValueOnce(fast.promise));
		render(Page);
		const second = refreshPage();
		fast.resolve(ok(record('new.example')));
		expect(await second).toBe('ok');
		slow.resolve(ok(record('old.example')));
		expect(await screen.findByText('new.example')).toBeInTheDocument();
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.queryByText('old.example')).not.toBeInTheDocument();
	});

	it('unregisters when the page goes', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		const { unmount } = render(Page);
		expect(get(pageRefresh).available).toBe(true);
		unmount();
		expect(get(pageRefresh).available).toBe(false);
	});
});
