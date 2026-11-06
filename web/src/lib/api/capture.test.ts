import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getCaptureMode,
	fetchCaptureMode,
	getCaptureHealth,
	getCaptureStats,
	getCaptureStatus,
	fetchCaptureStatus,
	toggleCapture,
	updateCaptureSettings,
	captureState,
	formatLossPct,
	packetsLost,
} from './capture';

// S9: one total-loss count (kernel drops + NIC misses) behind every zero-loss claim
describe('packet loss', () => {
	it('counts NIC misses as well as kernel drops', () => {
		expect(packetsLost({ rx_dropped: 0, rx_missed_errors: 50 })).toBe(50);
		expect(packetsLost({ rx_dropped: 7, rx_missed_errors: 3 })).toBe(10);
	});

	it('never rounds a real loss down to 0', () => {
		expect(formatLossPct(0.0000001, 1)).toBe('< 0.01%');
		expect(formatLossPct(0, 0)).toBe('0.00%');
		expect(formatLossPct(0.42, 900)).toBe('0.42%');
	});
});

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

function mockFetchFailure(status = 500): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: false,
			status,
			json: () => Promise.reject(new Error('no body')),
		}),
	);
}

function mockFetchReject(): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockRejectedValue(new Error('network error')),
	);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('capture API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getCaptureMode -------------------------------------------------------

	describe('getCaptureMode', () => {
		it('returns parsed mode on success', async () => {
			mockFetchSuccess({ mode: 'mirror', interface: 'enp2s0' });

			const result = await getCaptureMode();

			expect(result.mode).toBe('mirror');
			expect(result.interface).toBe('enp2s0');
		});

		it('throws on HTTP error instead of guessing bridge', async () => {
			mockFetchFailure(503);

			await expect(getCaptureMode()).rejects.toThrow('HTTP 503');
		});

		it('throws on network error', async () => {
			mockFetchReject();

			await expect(getCaptureMode()).rejects.toThrow();
		});
	});

	// -- fetchCaptureMode -----------------------------------------------------

	describe('fetchCaptureMode', () => {
		it('returns the mode on success', async () => {
			mockFetchSuccess({ mode: 'dhcp_gateway', interface: 'enp1s0' });

			await expect(fetchCaptureMode()).resolves.toEqual({ mode: 'dhcp_gateway', interface: 'enp1s0' });
		});

		it('throws the daemon error instead of guessing bridge', async () => {
			mockFetchSuccess({ error: 'Daemon unreachable: ECONNREFUSED' }, 502);

			await expect(fetchCaptureMode()).rejects.toThrow('Daemon unreachable: ECONNREFUSED');
		});

		it('throws HTTP <status> when the error body is not JSON', async () => {
			mockFetchFailure(503);

			await expect(fetchCaptureMode()).rejects.toThrow('HTTP 503');
		});

		it('throws on a network error', async () => {
			mockFetchReject();

			await expect(fetchCaptureMode()).rejects.toThrow('network error');
		});

		it('throws when the response has no mode', async () => {
			mockFetchSuccess({ error: 'Failed to parse daemon response' });

			await expect(fetchCaptureMode()).rejects.toThrow(/no mode/);
		});
	});

	// -- fetchCaptureStatus ---------------------------------------------------

	describe('fetchCaptureStatus', () => {
		const STATUS = { enabled: true, maxFileSizeMB: 4096, rotateMinutes: 10, containerRunning: true, containerStatus: 'running' };

		it('returns the status on success', async () => {
			mockFetchSuccess(STATUS);

			await expect(fetchCaptureStatus()).resolves.toEqual(STATUS);
		});

		it('throws the daemon error instead of returning a guessed 100 MB', async () => {
			mockFetchSuccess({ error: 'Daemon unreachable: ECONNREFUSED' }, 502);

			await expect(fetchCaptureStatus()).rejects.toThrow('Daemon unreachable: ECONNREFUSED');
		});

		it('throws HTTP <status> when the error body is not JSON', async () => {
			mockFetchFailure(503);

			await expect(fetchCaptureStatus()).rejects.toThrow('HTTP 503');
		});

		it('throws on a network error', async () => {
			mockFetchReject();

			await expect(fetchCaptureStatus()).rejects.toThrow('network error');
		});

		it('throws when the response has no file size', async () => {
			mockFetchSuccess({ enabled: true });

			await expect(fetchCaptureStatus()).rejects.toThrow(/incomplete/);
		});
	});

	// -- getCaptureHealth -----------------------------------------------------

	describe('getCaptureHealth', () => {
		it('returns parsed health on success', async () => {
			const expected = {
				mode: 'mirror',
				status: 'normal',
				capture_interface: 'enp2s0',
				link_up: true,
				promisc_enabled: true,
				issues: [],
			};
			mockFetchSuccess(expected);

			const result = await getCaptureHealth();

			expect(result.mode).toBe('mirror');
			expect(result.status).toBe('normal');
			expect(result.link_up).toBe(true);
			expect(result.issues).toEqual([]);
		});

		it('throws on HTTP error instead of reporting capture down', async () => {
			mockFetchFailure(500);

			await expect(getCaptureHealth()).rejects.toThrow('HTTP 500');
		});

		it('throws on network error', async () => {
			mockFetchReject();

			await expect(getCaptureHealth()).rejects.toThrow();
		});
	});

	// -- getCaptureStats ------------------------------------------------------

	describe('getCaptureStats', () => {
		it('returns parsed stats on success', async () => {
			const expected = {
				capture_interface: 'enp2s0',
				rx_bytes: 1000000,
				tx_bytes: 500000,
				rx_packets: 10000,
				tx_packets: 5000,
				rx_dropped: 5,
				rx_missed_errors: 0,
				link_speed_mbps: 2500,
				drop_rate_pct: 0.05,
			};
			mockFetchSuccess(expected);

			const result = await getCaptureStats();

			expect(result.rx_bytes).toBe(1000000);
			expect(result.rx_dropped).toBe(5);
			expect(result.link_speed_mbps).toBe(2500);
			expect(result.drop_rate_pct).toBe(0.05);
		});

		it('throws on HTTP error instead of reporting zero drops', async () => {
			mockFetchFailure(500);

			await expect(getCaptureStats()).rejects.toThrow('HTTP 500');
		});

		it('throws on network error', async () => {
			mockFetchReject();

			await expect(getCaptureStats()).rejects.toThrow();
		});
	});

	// -- getCaptureStatus -----------------------------------------------------

	describe('getCaptureStatus', () => {
		it('returns status on success', async () => {
			const expected = {
				enabled: true,
				maxFileSizeMB: 100,
				containerRunning: true,
				containerStatus: 'running',
			};
			mockFetchSuccess(expected);

			const result = await getCaptureStatus();

			expect(result.enabled).toBe(true);
			expect(result.maxFileSizeMB).toBe(100);
			expect(result.containerRunning).toBe(true);
			expect(result.containerStatus).toBe('running');
		});

		it('returns defaults on failure', async () => {
			mockFetchReject();

			const result = await getCaptureStatus();

			expect(result.enabled).toBe(true);
			expect(result.maxFileSizeMB).toBe(100);
			expect(result.containerRunning).toBe(false);
			expect(result.containerStatus).toBe('unknown');
		});

		it('maps the failure default to the unknown capture state, not active', async () => {
			mockFetchReject();

			expect(captureState(await getCaptureStatus())).toBe('unknown');
		});
	});

	// -- captureState ---------------------------------------------------------

	describe('captureState', () => {
		const base = { enabled: true, maxFileSizeMB: 100, containerRunning: true, containerStatus: 'running' };

		it('is active only when enabled and the container is running', () => {
			expect(captureState(base)).toBe('active');
		});

		it('is stopped when enabled but the container is not running', () => {
			expect(captureState({ ...base, containerRunning: false, containerStatus: 'exited' })).toBe('stopped');
		});

		it('is stopped when disabled', () => {
			expect(captureState({ ...base, enabled: false, containerRunning: false, containerStatus: 'exited' })).toBe(
				'stopped',
			);
		});

		it('is unknown when the status could not be read', () => {
			expect(captureState(null)).toBe('unknown');
			expect(captureState({ ...base, containerRunning: false, containerStatus: 'unknown' })).toBe('unknown');
		});
	});

	// -- toggleCapture --------------------------------------------------------

	describe('toggleCapture', () => {
		it('sends PUT with {enabled: false}', async () => {
			mockFetchSuccess({
				enabled: false,
				containerRunning: false,
				containerStatus: 'exited',
			});

			const result = await toggleCapture(false);

			expect(result.enabled).toBe(false);
			expect(result.containerRunning).toBe(false);
			expect(result.containerStatus).toBe('exited');

			const callArgs = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
			expect(callArgs[0]).toBe('/api/capture/toggle');
			expect(callArgs[1].method).toBe('PUT');
			const body = JSON.parse(callArgs[1].body);
			expect(body.enabled).toBe(false);
		});

		it('throws on server error', async () => {
			mockFetchFailure(500);

			await expect(toggleCapture(true)).rejects.toThrow();
		});
	});

	// -- updateCaptureSettings ------------------------------------------------

	describe('updateCaptureSettings', () => {
		it('sends PUT with {maxFileSizeMB: 200}', async () => {
			mockFetchSuccess({ maxFileSizeMB: 200, restarted: true });

			const result = await updateCaptureSettings({ maxFileSizeMB: 200 });

			expect(result.maxFileSizeMB).toBe(200);
			expect(result.restarted).toBe(true);

			const callArgs = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
			expect(callArgs[0]).toBe('/api/capture/settings');
			expect(callArgs[1].method).toBe('PUT');
			const body = JSON.parse(callArgs[1].body);
			expect(body.maxFileSizeMB).toBe(200);
		});

		it('throws on validation error', async () => {
			vi.stubGlobal(
				'fetch',
				vi.fn().mockResolvedValue({
					ok: false,
					status: 400,
					json: () =>
						Promise.resolve({
							error: "'maxFileSizeMB' must be between 10 and 10000",
						}),
				}),
			);

			await expect(updateCaptureSettings({ maxFileSizeMB: 5 })).rejects.toThrow(
				"'maxFileSizeMB' must be between 10 and 10000",
			);
		});
	});
});
