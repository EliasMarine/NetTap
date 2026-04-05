import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getCaptureMode,
	getCaptureHealth,
	getCaptureStats,
	getCaptureStatus,
	toggleCapture,
	updateCaptureSettings,
} from './capture';

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

		it('returns bridge fallback on HTTP error', async () => {
			mockFetchFailure(503);

			const result = await getCaptureMode();

			expect(result.mode).toBe('bridge');
			expect(result.interface).toBe('');
		});

		it('returns bridge fallback on network error', async () => {
			mockFetchReject();

			const result = await getCaptureMode();

			expect(result.mode).toBe('bridge');
			expect(result.interface).toBe('');
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

		it('returns down fallback on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getCaptureHealth();

			expect(result.status).toBe('down');
			expect(result.link_up).toBe(false);
			expect(result.issues).toHaveLength(1);
		});

		it('returns down fallback on network error', async () => {
			mockFetchReject();

			const result = await getCaptureHealth();

			expect(result.status).toBe('down');
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

		it('returns zeros on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getCaptureStats();

			expect(result.rx_bytes).toBe(0);
			expect(result.tx_bytes).toBe(0);
			expect(result.rx_packets).toBe(0);
			expect(result.rx_dropped).toBe(0);
		});

		it('returns zeros on network error', async () => {
			mockFetchReject();

			const result = await getCaptureStats();

			expect(result.rx_bytes).toBe(0);
			expect(result.capture_interface).toBe('');
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
