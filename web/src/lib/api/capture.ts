/**
 * Client-side API helpers for capture mode and capture control endpoints.
 * Wraps GET /api/capture/mode, /api/capture/health, /api/capture/stats,
 *        GET /api/capture/status, PUT /api/capture/toggle, PUT /api/capture/settings.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CaptureMode {
	mode: string; // "bridge" | "mirror" | "dhcp_gateway"
	interface: string;
}

export interface CaptureHealthResponse {
	mode: string;
	status: string; // "normal" | "degraded" | "down" | "not_configured"
	capture_interface: string;
	link_up: boolean;
	promisc_enabled: boolean;
	issues: string[];
	[key: string]: unknown; // extra fields from bridge/mirror
}

export interface CaptureStatsResponse {
	capture_interface: string;
	rx_bytes: number;
	tx_bytes: number;
	rx_packets: number;
	tx_packets: number;
	rx_dropped: number;
	rx_missed_errors: number;
	link_speed_mbps: number;
	drop_rate_pct: number;
	/** NET-167: always set by getCaptureStats; an old daemon's missing block reads as unavailable. */
	loss_window: LossWindow;
}

/** Packets that reached the interface and how many of them were lost. The rate is null when nothing arrived. */
export interface LossCounts {
	arrived: number;
	lost: number;
	drop_rate_pct: number | null;
}

/** NET-167: loss over the last hour or less (`window`) and since the counters reset (`cumulative`). */
export interface LossWindow {
	state: 'ok' | 'measuring' | 'unavailable';
	interface: string | null;
	/** Set only when state is ok; `seconds` is the span actually measured. */
	window: (LossCounts & { seconds: number }) | null;
	cumulative: LossCounts | null;
}

// OLD CODE START — NET-167: labelled the main loss figure, which is now the last hour
// /** S9: what every packet-loss figure covers; nothing records when the counters last reset. */
// export const LOSS_SCOPE = 'Cumulative kernel interface counters; reset time unknown';
// OLD CODE END
/** What the cumulative loss count covers. */
export const LOSS_SCOPE =
	'Counted since the interface counters last reset: boot, driver reload or the interface being re-created';

// OLD CODE START — NET-167: every loss figure now comes from the daemon's validated loss_window;
// rx_dropped and rx_missed_errors can read 0 when the counters couldn't be read
// /** S9: packets lost = kernel drops + NIC misses. Every zero-loss claim reads this one count. */
// export function packetsLost(s: Pick<CaptureStatsResponse, 'rx_dropped' | 'rx_missed_errors'>): number {
// 	return s.rx_dropped + s.rx_missed_errors;
// }
// OLD CODE END

/** The daemon's loss rate as a percentage that never rounds a real loss down to 0. */
export function formatLossPct(pct: number, lost: number): string {
	return lost > 0 && pct < 0.01 ? '< 0.01%' : `${pct.toFixed(2)}%`;
}

/** "last 58 min": whole minutes rounded down, so the span is never overstated. */
export function windowWords(seconds: number): string {
	return `last ${Math.floor(seconds / 60)} min`;
}

export interface LossWords {
	status: 'ok' | 'failing' | 'unknown';
	detail: string;
	/** The loss percentage the detail shows, or null when there is none to show. */
	pct: string | null;
}

/** NET-167: the one reading of recent loss Home and Infrastructure both show. Over 0.1 % is failing. */
export function lossWords(lw: LossWindow): LossWords {
	if (lw.state === 'measuring') return { status: 'unknown', detail: 'Measuring recent loss…', pct: null };
	const w = lw.window;
	if (lw.state !== 'ok' || !w) return { status: 'unknown', detail: 'Loss counters unavailable', pct: null };
	const span = windowWords(w.seconds);
	if (w.arrived === 0 || w.drop_rate_pct == null) return { status: 'unknown', detail: `No packets in the ${span}`, pct: null };
	const pct = formatLossPct(w.drop_rate_pct, w.lost);
	const status = w.drop_rate_pct > 0.1 ? 'failing' : 'ok';
	const detail =
		w.lost > 0
			? `${pct} lost in the ${span} · ${w.lost.toLocaleString()} packets`
			: `No packets lost in the ${span} · ${w.arrived.toLocaleString()} received`;
	return { status, detail, pct };
}

const isCount = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0;

