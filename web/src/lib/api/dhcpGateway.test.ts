import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getDhcpPreflight,
	enableDhcpGateway,
	disableDhcpGateway,
	getDhcpStatus,
	DhcpGatewayError,
} from './dhcpGateway';

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

function mockFetch(body: unknown, status = 200): ReturnType<typeof vi.fn> {
	const fn = vi.fn().mockResolvedValue({
		ok: status >= 200 && status < 300,
		status,
		json: () => Promise.resolve(body),
	});
	vi.stubGlobal('fetch', fn);
	return fn;
}

function mockFetchNoBody(status: number): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: false,
			status,
			json: () => Promise.reject(new Error('no body')),
		}),
	);
}

async function caught(p: Promise<unknown>): Promise<DhcpGatewayError> {
	try {
		await p;
	} catch (e) {
		return e as DhcpGatewayError;
	}
	throw new Error('expected a rejection');
}

const STATUS = {
	interface: 'enp1s0',
	subnet: '10.77.0.0/24',
	gateway_ip: '10.77.0.1',
	upstream: { address: '192.168.1.50/24', gateway: '192.168.1.1' },
	routing_active: true,
	dhcp_enabled: true,
	dhcp_server_running: true,
	leases: [],
	issues: [],
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('dhcpGateway API client', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	describe('URLs and methods', () => {
		it('getDhcpPreflight GETs /api/capture/dhcp/preflight', async () => {
			const fn = mockFetch({ ready: true, checks: [] });

			const result = await getDhcpPreflight();

			expect(result.ready).toBe(true);
			expect(fn.mock.calls[0][0]).toBe('/api/capture/dhcp/preflight');
			expect(fn.mock.calls[0][1]).toBeUndefined();
		});

		it('getDhcpStatus GETs /api/capture/dhcp/status', async () => {
			const fn = mockFetch(STATUS);

			const result = await getDhcpStatus();

			expect(result.dhcp_server_running).toBe(true);
			expect(fn.mock.calls[0][0]).toBe('/api/capture/dhcp/status');
		});

		it('enableDhcpGateway POSTs {confirm: true}', async () => {
			const fn = mockFetch(STATUS);

			const result = await enableDhcpGateway();

			expect(result.routing_active).toBe(true);
			const [url, init] = fn.mock.calls[0];
			expect(url).toBe('/api/capture/dhcp/enable');
			expect(init.method).toBe('POST');
			expect(init.headers['Content-Type']).toBe('application/json');
			expect(JSON.parse(init.body)).toEqual({ confirm: true });
		});

		it('disableDhcpGateway POSTs to /api/capture/dhcp/disable', async () => {
			const fn = mockFetch({ ...STATUS, dhcp_enabled: false });

			const result = await disableDhcpGateway();

			expect(result.dhcp_enabled).toBe(false);
			expect(fn.mock.calls[0][0]).toBe('/api/capture/dhcp/disable');
			expect(fn.mock.calls[0][1].method).toBe('POST');
		});
	});

	describe('errors', () => {
		it('throws the daemon error text', async () => {
			mockFetch({ error: 'Capture mode is not dhcp_gateway' }, 409);

			const err = await caught(getDhcpStatus());

			expect(err).toBeInstanceOf(DhcpGatewayError);
			expect(err.message).toBe('Capture mode is not dhcp_gateway');
			expect(err.status).toBe(409);
			expect(err.checks).toBeUndefined();
		});

		it('falls back to HTTP <status> without a JSON body', async () => {
			mockFetchNoBody(502);

			const err = await caught(getDhcpPreflight());

			expect(err.message).toBe('HTTP 502');
			expect(err.status).toBe(502);
		});

		it('falls back to HTTP <status> when error is empty', async () => {
			mockFetch({ error: '' }, 500);

			const err = await caught(disableDhcpGateway());

			expect(err.message).toBe('HTTP 500');
		});

		it('attaches checks from a 409 enable refusal', async () => {
			const checks = [
				{ name: 'no_other_dhcp', passed: false, blocking: true, message: "Your router's DHCP server is still on (192.168.1.1)." },
			];
			mockFetch({ error: 'Preflight failed', checks }, 409);

			const err = await caught(enableDhcpGateway());

			expect(err.message).toBe('Preflight failed');
			expect(err.checks).toEqual(checks);
		});

		it('ignores checks on non-409 errors', async () => {
			mockFetch({ error: 'Apply failed', checks: [{ name: 'x' }] }, 500);

			const err = await caught(enableDhcpGateway());

			expect(err.message).toBe('Apply failed');
			expect(err.checks).toBeUndefined();
		});

		it('propagates network errors', async () => {
			vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network error')));

			await expect(getDhcpStatus()).rejects.toThrow('network error');
		});
	});
});
