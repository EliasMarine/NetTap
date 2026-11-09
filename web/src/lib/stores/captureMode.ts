/**
 * Singleton store for the current capture mode (bridge, mirror or dhcp_gateway), or null while
 * it isn't known. Fetched at app startup from /api/capture/mode; pages that word things by mode
 * call initCaptureMode() again from their loaders, so a failed first request is retried.
 * Used by drawer components to conditionally show/hide "Block IP" actions.
 */
import { writable } from 'svelte/store';
import { getCaptureMode } from '$api/capture';

// OLD CODE START — 2026-10-30: store type gains 'dhcp_gateway' for DHCP gateway capture mode
// export const captureMode = writable<'bridge' | 'mirror'>('bridge');
// OLD CODE END
export type StoreCaptureMode = 'bridge' | 'mirror' | 'dhcp_gateway';

// OLD CODE START — NET-225: 'bridge' before the reply, on a failure or for an unknown mode; pages
// that warn about bridge mode would have warned mirror users
// export const captureMode = writable<StoreCaptureMode>('bridge');
//
// let initialized = false;
//
// export async function initCaptureMode(): Promise<void> {
// 	if (initialized) return;
// 	initialized = true;
//
// 	try {
// 		const result = await getCaptureMode();
// 		const known = result.mode === 'mirror' || result.mode === 'dhcp_gateway';
// 		captureMode.set(known ? (result.mode as StoreCaptureMode) : 'bridge');
// 	} catch {
// 		// Fallback to bridge — safe default
// 	}
// }
// OLD CODE END
// OLD CODE: export const captureMode = writable<StoreCaptureMode | null>(null); (NET-225: the shell chip says
// "Mode unknown" once asked and "Checking mode…" before, so a settled request without a known mode is 'unknown')
/** null until a request settles; 'unknown' when it failed or named no mode this build knows. */
export const captureMode = writable<StoreCaptureMode | 'unknown' | null>(null);

const MODES: readonly string[] = ['bridge', 'mirror', 'dhcp_gateway'];
let answered = false;
let pending: Promise<void> | null = null;

// OLD CODE START — review M2: an unknown mode counted as answered, so it was never asked again
// /** Asks once the daemon has answered; a failed request is asked again on the next call. */
// …	.then((result) => {
// 		answered = true;
// 		captureMode.set(MODES.includes(result.mode) ? (result.mode as StoreCaptureMode) : null);
// 	})
// OLD CODE END
/** Asks until the daemon names a known mode; a failure or an unknown mode is asked again on the next call. */
export function initCaptureMode(): Promise<void> {
	if (answered) return Promise.resolve();
	pending ??= getCaptureMode()
		.then((result) => {
			answered = MODES.includes(result.mode);
			// OLD CODE: captureMode.set(answered ? (result.mode as StoreCaptureMode) : null);
			captureMode.set(answered ? (result.mode as StoreCaptureMode) : 'unknown');
		})
		.catch(() => {
			// OLD CODE: (nothing: unknown stayed null)
			captureMode.set('unknown'); // the next loader asks again
		})
		.finally(() => {
			pending = null;
		});
	return pending;
}

/** Reads the mode again even after an answer: a backup restore can change it in the session (review M2). */
export async function refreshCaptureMode(): Promise<void> {
	await pending; // an older request can't land after this one
	answered = false;
	await initCaptureMode();
}
