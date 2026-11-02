/**
 * Client-side API helpers for internet health monitoring endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// OLD CODE START — no 'unknown': a ping that couldn't run read as 100% loss and down; the
// daemon now sends status 'unknown' with packet_loss_pct null and an error, and nulls in the stats
// export interface HealthCheck {
// 	timestamp: string;
// 	latency_ms: number | null;
// 	dns_resolve_ms: number | null;
// 	packet_loss_pct: number;
// 	status: string; // 'healthy' | 'degraded' | 'down'
// }
//
// export interface HealthStats {
// 	avg_latency_ms: number;
// 	p95_latency_ms: number;
// 	min_latency_ms: number;
// 	max_latency_ms: number;
// 	avg_dns_ms: number;
// 	avg_packet_loss_pct: number;
// 	uptime_pct: number;
// 	total_checks: number;
// 	history_span_hours: number;
// }
// OLD CODE END

/** 'unknown' = ping couldn't run, so nothing was measured (see `error`); never read it as down. */
export type InternetStatus = 'healthy' | 'degraded' | 'down' | 'unknown' | 'not_configured';

export interface HealthCheck {
	timestamp: string;
	latency_ms: number | null;
	dns_resolve_ms: number | null;
	/** null = not measured (status 'unknown'): show "—", never 0% or 100% */
	packet_loss_pct: number | null;
	status: InternetStatus;
	/** Why ping couldn't measure (status 'unknown'). */
	error?: string | null;
}

/** Averages leave out unmeasured checks; null = nothing measured yet. */
export interface HealthStats {
	avg_latency_ms: number | null;
	p95_latency_ms: number | null;
	min_latency_ms: number | null;
	max_latency_ms: number | null;
	avg_dns_ms: number | null;
	avg_packet_loss_pct: number | null;
	uptime_pct: number | null;
	total_checks: number;
	history_span_hours: number;
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function buildQuery(params: Record<string, string | number | undefined>): string {
	const qs = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value !== undefined && value !== '') {
			qs.set(key, String(value));
		}
	}
	const str = qs.toString();
	return str ? `?${str}` : '';
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get the most recent internet health check result.
 */
export async function getInternetHealth(): Promise<HealthCheck> {
	const res = await fetch('/api/internet/health');

	// OLD CODE START — #96: a failed request read as the internet being down
	// if (!res.ok) {
	// 	return {
	// 		timestamp: '',
	// 		latency_ms: null,
	// 		dns_resolve_ms: null,
	// 		packet_loss_pct: 100,
	// 		status: 'down',
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Internet health failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Get historical internet health checks.
 */
export async function getInternetHistory(
	limit?: number
): Promise<{ history: HealthCheck[] }> {
	const query = buildQuery({ limit });
	const res = await fetch(`/api/internet/history${query}`);

	// OLD CODE START — #96: a failed request read as no history
	// if (!res.ok) {
	// 	return { history: [] };
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Internet health history failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Get aggregated internet health statistics.
 */
export async function getInternetStats(): Promise<HealthStats> {
	const res = await fetch('/api/internet/stats');

	// OLD CODE START — #96: a failed request read as 0% uptime
	// if (!res.ok) {
	// 	return {
	// 		avg_latency_ms: 0,
	// 		p95_latency_ms: 0,
	// 		min_latency_ms: 0,
	// 		max_latency_ms: 0,
	// 		avg_dns_ms: 0,
	// 		avg_packet_loss_pct: 100,
	// 		uptime_pct: 0,
	// 		total_checks: 0,
	// 		history_span_hours: 0,
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Internet health stats failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Trigger an on-demand internet health check and return the result.
 */
export async function triggerHealthCheck(): Promise<HealthCheck> {
	const res = await fetch('/api/internet/check', {
		method: 'POST',
	});

	// OLD CODE START — #96: a failed request read as the internet being down
	// if (!res.ok) {
	// 	return {
	// 		timestamp: '',
	// 		latency_ms: null,
	// 		dns_resolve_ms: null,
	// 		packet_loss_pct: 100,
	// 		status: 'down',
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Internet health check failed: HTTP ${res.status}`);

	return res.json();
}
