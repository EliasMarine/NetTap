/**
 * Client-side API helpers for internet health monitoring endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface HealthCheck {
	timestamp: string;
	latency_ms: number | null;
	dns_resolve_ms: number | null;
	packet_loss_pct: number;
	status: string; // 'healthy' | 'degraded' | 'down'
}

export interface HealthStats {
	avg_latency_ms: number;
	p95_latency_ms: number;
	min_latency_ms: number;
	max_latency_ms: number;
	avg_dns_ms: number;
	avg_packet_loss_pct: number;
	uptime_pct: number;
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

	if (!res.ok) {
		return {
			timestamp: '',
			latency_ms: null,
			dns_resolve_ms: null,
			packet_loss_pct: 100,
			status: 'down',
		};
	}

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

	if (!res.ok) {
		return { history: [] };
	}

	return res.json();
}

/**
 * Get aggregated internet health statistics.
 */
export async function getInternetStats(): Promise<HealthStats> {
	const res = await fetch('/api/internet/stats');

	if (!res.ok) {
		return {
			avg_latency_ms: 0,
			p95_latency_ms: 0,
			min_latency_ms: 0,
			max_latency_ms: 0,
			avg_dns_ms: 0,
			avg_packet_loss_pct: 100,
			uptime_pct: 0,
			total_checks: 0,
			history_span_hours: 0,
		};
	}

	return res.json();
}

/**
 * Trigger an on-demand internet health check and return the result.
 */
export async function triggerHealthCheck(): Promise<HealthCheck> {
	const res = await fetch('/api/internet/check', {
		method: 'POST',
	});

	if (!res.ok) {
		return {
			timestamp: '',
			latency_ms: null,
			dns_resolve_ms: null,
			packet_loss_pct: 100,
			status: 'down',
		};
	}

	return res.json();
}
