import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { readable, get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';
import { expectNoNestedInteractive } from '../../../tests/nested-interactive';

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
		// OLD CODE START — NET-237 (GEO-2): a city centre to four decimals with a coordinate pin
		// expect(screen.getByRole('link', { name: /37\.4056, -122\.0775/ })).toHaveAttribute(
		// 	'href',
		// 	'https://www.google.com/maps/search/?api=1&query=37.4056,-122.0775',
		// );
		// OLD CODE END
		expect(screen.getByRole('link', { name: /37\.4, -122\.1/ })).toHaveAttribute(
			'href',
			'https://www.google.com/maps/search/?api=1&query=Mountain%20View%2C%20United%20States',
		);
		expect(screen.getAllByText(/city estimate, accuracy unknown/).length).toBeGreaterThan(0);
		expect(screen.getByTitle('GeoIP location map').getAttribute('src')).not.toContain('marker=');
		expect(screen.getByTitle('GeoIP location map')).toBeInTheDocument();
		// OLD CODE START — NET-160: ?filter= links the Connections page never read
		// expect(screen.getByRole('link', { name: 'Filter connections to' })).toHaveAttribute('href', '/connections?filter=ip.dst==8.8.8.8');
		// OLD CODE END
		expect(screen.getByRole('link', { name: 'Connections with this address' })).toHaveAttribute('href', '/connections?ip=8.8.8.8');
		expect(screen.getByRole('link', { name: 'Open address page' })).toHaveAttribute('href', '/address/8.8.8.8');
		expect(screen.queryByRole('link', { name: 'View device details' })).not.toBeInTheDocument();
		expectNoNestedInteractive(document.body);
	});

	it('offers the device page for a LAN address', async () => {
		const lan = { version: 'v', subnets: ['192.168.1.0/24'], source: 'env', ipv6: 'not-lan' };
		vi.stubGlobal('fetch', vi.fn(async (url: string) => (url === '/api/network/lan' ? okJson(lan) : okJson(geo('Home', { ip: '192.168.1.5', is_private: true })))));
		render(Page);
		await screen.findByText('Home');
		await vi.waitFor(() => expect(screen.getByRole('link', { name: 'View device details' })).toHaveAttribute('href', '/devices/192.168.1.5'));
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
		// NET-160: the action links fetch the LAN policy; only the lookups take the sequence
		// OLD CODE: vi.stubGlobal('fetch', vi.fn((url: string) => (url === '/api/network/lan' ? Promise.resolve({ ok: false, status: 404, json: async () => ({}) }) : fetch(url)))); (NET-237: the installed database loads beside the lookup)
		const aside = (url: string) => url === '/api/network/lan' || url === '/api/system/versions';
		vi.stubGlobal('fetch', vi.fn((url: string) => (aside(url) ? Promise.resolve(url === '/api/network/lan' ? { ok: false, status: 404, json: async () => ({}) } : okJson({ versions: [] })) : fetch(url))));
		const { unmount } = render(Page);
		await screen.findByText('First');
		// OLD CODE: expect(get(pageRefresh).status).toBe('ok'); (NET-237: the answer shows before the database date lands)
		await vi.waitFor(() => expect(get(pageRefresh).status).toBe('ok'));

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

// NET-237 (GEO-2, GEO-3, GEO-4, P3 anycast)
describe('GeoIP Lookup Page — source, age and precision', () => {
	afterEach(() => vi.unstubAllGlobals());

	const versions = {
		versions: [
			{ name: 'zeek', category: 'docker', current_version: '9.0.1', install_type: 'docker', last_checked: '', status: 'ok', details: {} },
			{ name: 'geoip-db', category: 'database', current_version: '2026-10-28', install_type: 'builtin', last_checked: '', status: 'ok', details: { source: 'Logstash geoip filter (bundled)' } },
		],
		last_scan: '',
		count: 2,
	};
	const stub = (answer: unknown, versionsReply: unknown = okJson(versions)) =>
		vi.stubGlobal('fetch', vi.fn(async (url: string) => (url === '/api/system/versions' ? versionsReply : okJson(answer))));

	it('names a stored answer as such, with when the traffic was seen and the installed file apart', async () => {
		stub(geo('Berlin', { source: 'traffic', seen_at: '2026-09-01T10:00:00Z', anycast: false }));
		render(Page);
		expect(await screen.findByText(/^Malcolm's GeoLite2 lookup, stored with traffic seen 1 Sept, \d\d:\d\d\. The database version used then isn't recorded\.$/)).toBeInTheDocument();
		expect(await screen.findByText(/^GeoLite2 file dated 2026-10-28, installed now · Logstash geoip filter \(bundled\)$/)).toBeInTheDocument();
		expect(get(pageRefresh).status).toBe('ok');
	});

	it('says when the installed database date could not be read, and keeps the answer', async () => {
		stub(geo('Berlin', { source: 'traffic', seen_at: null, anycast: false }), { ok: false, status: 500, json: async () => ({}) });
		render(Page);
		expect(await screen.findByText("Couldn't read the installed database date")).toBeInTheDocument();
		expect(screen.getByText('Berlin')).toBeInTheDocument();
		expect(get(pageRefresh).status).toBe('partial');
	});

	it('names the built-in list, and gives a country-only answer no local position or map', async () => {
		stub(geo('', { city: null, latitude: 37.751, longitude: -97.822, source: 'builtin', anycast: false }));
		render(Page);
		expect(await screen.findByText("NetTap's built-in list of well-known services, not a database lookup")).toBeInTheDocument();
		expect(screen.getByText('Country-level estimate, no local position')).toBeInTheDocument();
		expect(screen.queryByText(/37\.7/)).not.toBeInTheDocument();
		expect(screen.queryByTitle('GeoIP location map')).not.toBeInTheDocument();
		expect(screen.queryByText('Installed database')).not.toBeInTheDocument();
	});

	it('says anycast has no one location, with no coordinates or map', async () => {
		stub(geo('', { ip: '1.1.1.1', city: null, latitude: null, longitude: null, source: 'traffic', seen_at: null, anycast: true }));
		render(Page);
		expect(await screen.findByText('Anycast: location varies')).toBeInTheDocument();
		expect(screen.queryByTitle('GeoIP location map')).not.toBeInTheDocument();
	});

	it("shows the daemon's 502 as a failed lookup, not an answer", async () => {
		stub(undefined);
		vi.stubGlobal('fetch', vi.fn(async (url: string) => (url === '/api/system/versions' ? okJson(versions) : { ok: false, status: 502, json: async () => ({ error: "Couldn't look up this address" }) })));
		render(Page);
		expect(await screen.findByText('Lookup failed')).toBeInTheDocument();
		expect(screen.queryByText('Source')).not.toBeInTheDocument();
	});
});

describe('GeoIP Lookup Page — a slow version scan', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('shows the answer without waiting for the installed database date', async () => {
		vi.stubGlobal('fetch', vi.fn((url: string) => (url === '/api/system/versions' ? new Promise(() => {}) : Promise.resolve(okJson(geo('Berlin', { source: 'traffic', seen_at: null, anycast: false }))))));
		render(Page);
		expect(await screen.findByText('Berlin')).toBeInTheDocument();
		expect(screen.getByText('Not reported')).toBeInTheDocument();
	});
});
