import { describe, it, expect, vi, afterEach } from 'vitest';
import { getLanPolicy } from './network';

describe('getLanPolicy', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('returns the daemon policy', async () => {
		const body = { version: 'abc', subnets: ['192.168.1.0/24'], source: 'env', ipv6: 'not-lan' };
		const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => body }));
		vi.stubGlobal('fetch', fetchMock);
		await expect(getLanPolicy()).resolves.toEqual(body);
		expect(fetchMock).toHaveBeenCalledWith('/api/network/lan');
	});

	it('throws on an HTTP error, so links stay on the address page', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })));
		await expect(getLanPolicy()).rejects.toThrow('HTTP 404');
	});

	it('throws on a malformed reply instead of guessing a policy', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ version: 'x', subnets: [1] }) })));
		await expect(getLanPolicy()).rejects.toThrow('malformed');
	});
});
