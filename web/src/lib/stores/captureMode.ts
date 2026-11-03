/**
 * Singleton store for the current capture mode (bridge, mirror or dhcp_gateway).
 * Fetched once at app startup from /api/capture/mode.
 * Used by drawer components to conditionally show/hide "Block IP" actions.
 */
import { writable } from 'svelte/store';
import { getCaptureMode } from '$api/capture';

// OLD CODE START — 2026-10-30: store type gains 'dhcp_gateway' for DHCP gateway capture mode
// export const captureMode = writable<'bridge' | 'mirror'>('bridge');
// OLD CODE END
export type StoreCaptureMode = 'bridge' | 'mirror' | 'dhcp_gateway';

export const captureMode = writable<StoreCaptureMode>('bridge');

let initialized = false;

export async function initCaptureMode(): Promise<void> {
	if (initialized) return;
	initialized = true;

	try {
		const result = await getCaptureMode();
		// OLD CODE START — 2026-10-30: dhcp_gateway was collapsed into 'bridge'
		// captureMode.set(result.mode === 'mirror' ? 'mirror' : 'bridge');
		// OLD CODE END
		const known = result.mode === 'mirror' || result.mode === 'dhcp_gateway';
		captureMode.set(known ? (result.mode as StoreCaptureMode) : 'bridge');
	} catch {
		// Fallback to bridge — safe default
	}
}
