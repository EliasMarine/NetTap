import { describe, it, expect, vi, afterEach } from 'vitest';
import { getUnifiStatus, getUnifiDnsPolicies, getUnifiVpn } from './unifi';

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

function mockFetchSuccess(body: unknown, status = 200): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: status >= 200 && status < 300,
			status,
			json: () => Promise.resolve(body),
		}),
	);
}

function mockFetchReject(): void {
	vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network error')));
}

/** Shape of daemon/services/unifi_integration.py get_status() */
function daemonStatus(overrides: Record<string, unknown> = {}) {
	return {
		configured: true,
		controller_url: 'https://192.168.1.1',
		site_id: 'site-1',
		connected: true,
		last_poll_time: 1793300000.5,
		cache_counts: { clients: 12, devices: 3 },
		cached_device_count: 0,
		cache_age_seconds: 4.2,
		last_error: null,
		...overrides,
	};
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('unifi API client', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	describe('getUnifiStatus', () => {
		it('passes through connected, site_id and last_poll_time', async () => {
			mockFetchSuccess(daemonStatus());

			const status = await getUnifiStatus();

			expect(status.connected).toBe(true);
			expect(status.site_id).toBe('site-1');
			expect(status.last_poll_time).toBe(1793300000.5);
			expect(status.cache_counts).toEqual({ clients: 12, devices: 3 });
			expect(fetch).toHaveBeenCalledWith('/api/integrations/unifi/status');
		});

		it('defaults connected/site_id for an older daemon that omits them', async () => {
			const old = daemonStatus();
			delete (old as Record<string, unknown>).connected;
			delete (old as Record<string, unknown>).site_id;
			mockFetchSuccess(old);

			const status = await getUnifiStatus();

			expect(status.connected).toBe(false);
			expect(status.site_id).toBeNull();
			expect(status.configured).toBe(true);
		});

		it('treats an empty site_id as no site', async () => {
			mockFetchSuccess(daemonStatus({ site_id: '' }));
			expect((await getUnifiStatus()).site_id).toBeNull();
		});

		it('returns a disconnected default on HTTP error', async () => {
			mockFetchSuccess({ error: 'boom' }, 500);
			const status = await getUnifiStatus();
			expect(status).toMatchObject({ configured: false, connected: false, last_poll_time: 0 });
		});

		it('returns a disconnected default on network error', async () => {
			mockFetchReject();
			const status = await getUnifiStatus();
			expect(status).toMatchObject({ configured: false, connected: false, site_id: null });
		});
	});

	describe('getUnifiDnsPolicies', () => {
		it('reads the daemon `policies` key', async () => {
			mockFetchSuccess({ policies: [{ id: 'p1', name: 'Block ads', enabled: true }] });

			const policies = await getUnifiDnsPolicies();

			expect(policies).toHaveLength(1);
			expect(policies[0].name).toBe('Block ads');
			expect(fetch).toHaveBeenCalledWith('/api/integrations/unifi/dns-policies');
		});

		it('returns [] on HTTP error', async () => {
			mockFetchSuccess({ error: 'UniFi not configured' }, 400);
			expect(await getUnifiDnsPolicies()).toEqual([]);
		});
	});

	describe('getUnifiVpn', () => {
		it('reads the daemon `tunnels` key', async () => {
			mockFetchSuccess({ tunnels: [{ id: 't1', name: 'Office', type: 'wireguard', status: 'up' }] });

			const tunnels = await getUnifiVpn();

			expect(tunnels).toHaveLength(1);
			expect(tunnels[0].name).toBe('Office');
			expect(fetch).toHaveBeenCalledWith('/api/integrations/unifi/vpn');
		});

		it('returns [] on network error', async () => {
			mockFetchReject();
			expect(await getUnifiVpn()).toEqual([]);
		});
	});
});
