import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { readable, get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/geoip/8.8.8.8'), params: { ip: '8.8.8.8' } }),
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

describe('GeoIP Lookup Page', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});
});

// #96: a failed lookup came back as country "Unknown" and showed as a result
describe('GeoIP Lookup Page — failed lookup', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('says the lookup failed instead of showing country "Unknown"', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })));
		render(Page);
		expect(await screen.findByText('Lookup failed')).toBeInTheDocument();
		expect(screen.queryByText('Unknown')).not.toBeInTheDocument();
	});
});

const geo = (city: string, extra: Record<string, unknown> = {}) => ({
	ip: '8.8.8.8',
	country: 'United States',
	country_code: 'US',
	city,
	latitude: 37.4056,
	longitude: -122.0775,
	asn: 15169,
	organization: 'Google LLC',
	is_private: false,
	...extra,
});
const okJson = (body: unknown) => ({ ok: true, status: 200, json: async () => body });

describe('GeoIP Lookup Page — states', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('shows the loading state while the lookup is pending', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		expect(screen.getByRole('status')).toHaveTextContent('Looking up the location');
	});

	it('shows the location as facts, with no flag emoji, and the map', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => okJson(geo('Mountain View'))));
		render(Page);
		expect(await screen.findByText('Mountain View')).toBeInTheDocument();
		expect(screen.getByText('AS15169')).toBeInTheDocument();
		expect(screen.getByText('(US)')).toBeInTheDocument();
		expect(document.body.textContent).not.toMatch(/\p{Regional_Indicator}/u);
		expect(screen.getByRole('link', { name: /37\.4056, -122\.0775/ })).toHaveAttribute(
			'href',
			'https://www.google.com/maps/search/?api=1&query=37.4056,-122.0775',
		);
		expect(screen.getByTitle('GeoIP location map')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Filter connections to' })).toHaveAttribute('href', '/connections?filter=ip.dst==8.8.8.8');
	});

	it('leaves the map out when there are no coordinates', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => okJson(geo('Nowhere', { latitude: null, longitude: null }))));
		render(Page);
		await screen.findByText('Nowhere');
		expect(screen.queryByTitle('GeoIP location map')).not.toBeInTheDocument();
	});
});

describe('GeoIP Lookup Page — refresh contract', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('reports ok, then failed, and drops a stale response', async () => {
		let resolveSlow!: (v: unknown) => void;
		const fetch = vi
			.fn()
			.mockResolvedValueOnce(okJson(geo('First')))
			.mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
			.mockReturnValueOnce(new Promise((r) => (resolveSlow = r)))
			.mockResolvedValueOnce(okJson(geo('Newest')));
		vi.stubGlobal('fetch', fetch);
		const { unmount } = render(Page);
		await screen.findByText('First');
		expect(get(pageRefresh).status).toBe('ok');

		expect(await refreshPage()).toBe('failed');
		expect(screen.getByText('Lookup failed')).toBeInTheDocument();

		const stale = refreshPage();
		expect(await refreshPage()).toBe('ok');
		resolveSlow(okJson(geo('Stale')));
		expect(await stale).toBe('skipped');
		expect(screen.getByText('Newest')).toBeInTheDocument();
		expect(screen.queryByText('Stale')).not.toBeInTheDocument();

		unmount();
		expect(get(pageRefresh).available).toBe(false);
	});
});