/** Counts as sent, null when the daemon sent null, undefined when malformed. */
function readCounts(v: unknown): LossCounts | null | undefined {
	if (v === null) return null;
	if (typeof v !== 'object') return undefined;
	const { arrived, lost, drop_rate_pct } = v as Record<string, unknown>;
	if (!isCount(arrived) || !isCount(lost) || (drop_rate_pct !== null && !isCount(drop_rate_pct))) return undefined;
	return { arrived, lost, drop_rate_pct };
}

/** A missing or malformed loss_window reads as unavailable, never as 0 loss. */
function parseLossWindow(v: unknown): LossWindow {
	const unavailable: LossWindow = { state: 'unavailable', interface: null, window: null, cumulative: null };
	if (typeof v !== 'object' || v === null) return unavailable;
	const { state, interface: iface, window: rawWindow, cumulative: rawCumulative } = v as Record<string, unknown>;
	const win = readCounts(rawWindow);
	const cumulative = readCounts(rawCumulative);
	const seconds = (rawWindow as { seconds?: unknown } | null | undefined)?.seconds;
	if (
		(state !== 'ok' && state !== 'measuring' && state !== 'unavailable') ||
		(iface !== null && typeof iface !== 'string') ||
		win === undefined ||
		cumulative === undefined ||
		(state === 'ok') !== (win !== null) ||
		// under a minute would read "last 0 min"; the daemon never sends one
		(win !== null && !(isCount(seconds) && seconds >= 60))
	) {
		return unavailable;
	}
	return { state, interface: iface, window: win && { ...win, seconds: seconds as number }, cumulative };
}

export interface CaptureStatus {
	enabled: boolean;
	maxFileSizeMB: number;
	/** netsniff also starts a new file after this many minutes */
	rotateMinutes?: number;
	containerRunning: boolean;
	containerStatus: string;
}

export interface CaptureToggleResult {
	enabled: boolean;
	containerRunning: boolean;
	containerStatus: string;
}

export interface CaptureSettings {
	maxFileSizeMB: number;
}

export interface CaptureSettingsResult {
	maxFileSizeMB: number;
	restarted: boolean;
}

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

const DEFAULT_STATUS: CaptureStatus = {
	enabled: true,
	maxFileSizeMB: 100,
	containerRunning: false,
	containerStatus: 'unknown',
};

// ---------------------------------------------------------------------------
// Derived state
// ---------------------------------------------------------------------------

export type CaptureState = 'active' | 'stopped' | 'unknown';

/**
 * Capture is "active" only when it is enabled AND its container is running.
 * `containerStatus: 'unknown'` is what both the daemon (docker inspect failed)
 * and DEFAULT_STATUS (request failed) report when the real state is not known.
 */
