/**
 * Client for GET /api/live-bandwidth (NET-205): a device's live download and upload rate,
 * measured by the daemon while someone polls it. Each GET is also the keepalive: stop
 * polling and the daemon stops measuring within 15 s. The catch-all proxy forwards it.
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
}

export type LiveBandwidthResponse = LiveBandwidthSupported | LiveBandwidthUnsupported;

/** A non-OK reply: `status` tells 503 (busy, starting, capture changing) from 400 and 500; `message` is the daemon's reason. */
export class LiveBandwidthError extends Error {
	status: number;

	constructor(message: string, status: number) {
		super(message);
		this.name = 'LiveBandwidthError';
		this.status = status;
	}
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

export async function getLiveBandwidth(key: LiveBandwidthKey, signal?: AbortSignal): Promise<LiveBandwidthResponse> {
	const query = 'mac' in key ? ['mac', key.mac] : ['ip', key.ip];
	const res = await fetch(`/api/live-bandwidth?${new URLSearchParams([query])}`, { signal });
	if (!res.ok) {
		const data: { error?: unknown } | null = await res.json().catch(() => null);
		const message = typeof data?.error === 'string' && data.error ? data.error : `HTTP ${res.status}`;
		throw new LiveBandwidthError(message, res.status);
	}
	const data: unknown = await res.json().catch(() => null);
	// A signed-out request gets 401 above (NET-197); a 2xx without the daemon's shape is not its answer either
	if (!data || typeof data !== 'object' || typeof (data as { supported?: unknown }).supported !== 'boolean') {
		throw new LiveBandwidthError('NetTap sent an unexpected reply. Sign in again and retry.', res.status);
	}
	return data as LiveBandwidthResponse;
}
