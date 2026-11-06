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
	lossWords,
	windowWords,
	type LossWindow,
} from './capture';

// S9: one total-loss count (kernel drops + NIC misses) behind every zero-loss claim
describe('packet loss', () => {
	// OLD CODE START — NET-167: packetsLost is gone; the daemon's loss_window counts NIC misses
	// it('counts NIC misses as well as kernel drops', () => {
	// 	expect(packetsLost({ rx_dropped: 0, rx_missed_errors: 50 })).toBe(50);
	// 	expect(packetsLost({ rx_dropped: 7, rx_missed_errors: 3 })).toBe(10);
	// });
	// OLD CODE END

	it('never rounds a real loss down to 0', () => {
		expect(formatLossPct(0.0000001, 1)).toBe('< 0.01%');
		expect(formatLossPct(0, 0)).toBe('0.00%');
		expect(formatLossPct(0.42, 900)).toBe('0.42%');
	});
});

// NET-167: loss over a recent window, not since the counters reset
const lossWindow = (window: LossWindow['window'], state: LossWindow['state'] = 'ok'): LossWindow => ({
	state,
	interface: 'br0',
	window,
	cumulative: { arrived: 5_000_000, lost: 900, drop_rate_pct: 0.018 },
});

describe('windowWords', () => {
	it('says whole minutes rounded down, so the span is never overstated', () => {
		expect(windowWords(3480)).toBe('last 58 min');
		expect(windowWords(3539)).toBe('last 58 min');
		expect(windowWords(60)).toBe('last 1 min');
		expect(windowWords(3600)).toBe('last 60 min');
	});
});

describe('lossWords', () => {
	it('reads a loss over 0.1 % as failing, with the window and the count', () => {
		expect(lossWords(lossWindow({ seconds: 3480, arrived: 293_810, lost: 1_234, drop_rate_pct: 0.42 }))).toEqual({
			status: 'failing',
			detail: '0.42% lost in the last 58 min · 1,234 packets',
			pct: '0.42%',
		});
	});

	it('reads a loss at or under 0.1 % as ok, and a tiny loss never as 0', () => {
		expect(lossWords(lossWindow({ seconds: 3480, arrived: 1_000_000, lost: 1_000, drop_rate_pct: 0.1 })).status).toBe('ok');
		expect(lossWords(lossWindow({ seconds: 3480, arrived: 98_765, lost: 12, drop_rate_pct: 0.00001 }))).toEqual({
			status: 'ok',
			detail: '< 0.01% lost in the last 58 min · 12 packets',
			pct: '< 0.01%',
		});
	});

	it('says no packets were lost, with how many arrived', () => {
		expect(lossWords(lossWindow({ seconds: 3480, arrived: 98_765, lost: 0, drop_rate_pct: 0 }))).toEqual({
			status: 'ok',
			detail: 'No packets lost in the last 58 min · 98,765 received',
			pct: '0.00%',
		});
	});

	it('never shows a percentage when nothing arrived', () => {
		expect(lossWords(lossWindow({ seconds: 3480, arrived: 0, lost: 0, drop_rate_pct: null }))).toEqual({
			status: 'unknown',
			detail: 'No packets in the last 58 min',
			pct: null,
		});
	});

	it('says when it is still measuring, or the counters are unavailable', () => {
		expect(lossWords(lossWindow(null, 'measuring'))).toEqual({ status: 'unknown', detail: 'Measuring recent loss…', pct: null });
		expect(lossWords(lossWindow(null, 'unavailable'))).toEqual({ status: 'unknown', detail: 'Loss counters unavailable', pct: null });
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

		// NET-167: a missing or malformed loss_window reads as unavailable, never as 0 loss
		const UNAVAILABLE = { state: 'unavailable', interface: null, window: null, cumulative: null };
		const GOOD = {
			state: 'ok',
			interface: 'br0',
			window: { seconds: 3480, arrived: 98_765, lost: 12, drop_rate_pct: 0.01215 },
			cumulative: { arrived: 123_456_789, lost: 345, drop_rate_pct: 0.000279 },
		};
		const lossWindowOf = async (loss_window: unknown) => {
			mockFetchSuccess({ capture_interface: 'br0', drop_rate_pct: 0, loss_window });
			return (await getCaptureStats()).loss_window;
		};

		it('keeps a well-formed loss_window, including measuring and a null rate', async () => {
			expect(await lossWindowOf(GOOD)).toEqual(GOOD);
			const measuring = { state: 'measuring', interface: 'br0', window: null, cumulative: { arrived: 0, lost: 0, drop_rate_pct: null } };
			expect(await lossWindowOf(measuring)).toEqual(measuring);
		});

		it('reads an old daemon with no loss_window as unavailable', async () => {
			mockFetchSuccess({ capture_interface: 'br0', rx_dropped: 0, rx_missed_errors: 0, drop_rate_pct: 0 });
			const result = await getCaptureStats();
			expect(result.loss_window).toEqual(UNAVAILABLE);
			expect(result.capture_interface).toBe('br0');
		});

		it('reads a malformed window as unavailable', async () => {
			for (const window of [
				{ ...GOOD.window, lost: '12' },
				{ ...GOOD.window, arrived: -1 },
				{ ...GOOD.window, drop_rate_pct: undefined },
				{ ...GOOD.window, seconds: 30 },
				{ ...GOOD.window, seconds: undefined },
				null, // state ok needs a window
				'3480',
			]) {
				expect(await lossWindowOf({ ...GOOD, window })).toEqual(UNAVAILABLE);
			}
			// a window that state says isn't there
			expect(await lossWindowOf({ ...GOOD, state: 'measuring' })).toEqual(UNAVAILABLE);
		});

		it('reads a malformed cumulative block as unavailable', async () => {
			for (const cumulative of [{ arrived: 10, lost: Number.NaN, drop_rate_pct: null }, { arrived: 10 }, undefined, 0]) {
				expect(await lossWindowOf({ ...GOOD, cumulative })).toEqual(UNAVAILABLE);
			}
		});

		it('reads an unknown state or a non-string interface as unavailable', async () => {
			expect(await lossWindowOf({ ...GOOD, state: 'fine' })).toEqual(UNAVAILABLE);
			expect(await lossWindowOf({ ...GOOD, interface: 7 })).toEqual(UNAVAILABLE);
			expect(await lossWindowOf('ok')).toEqual(UNAVAILABLE);
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
