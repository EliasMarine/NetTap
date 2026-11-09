/**
 * Client for GET /api/live-bandwidth (NET-205): a device's live download and upload rate,
 * measured by the daemon while someone polls it. Each GET is also the keepalive: stop
 * polling and the daemon stops measuring within 15 s. The catch-all proxy forwards it.
 * It is opt-in: /api/settings/live-bandwidth holds the switch (Settings › Capture), off by default.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** The MAC page counts by MAC, the IP page by its IP (IPv4 only). Exactly one. */
export type LiveBandwidthKey = { mac: string } | { ip: string };

export interface LiveBandwidthSample {
	tick: number;
	/** Wall-clock ms, null for padding before the watch started */
	t: number | null;
	/** The daemon's monotonic time at the counter read, for verification */
	mono: number | null;
	bracket_ms: number | null;
	/** null when not measured, with `reason` saying why */
	down_bps: number | null;
	up_bps: number | null;
	reason: string | null;
}

/** The latest slot, as a sample; its rates are null when it is invalid or older than 5 s, and `reason` says why. */
export type LiveBandwidthLatest = LiveBandwidthSample;

interface LiveBandwidthBase {
	reason: string | null;
	/** null when capture isn't set up yet */
	mode: string | null;
	interface: string | null;
	key: { kind: 'mac' | 'ip'; value: string };
}

export interface LiveBandwidthSupported extends LiveBandwidthBase {
	supported: true;
	mode: string;
	interface: string;
	layer: string;
	/** null when ethtool couldn't read the offload */
	offloads: { gro: boolean | null; lro: boolean | null };
	interval_s: number;
	latest: LiveBandwidthLatest | null;
	/** Seconds since `latest` was read, at response time */
	latest_age_s: number | null;
	last_valid_age_s: number | null;
	measuring_since: number;
	/** 150 slots (5 minutes at 2 s), oldest first */
	samples: LiveBandwidthSample[];
}

export interface LiveBandwidthUnsupported extends LiveBandwidthBase {
	supported: false;
	/** Plain-English reason, e.g. bridge mode can't split the rate by device */
	reason: string;
	/** The setting is off: nothing is measured until it is turned on in Settings › Capture */
	off?: true;
}

export type LiveBandwidthResponse = LiveBandwidthSupported | LiveBandwidthUnsupported;

export type LiveBandwidthCleanupState = 'idle' | 'running' | 'retrying';

/** GET and PUT /api/settings/live-bandwidth: the switch, whether this capture mode can use it, and the counters' removal after a turn-off. */
export interface LiveBandwidthSetting {
	enabled: boolean;
	/** false in bridge or gateway mode, or with capture not set up; the setting is kept anyway */
	supported: boolean;
	reason: string | null;
	mode: string | null;
	cleanup: {
		state: LiveBandwidthCleanupState;
		/** Interface → why its counters couldn't be removed yet (the daemon keeps retrying) */
		failed: Record<string, string>;
	};
}

/** A non-OK reply: `status` tells 503 (busy, starting, capture changing) from 400 and 500; `message` is the daemon's reason. */
export class LiveBandwidthError extends Error {
	status: number;
	/** A failed save's authoritative setting (PUT 500: nothing changed); absent when the reply didn't say */
	enabled?: boolean;

	constructor(message: string, status: number, enabled?: boolean) {
		super(message);
		this.name = 'LiveBandwidthError';
		this.status = status;
		this.enabled = enabled;
	}
}

/** The error a non-OK reply carries: the daemon's own reason, else the status. */
async function replyError(res: Response): Promise<LiveBandwidthError> {
	const data: { error?: unknown; enabled?: unknown } | null = await res.json().catch(() => null);
	const message = typeof data?.error === 'string' && data.error ? data.error : `HTTP ${res.status}`;
	return new LiveBandwidthError(message, res.status, typeof data?.enabled === 'boolean' ? data.enabled : undefined);
}

// A signed-out request gets 401 (NET-197); a 2xx without the daemon's shape is not its answer either
const unexpected = (status: number) => new LiveBandwidthError('NetTap sent an unexpected reply. Sign in again and retry.', status);

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

export async function getLiveBandwidth(key: LiveBandwidthKey, signal?: AbortSignal): Promise<LiveBandwidthResponse> {
	const query = 'mac' in key ? ['mac', key.mac] : ['ip', key.ip];
	const res = await fetch(`/api/live-bandwidth?${new URLSearchParams([query])}`, { signal });
	if (!res.ok) throw await replyError(res);
	const data: unknown = await res.json().catch(() => null);
	if (!data || typeof data !== 'object' || typeof (data as { supported?: unknown }).supported !== 'boolean') throw unexpected(res.status);
	// the card renders samples straight from a measuring reply, so a half answer must not reach it (ts review #2)
	const d = data as Partial<LiveBandwidthSupported>;
	if (d.supported && !(Array.isArray(d.samples) && Number.isFinite(d.interval_s) && typeof d.interface === 'string')) throw unexpected(res.status);
	return data as LiveBandwidthResponse;
}

const SETTING_URL = '/api/settings/live-bandwidth';
const CLEANUP_STATES: readonly unknown[] = ['idle', 'running', 'retrying'] satisfies LiveBandwidthCleanupState[];

async function readSetting(res: Response): Promise<LiveBandwidthSetting> {
	if (!res.ok) throw await replyError(res);
	const data: Partial<LiveBandwidthSetting> | null = await res.json().catch(() => null);
	const failed = data?.cleanup?.failed;
	if (
		typeof data?.enabled !== 'boolean' ||
		typeof data.supported !== 'boolean' ||
		!CLEANUP_STATES.includes(data.cleanup?.state) ||
		!failed ||
		typeof failed !== 'object' ||
		Object.values(failed).some((v) => typeof v !== 'string')
	) {
		throw unexpected(res.status);
	}
	return data as LiveBandwidthSetting;
}

export async function getLiveBandwidthSetting(): Promise<LiveBandwidthSetting> {
	return readSetting(await fetch(SETTING_URL));
}

/** The reply's `enabled` is what the daemon now has; a 500 throws with the unchanged value in `enabled`. */
export async function setLiveBandwidthSetting(enabled: boolean): Promise<LiveBandwidthSetting> {
	return readSetting(
		await fetch(SETTING_URL, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) }),
	);
}
