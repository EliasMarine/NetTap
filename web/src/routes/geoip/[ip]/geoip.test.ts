import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { readable } from 'svelte/store';
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
		expect(await screen.findByText('Lookup Failed')).toBeInTheDocument();
		expect(screen.queryByText('Unknown')).not.toBeInTheDocument();
	});
});
