import { describe, it, expect } from 'vitest';
import {
	captureStage,
	COMPARE_FAILED,
	dataStage,
	formatBytes,
	formatBytesShort,
	kpiDelta,
	kpiWindow,
	localMidnight,
	NOT_ENOUGH,
	openSearchStage,
	packetsStage,
	smartLevel,
	systemStage,
	trendPercent,
} from './home';
import type { CaptureHealthResponse, CaptureStatsResponse, LossWindow } from '$api/capture';
import type { SystemHealth } from '$api/system';

const health = (over: Partial<CaptureHealthResponse> = {}): CaptureHealthResponse => ({
	mode: 'mirror', status: 'normal', capture_interface: 'enp4s0', link_up: true, promisc_enabled: true, issues: [], ...over,
});
const stats = (over: Partial<CaptureStatsResponse> = {}): CaptureStatsResponse => ({
	capture_interface: 'enp4s0', rx_bytes: 0, tx_bytes: 0, rx_packets: 1_200_000, tx_packets: 0, rx_dropped: 0,
	rx_missed_errors: 0, link_speed_mbps: 2500, drop_rate_pct: 0,
	loss_window: { state: 'unavailable', interface: null, window: null, cumulative: null },
	...over,
});
/** NET-167: stats whose recent window (58 min) is as given; the cumulative counters say otherwise on purpose. */
const recent = (window: LossWindow['window'], state: LossWindow['state'] = 'ok') =>
	stats({
		rx_dropped: 900_000, drop_rate_pct: 75, // a burst days ago, which must not decide the stage
		loss_window: { state, interface: 'enp4s0', window, cumulative: { arrived: 1_200_000, lost: 900_000, drop_rate_pct: 75 } },
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

	it('says why there is no trend, and where the compared data ends (NET-228, TRF-6)', () => {
		expect(kpiDelta(NOT_ENOUGH)).toBeUndefined();
		expect(kpiDelta(COMPARE_FAILED)).toBeUndefined();
		expect(kpiWindow(true, NOT_ENOUGH, 'Last 24 hours', 'previous 24 hours', '13:00')).toEqual({ note: 'Not enough data to compare' });
		expect(kpiWindow(true, COMPARE_FAILED, 'Last 24 hours', 'previous 24 hours', '13:00')).toEqual({ note: "Couldn't load the comparison" });
		expect(kpiWindow(true, trendPercent(15, 10), 'Last 24 hours', 'previous 24 hours', '13:00')).toEqual({ comparison: 'vs previous 24 hours, up to 13:00' });
		expect(kpiWindow(true, trendPercent(10, 10), 'Last 24 hours', 'previous 24 hours', '13:00')).toEqual({ note: 'No change vs previous 24 hours, up to 13:00' });
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

	// OLD CODE: it('packets: no drops, drops under the 0.1 % flag, drops over it, and a failed request', … (NET-167: the drop cases moved below)
	it('packets: a failed request', () => {
		// OLD CODE START — 2026-11-06 (S9): kernel drops only, at 3 decimal places
		// expect(packetsStage(stats(), false)).toMatchObject({ status: 'ok', detail: 'No packet drops · 1.2M received' });
		// expect(packetsStage(stats({ rx_dropped: 12, drop_rate_pct: 0.001 }), false)).toMatchObject({
		// 	status: 'ok',
		// 	detail: '0.001% dropped · 12 packets',
		// });
		// OLD CODE END
		// OLD CODE START — NET-167: judged on the counters since they last reset
		// expect(packetsStage(stats(), false)).toMatchObject({ status: 'ok', detail: 'No packets lost · 1.2M received' });
		// // a tiny real loss never reads as 0.00% or "none"
		// expect(packetsStage(stats({ rx_dropped: 12, drop_rate_pct: 0.001 }), false)).toMatchObject({
		// 	status: 'ok',
		// 	detail: '< 0.01% lost · 12 packets',
		// });
		// // NIC misses count: rx_dropped 0 is not "no packets lost"
		// expect(packetsStage(stats({ rx_missed_errors: 600, drop_rate_pct: 0.05 }), false)).toMatchObject({
		// 	detail: '0.05% lost · 600 packets',
		// });
		// expect(packetsStage(stats({ rx_dropped: 5000, drop_rate_pct: 0.4 }), false).status).toBe('failing');
		// OLD CODE END
		expect(packetsStage(null, true)).toMatchObject({ status: 'unknown', detail: "Couldn't load capture counters: the request failed." });
	});

	// NET-167: the stage reads the last hour, so a burst days ago no longer keeps it red
	it('packets: judged on the recent window, not on the counters since they reset', () => {
		expect(packetsStage(recent({ seconds: 3480, arrived: 98_765, lost: 0, drop_rate_pct: 0 }), false)).toEqual({
			key: 'packets', label: 'Packets', status: 'ok', detail: 'No packets lost in the last 58 min · 98,765 received',
		});
		// a tiny real loss never reads as 0.00% or "none"
		expect(packetsStage(recent({ seconds: 3480, arrived: 98_765, lost: 12, drop_rate_pct: 0.01215 }), false)).toMatchObject({
			status: 'ok', detail: '0.01% lost in the last 58 min · 12 packets',
		});
		expect(packetsStage(recent({ seconds: 3480, arrived: 293_810, lost: 1_234, drop_rate_pct: 0.42 }), false)).toMatchObject({
			status: 'failing', detail: '0.42% lost in the last 58 min · 1,234 packets',
		});
	});

	it('packets: no arrivals, measuring and unavailable are unknown, never a 0 % loss', () => {
		expect(packetsStage(recent({ seconds: 3480, arrived: 0, lost: 0, drop_rate_pct: null }), false)).toMatchObject({
			status: 'unknown', detail: 'No packets in the last 58 min',
		});
		expect(packetsStage(recent(null, 'measuring'), false)).toMatchObject({ status: 'unknown', detail: 'Measuring recent loss…' });
		expect(packetsStage(recent(null, 'unavailable'), false)).toMatchObject({ status: 'unknown', detail: 'Loss counters unavailable' });
	});

	it('system and OpenSearch read the one health check; a failed check is unknown, never degraded', () => {
		expect(systemStage(system(), false)).toMatchObject({ status: 'ok', detail: 'Healthy' });
		// OLD CODE START — 2026-11-06 (S5): one boolean
		// expect(systemStage(system({ healthy: false }), false)).toMatchObject({ status: 'failing', detail: 'Degraded' });
		// OLD CODE END
		expect(systemStage(system({ status: 'problem', healthy: false }), false)).toMatchObject({ status: 'failing', detail: 'Reports a problem' });
		// an unreadable drive beside healthy checks is incomplete, never "Degraded"
		// OLD CODE: …toMatchObject({ status: 'unknown', … }) (NET-168: incomplete is amber now)
		expect(systemStage(system({ status: 'incomplete', healthy: null }), false)).toMatchObject({ status: 'warn', detail: "Incomplete · some checks couldn't run" });
		expect(systemStage(null, true)).toMatchObject({ status: 'unknown', detail: "Couldn't check: the request failed" });
		// a daemon that predates the status field must not break the Home page
		expect(systemStage(system({ status: undefined }), false)).toMatchObject({ status: 'unknown', detail: 'Unknown' });
		expect(openSearchStage(system(), false)).toMatchObject({ status: 'ok', detail: 'Connected' });
		expect(openSearchStage(system({ opensearch_reachable: false }), false)).toMatchObject({ status: 'failing', detail: 'Unreachable' });
		expect(openSearchStage(null, true).status).toBe('unknown');
	});

	// F2: storage, SMART and OpenSearch fine said nothing about whether data still arrives
	it('data reads the pipeline: stale data fails the stage while the system stage stays its own', () => {
		const pipeline = {
			state: 'stale', newest_record_at: '2026-11-08T20:13:00+00:00', age_seconds: 47 * 60, threshold_seconds: 900,
			sensors: {}, checked_at: '2026-11-08T21:00:00+00:00',
		} as const;
		expect(dataStage(system({ status: 'problem', healthy: false, pipeline }), false)).toEqual({
			key: 'data', label: 'Data', status: 'failing', detail: 'No new records for 47 min',
		});
		expect(dataStage(system({ pipeline: { ...pipeline, state: 'fresh', age_seconds: 40 } }), false)).toMatchObject({
			status: 'ok', detail: 'Newest record 40 s ago',
		});
		// a daemon older than the web app sends no pipeline: Unknown, never healthy
		expect(dataStage(system(), false)).toMatchObject({ status: 'unknown', detail: 'Unknown' });
		expect(dataStage(null, true)).toMatchObject({ status: 'unknown', detail: 'Unknown: the health check failed' });
		expect(dataStage(null, false)).toMatchObject({ status: 'unknown', detail: 'Checking…' });
	});
});

// NET-166: decimal units, so a figure means what its label says (1,024-based read 954 MB for 10^9 bytes)
describe('Home byte formats', () => {
	it('formatBytes reads 10^9 bytes as 1.0 GB and 10^12 as 1.0 TB, whole numbers from 100', () => {
		expect(formatBytes(1e9)).toBe('1.0 GB');
		expect(formatBytes(1e12)).toBe('1.0 TB');
		expect(formatBytes(250e9)).toBe('250 GB');
		expect(formatBytes(999)).toBe('999 B');
	});

	it('formatBytesShort is the axis form: no space, whole numbers from 10', () => {
		expect(formatBytesShort(1e9)).toBe('1.0GB');
		expect(formatBytesShort(25e6)).toBe('25MB');
	});
});
