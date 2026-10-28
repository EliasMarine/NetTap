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
