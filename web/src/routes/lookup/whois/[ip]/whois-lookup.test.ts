import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { readable, get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/lookup/whois/8.8.8.8'), params: { ip: '8.8.8.8' } }),
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const record = (orgname: string, raw = 'OrgName: ' + orgname) => ({ ip: '8.8.8.8', raw, parsed: { orgname, cidr: '8.8.8.0/24' }, error: null });
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });

function deferred<T>() {
	let resolve!: (v: T) => void;
	const promise = new Promise<T>((r) => (resolve = r));
	return { promise, resolve };
}

afterEach(() => vi.unstubAllGlobals());

describe('WHOIS lookup page', () => {
	it('shows the loading state while the lookup is pending', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		expect(screen.getByRole('status')).toHaveTextContent('Looking up WHOIS data');
	});

	it('shows the parsed fields and the raw reply behind a toggle', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => ok(record('Google LLC'))));
		render(Page);
		expect(await screen.findByText('Google LLC')).toBeInTheDocument();
		expect(screen.getByText('8.8.8.0/24')).toBeInTheDocument();

		const toggle = screen.getByRole('button', { name: 'Show raw WHOIS output' });
		expect(toggle).toHaveAttribute('aria-expanded', 'false');
		await fireEvent.click(toggle);
		expect(screen.getByText('OrgName: Google LLC')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Hide raw WHOIS output' })).toHaveAttribute('aria-expanded', 'true');
	});

	it('says so when the reply has no parsed fields', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => ok({ ip: '8.8.8.8', raw: '', parsed: {}, error: null })));
		render(Page);
		expect(await screen.findByText('No parsed WHOIS fields available.')).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: /raw WHOIS output/ })).not.toBeInTheDocument();
	});

	it('shows the error state when the request fails', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) })));
		render(Page);
		expect(await screen.findByRole('heading', { name: 'Lookup failed' })).toBeInTheDocument();
		expect(screen.getByRole('alert')).toHaveTextContent('Lookup failed');
	});
});

describe('WHOIS lookup page refresh contract', () => {
	it('reports ok after a lookup and failed when the daemon reports an error', async () => {
		const fetch = vi.fn(async () => ok(record('Google LLC')));
		vi.stubGlobal('fetch', fetch);
		render(Page);
		await screen.findByText('Google LLC');
		expect(get(pageRefresh)).toMatchObject({ available: true, status: 'ok' });

		fetch.mockImplementationOnce(async () => ok({ ...record('x'), error: 'whois: connection refused' }));
		expect(await refreshPage()).toBe('failed');
		expect(screen.getByText('whois: connection refused')).toBeInTheDocument();
	});

	it('drops an older response that lands after a newer one', async () => {
		const slow = deferred<unknown>();
		const fast = deferred<unknown>();
		vi.stubGlobal('fetch', vi.fn().mockReturnValueOnce(slow.promise).mockReturnValueOnce(fast.promise));
		render(Page);
		const second = refreshPage();
		fast.resolve(ok(record('New Org')));
		expect(await second).toBe('ok');
		slow.resolve(ok(record('Old Org')));
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.getByText('New Org')).toBeInTheDocument();
		expect(screen.queryByText('Old Org')).not.toBeInTheDocument();
	});

	it('unregisters when the page goes', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		const { unmount } = render(Page);
		expect(get(pageRefresh).available).toBe(true);
		unmount();
		expect(get(pageRefresh).available).toBe(false);
	});
});
