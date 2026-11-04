/**
 * What the shell says about capture and storage (PLAN.md §5.5). Pure, so every row of the
 * mapping table is tested without rendering.
 */
import type { CaptureHealthResponse, CaptureMode } from '$api/capture';
import type { StorageStatus } from '$api/system';
import { formatBytes } from '$api/logs';

export type ChipTone = 'ok' | 'medium' | 'high' | 'muted';

export interface CaptureChip {
	text: string;
	tone: ChipTone;
	pulse: boolean;
}

/** Loaded value, a failed request, or not answered yet. */
export type Loaded<T> = T | 'failed' | null;

const MODE_LABELS: Record<string, string> = { mirror: 'Mirror', dhcp_gateway: 'DHCP Gateway' };

/** Anything unknown shows as Bridge, the original default (as the old badge did). */
export function modeLabel(mode: string): string {
	return MODE_LABELS[mode] ?? 'Bridge';
}

export function captureChip(mode: Loaded<CaptureMode>, health: Loaded<CaptureHealthResponse>): CaptureChip {
	const modeText = mode === 'failed' ? 'Mode unknown' : mode ? `${modeLabel(mode.mode)} mode` : 'Checking mode…';
	const iface = (mode && mode !== 'failed' ? mode.interface : '') || (health && health !== 'failed' ? health.capture_interface : '');

	if (health === null) return { text: modeText, tone: 'muted', pulse: false };
	if (health === 'failed') return { text: 'Capture status unknown', tone: 'muted', pulse: false };
	switch (health.status) {
		case 'normal':
			return { text: iface ? `${modeText} · ${iface}` : modeText, tone: 'ok', pulse: true };
		case 'degraded':
			return { text: `${modeText} · degraded`, tone: 'medium', pulse: false };
		case 'down':
			return { text: 'Capture stopped', tone: 'high', pulse: false };
		case 'not_configured':
			return { text: 'Capture not set up', tone: 'muted', pulse: false };
		default:
			return { text: 'Capture status unknown', tone: 'muted', pulse: false };
	}
}

export interface StorageFoot {
	percent: number;
	used: string;
	detail: string;
}

/** "41% used" and "549 GB free · 90-day retention"; retention only when the daemon reports it. */
export function storageFoot(status: Loaded<StorageStatus>): StorageFoot | null {
	if (!status || status === 'failed' || !Number.isFinite(status.disk_usage_percent)) return null;
	const percent = Math.min(100, Math.max(0, Math.round(status.disk_usage_percent)));
	const parts = Number.isFinite(status.disk_free_bytes) ? [`${formatBytes(status.disk_free_bytes)} free`] : [];
	const hot = (status.retention as { hot_days?: unknown } | null)?.hot_days;
	if (typeof hot === 'number' && Number.isFinite(hot)) parts.push(`${hot}-day retention`);
	return { percent, used: `${percent}% used`, detail: parts.join(' · ') };
}
