/**
 * Home's pure helpers (routes/+page.svelte): number formats, the KPI trends, the "new today"
 * boundary and the capture pipeline stages. Moved out of the page unchanged where they existed.
 */
import type { PipelineStage } from '$components/ui/Pipeline.svelte';
import { modeLabel } from '$components/shell/status';
import { healthStage, type SystemHealth } from '$api/system';
import { formatLossPct, packetsLost, type CaptureHealthResponse, type CaptureStatsResponse } from '$api/capture';

const CHECKING = 'Checking…';

export function formatBytes(bytes: number): string {
	if (bytes === 0) return '0 B';
	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	const i = Math.floor(Math.log(bytes) / Math.log(1024));
	const value = bytes / Math.pow(1024, i);
	return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[i]}`;
}

export function formatBytesShort(bytes: number): string {
	if (bytes === 0) return '0';
	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	const i = Math.floor(Math.log(bytes) / Math.log(1024));
	const value = bytes / Math.pow(1024, i);
	return `${value.toFixed(value >= 10 ? 0 : 1)}${units[i]}`;
}

export function formatNumber(n: number): string {
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
	if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
	return n.toLocaleString();
}

/**
 * Compute the previous-period time range for trend comparison.
 * E.g., if current range is 24h ago to now, previous is 48h ago to 24h ago.
 */
export function computePreviousPeriod(from: string, to: string): { from: string; to: string } {
	const fromMs = new Date(from).getTime();
	const toMs = new Date(to).getTime();
	const duration = toMs - fromMs;
	return {
		from: new Date(fromMs - duration).toISOString(),
		to: new Date(fromMs).toISOString(),
	};
}

/** Local midnight: "new today" counts from the start of the owner's day, not the last 24 h. */
export function localMidnight(now: Date): string {
	return new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString();
}

export interface Trend {
	arrow: string;
	pct: string;
	direction: 'up' | 'down' | 'flat';
}

export function trendPercent(current: number, previous: number): Trend {
	if (previous === 0 && current === 0) return { arrow: '', pct: '', direction: 'flat' };
	if (previous === 0) return { arrow: '▲', pct: 'new', direction: 'up' };
	const change = ((current - previous) / previous) * 100;
	if (Math.abs(change) < 0.5) return { arrow: '', pct: '', direction: 'flat' };
	return {
		arrow: change > 0 ? '▲' : '▼',
		pct: `${Math.abs(change).toFixed(1)}%`,
		direction: change > 0 ? 'up' : 'down',
	};
}

export const NO_TREND = trendPercent(0, 0);

/** The KpiCard chip for a trend: "+12.5%", "−50.0%" or "new"; none when flat. */
export function kpiDelta(
	t: Trend,
	upIsBad = false,
): { text: string; direction: 'up' | 'down'; bad: boolean } | undefined {
	if (t.direction === 'flat') return undefined;
	const sign = t.pct === 'new' ? '' : t.direction === 'up' ? '+' : '−';
	return { text: `${sign}${t.pct}`, direction: t.direction, bad: upIsBad && t.direction === 'up' };
}

/** Beside the chip: the comparison window when both periods loaded, otherwise the window itself. */
export function kpiWindow(
	compared: boolean,
	t: Trend,
	window: string,
	previous: string,
): { comparison?: string; note?: string } {
	if (!compared) return { note: window };
	return t.direction === 'flat' ? { note: `No change vs ${previous}` } : { comparison: `vs ${previous}` };
}

// OLD CODE START — moved to $lib/utils/severity so the device page shares it
// /** Smart alert severity, 1 critical to 5 info (the daemon's sev_name_map). */
// export function smartLevel(severity: number): SeverityLevel {
// 	if (severity <= 1) return 'critical';
// 	if (severity === 2) return 'high';
// 	if (severity === 3) return 'medium';
// 	return severity === 4 ? 'low' : 'info';
// }
// OLD CODE END
export { smartLevel } from '$lib/utils/severity';

// ---------------------------------------------------------------------------
// Capture pipeline: replaces CaptureHealthPanel on Home, and System Health moves into it
// ---------------------------------------------------------------------------

export function captureStage(h: CaptureHealthResponse | null, failed: boolean): PipelineStage {
	const base = { key: 'capture', label: 'Capture' };
	if (!h) return { ...base, status: 'unknown', detail: failed ? "Couldn't check capture health: the request failed." : CHECKING };
	if (h.status === 'normal') return { ...base, status: 'ok', detail: `${modeLabel(h.mode)} on ${h.capture_interface || 'no interface'}` };
	if (h.status !== 'degraded' && h.status !== 'down') {
		return { ...base, status: 'unknown', detail: h.status === 'not_configured' ? 'Not configured' : 'Unknown' };
	}
	const word = h.status === 'down' ? 'Down' : 'Degraded';
	return { ...base, status: 'failing', detail: h.issues?.[0] ? `${word} · ${h.issues[0]}` : word };
}

export function packetsStage(s: CaptureStatsResponse | null, failed: boolean): PipelineStage {
	const base = { key: 'packets', label: 'Packets' };
	if (!s) return { ...base, status: 'unknown', detail: failed ? "Couldn't load capture counters: the request failed." : CHECKING };
	// OLD CODE START — 2026-11-06 (S9, O10): counted kernel drops only, so a mirror port losing
	// packets at the NIC (rx_missed_errors) read "No packet drops"
	// const detail =
	// 	s.rx_dropped > 0
	// 		? `${s.drop_rate_pct.toFixed(3)}% dropped · ${formatNumber(s.rx_dropped)} packets`
	// 		: `No packet drops · ${formatNumber(s.rx_packets)} received`;
	// OLD CODE END
	const lost = packetsLost(s);
	const detail =
		lost > 0
			? `${formatLossPct(s.drop_rate_pct, lost)} lost · ${formatNumber(lost)} packets`
			: `No packets lost · ${formatNumber(s.rx_packets)} received`;
	// CaptureHealthPanel flagged a drop rate over 0.1 %
	return { ...base, status: s.drop_rate_pct > 0.1 ? 'failing' : 'ok', detail };
}

export function systemStage(health: SystemHealth | null, failed: boolean): PipelineStage {
	const base = { key: 'system', label: 'System' };
	// #96: a failed check reads "Unknown", never "Degraded"
	if (!health) return { ...base, status: 'unknown', detail: failed ? "Couldn't check: the request failed" : CHECKING };
	// OLD CODE START — 2026-11-06 (S5): a check that couldn't run read as "Degraded"
	// return health.healthy ? { ...base, status: 'ok', detail: 'Healthy' } : { ...base, status: 'failing', detail: 'Degraded' };
	// OLD CODE END
	return { ...base, ...healthStage(health.status) };
}

export function openSearchStage(health: SystemHealth | null, failed: boolean): PipelineStage {
	const base = { key: 'opensearch', label: 'OpenSearch' };
	if (!health) return { ...base, status: 'unknown', detail: failed ? 'Unknown: the health check failed' : CHECKING };
	return health.opensearch_reachable
		? { ...base, status: 'ok', detail: 'Connected' }
		: { ...base, status: 'failing', detail: 'Unreachable' };
}
