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

	it('defaults to bridge', async () => {
		const { captureMode } = await import('./captureMode');
		expect(get(captureMode)).toBe('bridge');
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

	it('maps an unknown mode to bridge', async () => {
		mockGetCaptureMode.mockResolvedValue({ mode: 'something-new' });

		const { captureMode, initCaptureMode } = await import('./captureMode');
		await initCaptureMode();

		expect(get(captureMode)).toBe('bridge');
	});

	it('falls back to bridge on error', async () => {
		mockGetCaptureMode.mockRejectedValue(new Error('Network error'));

		const { captureMode, initCaptureMode } = await import('./captureMode');
		await initCaptureMode();

		expect(get(captureMode)).toBe('bridge');
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
