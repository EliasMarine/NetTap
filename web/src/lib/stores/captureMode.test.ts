import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { get } from 'svelte/store';

// ---------------------------------------------------------------------------
// Module-level mocks — must be before the import of the module under test
// ---------------------------------------------------------------------------

const mockGetCaptureMode = vi.fn();

vi.mock('$api/capture', () => ({
	getCaptureMode: mockGetCaptureMode,
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('captureMode store', () => {
	beforeEach(() => {
		vi.resetModules();
		mockGetCaptureMode.mockReset();
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	// OLD CODE: it('defaults to bridge', … toBe('bridge') (NET-225: unknown until the daemon answers)
	it('is unknown (null) until the daemon answers', async () => {
		const { captureMode } = await import('./captureMode');
		expect(get(captureMode)).toBeNull();
	});

	it('sets mirror when API returns mirror', async () => {
		mockGetCaptureMode.mockResolvedValue({ mode: 'mirror' });

		const { captureMode, initCaptureMode } = await import('./captureMode');
		await initCaptureMode();

		expect(get(captureMode)).toBe('mirror');
	});

	it('stays bridge when API returns bridge', async () => {
		mockGetCaptureMode.mockResolvedValue({ mode: 'bridge' });

		const { captureMode, initCaptureMode } = await import('./captureMode');
		await initCaptureMode();

		expect(get(captureMode)).toBe('bridge');
	});

	it('sets dhcp_gateway when API returns dhcp_gateway', async () => {
		mockGetCaptureMode.mockResolvedValue({ mode: 'dhcp_gateway' });

		const { captureMode, initCaptureMode } = await import('./captureMode');
		await initCaptureMode();

		expect(get(captureMode)).toBe('dhcp_gateway');
	});

	// OLD CODE: it('maps an unknown mode to bridge', … toBe('bridge') (NET-225: an unknown mode isn't bridge)
	it('leaves an unknown mode unknown', async () => {
		mockGetCaptureMode.mockResolvedValue({ mode: 'something-new' });

		const { captureMode, initCaptureMode } = await import('./captureMode');
		await initCaptureMode();

		expect(get(captureMode)).toBeNull();
	});

	// OLD CODE: it('falls back to bridge on error', … toBe('bridge') (NET-225: a guess would show mirror users bridge warnings)
	it('stays unknown on error', async () => {
		mockGetCaptureMode.mockRejectedValue(new Error('Network error'));

		const { captureMode, initCaptureMode } = await import('./captureMode');
		await initCaptureMode();

		expect(get(captureMode)).toBeNull();
	});

	// NET-225: a failed first request (daemon restarting) must not hide the mode for the whole session
	it('asks again after a failure, and stops asking once answered', async () => {
		mockGetCaptureMode.mockRejectedValueOnce(new Error('HTTP 503')).mockResolvedValue({ mode: 'bridge' });

		const { captureMode, initCaptureMode } = await import('./captureMode');
		await initCaptureMode();
		expect(get(captureMode)).toBeNull();
		await initCaptureMode();
		expect(get(captureMode)).toBe('bridge');
		await initCaptureMode();
		expect(mockGetCaptureMode).toHaveBeenCalledTimes(2);
	});

	it('shares one request between concurrent callers', async () => {
		mockGetCaptureMode.mockResolvedValue({ mode: 'mirror' });

		const { captureMode, initCaptureMode } = await import('./captureMode');
		await Promise.all([initCaptureMode(), initCaptureMode(), initCaptureMode()]);

		expect(mockGetCaptureMode).toHaveBeenCalledTimes(1);
		expect(get(captureMode)).toBe('mirror');
	});

	it('only initializes once', async () => {
		mockGetCaptureMode.mockResolvedValue({ mode: 'mirror' });

		const { initCaptureMode } = await import('./captureMode');
		await initCaptureMode();
		await initCaptureMode();
		await initCaptureMode();

		expect(mockGetCaptureMode).toHaveBeenCalledTimes(1);
	});
});
