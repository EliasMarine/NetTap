import { describe, it, expect } from 'vitest';
import {
	captureStage,
	kpiDelta,
	kpiWindow,
	localMidnight,
	openSearchStage,
	packetsStage,
	smartLevel,
	systemStage,
	trendPercent,
} from './home';
import type { CaptureHealthResponse, CaptureStatsResponse } from '$api/capture';
import type { SystemHealth } from '$api/system';

const health = (over: Partial<CaptureHealthResponse> = {}): CaptureHealthResponse => ({
	mode: 'mirror', status: 'normal', capture_interface: 'enp4s0', link_up: true, promisc_enabled: true, issues: [], ...over,
});
const stats = (over: Partial<CaptureStatsResponse> = {}): CaptureStatsResponse => ({
	capture_interface: 'enp4s0', rx_bytes: 0, tx_bytes: 0, rx_packets: 1_200_000, tx_packets: 0, rx_dropped: 0,
	rx_missed_errors: 0, link_speed_mbps: 2500, drop_rate_pct: 0, ...over,
});
const system = (over: Partial<SystemHealth> = {}): SystemHealth => ({
	uptime: 60, timestamp: '', storage: null, smart: null, opensearch_reachable: true, status: 'healthy', healthy: true, ...over,
});

describe('KPI deltas', () => {
	it('signs a change, says "new" from zero, and shows nothing when flat', () => {
		expect(kpiDelta(trendPercent(15, 10))).toEqual({ text: '+50.0%', direction: 'up', bad: false });
		expect(kpiDelta(trendPercent(5, 10))).toEqual({ text: '−50.0%', direction: 'down', bad: false });
		expect(kpiDelta(trendPercent(5, 0))).toEqual({ text: 'new', direction: 'up', bad: false });
		expect(kpiDelta(trendPercent(100, 100.2))).toBeUndefined();
	});

	it('marks a rise bad only where up is bad (alerts)', () => {
		expect(kpiDelta(trendPercent(15, 10), true)?.bad).toBe(true);
		expect(kpiDelta(trendPercent(5, 10), true)?.bad).toBe(false);
	});

	it('names the comparison window, or the window alone without a previous period', () => {
		expect(kpiWindow(true, trendPercent(15, 10), 'Last 24 hours', 'previous 24 h')).toEqual({ comparison: 'vs previous 24 h' });
		expect(kpiWindow(true, trendPercent(10, 10), 'Last 24 hours', 'previous 24 h')).toEqual({ note: 'No change vs previous 24 h' });
		expect(kpiWindow(false, trendPercent(0, 0), 'Last 24 hours', 'previous 24 h')).toEqual({ note: 'Last 24 hours' });
	});
});

describe('localMidnight', () => {
	it('is the start of the local day, so 00:01 today is after it and 23:59 yesterday before it', () => {
		const since = new Date(localMidnight(new Date(2026, 10, 3, 10, 0))).getTime();
		expect(new Date(2026, 10, 3, 0, 1).getTime()).toBeGreaterThanOrEqual(since);
		expect(new Date(2026, 10, 2, 23, 59).getTime()).toBeLessThan(since);
		expect(localMidnight(new Date(2026, 10, 3, 0, 0))).toBe(new Date(2026, 10, 3).toISOString());
	});
});

describe('smartLevel', () => {
	it('maps the daemon scale 1 critical … 5 info', () => {
		expect([1, 2, 3, 4, 5, 9].map(smartLevel)).toEqual(['critical', 'high', 'medium', 'low', 'info', 'info']);
	});
});

describe('capture pipeline stages', () => {
	it('capture: healthy with mode and interface, failing with the first issue, unknown otherwise', () => {
		expect(captureStage(health(), false)).toMatchObject({ status: 'ok', detail: 'Mirror on enp4s0' });
		expect(captureStage(health({ status: 'degraded', issues: ['Link down on eth1'] }), false)).toMatchObject({
			status: 'failing',
			detail: 'Degraded · Link down on eth1',
		});
		expect(captureStage(health({ status: 'down' }), false)).toMatchObject({ status: 'failing', detail: 'Down' });
		expect(captureStage(health({ status: 'not_configured' }), false)).toMatchObject({ status: 'unknown', detail: 'Not configured' });
		expect(captureStage(health({ status: 'odd' }), false)).toMatchObject({ status: 'unknown', detail: 'Unknown' });
		expect(captureStage(null, true)).toMatchObject({ status: 'unknown', detail: "Couldn't check capture health: the request failed." });
		expect(captureStage(null, false)).toMatchObject({ status: 'unknown', detail: 'Checking…' });
	});

	it('packets: no drops, drops under the 0.1 % flag, drops over it, and a failed request', () => {
		expect(packetsStage(stats(), false)).toMatchObject({ status: 'ok', detail: 'No packet drops · 1.2M received' });
		expect(packetsStage(stats({ rx_dropped: 12, drop_rate_pct: 0.001 }), false)).toMatchObject({
			status: 'ok',
			detail: '0.001% dropped · 12 packets',
		});
		expect(packetsStage(stats({ rx_dropped: 5000, drop_rate_pct: 0.4 }), false).status).toBe('failing');
		expect(packetsStage(null, true)).toMatchObject({ status: 'unknown', detail: "Couldn't load capture counters: the request failed." });
	});

	it('system and OpenSearch read the one health check; a failed check is unknown, never degraded', () => {
		expect(systemStage(system(), false)).toMatchObject({ status: 'ok', detail: 'Healthy' });
		// OLD CODE START — 2026-11-06 (S5): one boolean
		// expect(systemStage(system({ healthy: false }), false)).toMatchObject({ status: 'failing', detail: 'Degraded' });
		// OLD CODE END
		expect(systemStage(system({ status: 'problem', healthy: false }), false)).toMatchObject({ status: 'failing', detail: 'Reports a problem' });
		// an unreadable drive beside healthy checks is incomplete, never "Degraded"
		expect(systemStage(system({ status: 'incomplete', healthy: null }), false)).toMatchObject({ status: 'unknown', detail: "Incomplete · some checks couldn't run" });
		expect(systemStage(null, true)).toMatchObject({ status: 'unknown', detail: "Couldn't check: the request failed" });
		expect(openSearchStage(system(), false)).toMatchObject({ status: 'ok', detail: 'Connected' });
		expect(openSearchStage(system({ opensearch_reachable: false }), false)).toMatchObject({ status: 'failing', detail: 'Unreachable' });
		expect(openSearchStage(null, true).status).toBe('unknown');
	});
});