export function captureState(status: CaptureStatus | null): CaptureState {
	if (!status || status.containerStatus === 'unknown') return 'unknown';
	return status.enabled && status.containerRunning ? 'active' : 'stopped';
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get the current capture mode (bridge, mirror or dhcp_gateway).
 */
export async function getCaptureMode(): Promise<CaptureMode> {
	// OLD CODE START — #96: a failed request read as capture mode "Bridge"
	// try {
	// 	const res = await fetch('/api/capture/mode');
	// 	if (!res.ok) {
	// 		return { mode: 'bridge', interface: '' };
	// 	}
	// 	return res.json();
	// } catch {
	// 	return { mode: 'bridge', interface: '' };
	// }
	// OLD CODE END
	const res = await fetch('/api/capture/mode');
	if (!res.ok) {
		throw new Error(`Capture mode request failed: HTTP ${res.status}`);
	}
	return res.json();
}

/**
 * Get the current capture mode, throwing on any failure instead of guessing
 * 'bridge'. For flows that must not act on a guessed mode (Go Live).
 * Throws Error with the daemon's `error` text, or `HTTP <status>`.
 */
export async function fetchCaptureMode(): Promise<CaptureMode> {
	const res = await fetch('/api/capture/mode');
	if (!res.ok) {
		const data = await res.json().catch(() => ({}));
		throw new Error(typeof data?.error === 'string' && data.error ? data.error : `HTTP ${res.status}`);
	}
	const data = await res.json();
	if (typeof data?.mode !== 'string' || !data.mode) {
		throw new Error('The capture mode response had no mode.');
	}
	return data as CaptureMode;
}

/**
 * Get capture health status.
 */
export async function getCaptureHealth(): Promise<CaptureHealthResponse> {
	// OLD CODE START — #96: a failed request read as "Inline Bridge", status Down, link Down
	// try {
	// 	const res = await fetch('/api/capture/health');
	// 	if (!res.ok) {
	// 		return {
	// 			mode: 'bridge',
	// 			status: 'down',
	// 			capture_interface: '',
	// 			link_up: false,
	// 			promisc_enabled: false,
	// 			issues: ['Unable to reach capture health endpoint'],
	// 		};
	// 	}
	// 	return res.json();
	// } catch {
	// 	return { ...same 'down' default... };
	// }
	// OLD CODE END
	const res = await fetch('/api/capture/health');
	if (!res.ok) {
		throw new Error(`Capture health request failed: HTTP ${res.status}`);
	}
	return res.json();
}

/**
 * Get capture interface statistics (drop counters, throughput).
 */
export async function getCaptureStats(): Promise<CaptureStatsResponse> {
	// OLD CODE START — #96: a failed request read as 0 packets dropped, 0.000% drop rate
	// try {
	// 	const res = await fetch('/api/capture/stats');
	// 	if (!res.ok) {
	// 		return {
	// 			capture_interface: '',
	// 			rx_bytes: 0,
	// 			tx_bytes: 0,
	// 			rx_packets: 0,
	// 			tx_packets: 0,
	// 			rx_dropped: 0,
	// 			rx_missed_errors: 0,
	// 			link_speed_mbps: 0,
	// 			drop_rate_pct: 0,
	// 		};
	// 	}
	// 	return res.json();
	// } catch {
	// 	return { ...same all-zero default... };
	// }
	// OLD CODE END
	const res = await fetch('/api/capture/stats');
	if (!res.ok) {
		throw new Error(`Capture stats request failed: HTTP ${res.status}`);
	}
	// OLD CODE: return res.json(); (NET-167: loss_window is validated here, at the boundary)
	const data = await res.json();
	return { ...data, loss_window: parseLossWindow(data?.loss_window) };
}

// ---------------------------------------------------------------------------
// Capture control helpers (status / toggle / settings)
// ---------------------------------------------------------------------------

/**
 * Get capture control status (enabled state, file size, container state).
 */
export async function getCaptureStatus(): Promise<CaptureStatus> {
	try {
		const res = await fetch('/api/capture/status');
		if (!res.ok) {
			return { ...DEFAULT_STATUS };
		}
		return res.json();
	} catch {
		return { ...DEFAULT_STATUS };
	}
}

/**
 * Get capture status, throwing on any failure instead of returning defaults.
 * For forms that save what they load (Settings): a guessed 100 MB or
 * "enabled" must never be written back to the box.
 * Throws Error with the daemon's `error` text, or `HTTP <status>`.
 */
export async function fetchCaptureStatus(): Promise<CaptureStatus> {
	const res = await fetch('/api/capture/status');
	if (!res.ok) {
		const data = await res.json().catch(() => ({}));
		throw new Error(typeof data?.error === 'string' && data.error ? data.error : `HTTP ${res.status}`);
	}
	const data = await res.json();
	if (typeof data?.enabled !== 'boolean' || typeof data?.maxFileSizeMB !== 'number') {
		throw new Error('The capture status response was incomplete.');
	}
	return data as CaptureStatus;
}

/**
 * Start or stop the pcap-capture container.
 */
export async function toggleCapture(enabled: boolean): Promise<CaptureToggleResult> {
	const res = await fetch('/api/capture/toggle', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ enabled }),
	});

	if (!res.ok) {
		const data = await res.json().catch(() => ({ error: 'Toggle failed' }));
		throw new Error(data.error || `Toggle failed: ${res.status}`);
	}

	return res.json();
}

/**
 * Update the max PCAP file rotation size.
 */
export async function updateCaptureSettings(
	settings: CaptureSettings,
): Promise<CaptureSettingsResult> {
	const res = await fetch('/api/capture/settings', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ maxFileSizeMB: settings.maxFileSizeMB }),
	});

	if (!res.ok) {
		const data = await res.json().catch(() => ({ error: 'Settings update failed' }));
		throw new Error(data.error || `Settings update failed: ${res.status}`);
	}

	return res.json();
}
