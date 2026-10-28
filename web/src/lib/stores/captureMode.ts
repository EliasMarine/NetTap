/**
 * Singleton store for the current capture mode (bridge or mirror).
 * Fetched once at app startup from /api/capture/mode.
 * Used by drawer components to conditionally show/hide "Block IP" actions.
 */
import { writable } from 'svelte/store';
import { getCaptureMode } from '$api/capture';

export const captureMode = writable<'bridge' | 'mirror'>('bridge');

let initialized = false;

export async function initCaptureMode(): Promise<void> {
	if (initialized) return;
	initialized = true;

	try {
		const result = await getCaptureMode();
		captureMode.set(result.mode === 'mirror' ? 'mirror' : 'bridge');
	} catch {
		// Fallback to bridge — safe default
	}
}
