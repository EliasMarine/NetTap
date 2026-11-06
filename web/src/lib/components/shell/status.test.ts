import { describe, it, expect } from 'vitest';
import { captureChip, storageFoot, modeLabel } from './status';
import type { CaptureHealthResponse } from '$api/capture';
import type { StorageStatus } from '$api/system';

const health = (status: string): CaptureHealthResponse => ({
	mode: 'mirror', status, capture_interface: 'enp3s0', link_up: true, promisc_enabled: true, issues: [],
});
const mirror = { mode: 'mirror', interface: 'enp3s0' };

describe('capture chip', () => {
	it.each([
		['normal', { text: 'Mirror mode · enp3s0', tone: 'ok', pulse: true }],
		['degraded', { text: 'Mirror mode · degraded', tone: 'medium', pulse: false }],
		['down', { text: 'Capture stopped', tone: 'high', pulse: false }],
		['not_configured', { text: 'Capture not set up', tone: 'muted', pulse: false }],
		['something-new', { text: 'Capture status unknown', tone: 'muted', pulse: false }],
	])('health %s', (status, expected) => {
		expect(captureChip(mirror, health(status))).toEqual(expected);
	});

	it('says the status is unknown when the health request fails', () => {
		expect(captureChip(mirror, 'failed')).toEqual({ text: 'Capture status unknown', tone: 'muted', pulse: false });
	});

	it('shows the mode while health is still loading, never pulsing', () => {
		expect(captureChip(mirror, null)).toEqual({ text: 'Mirror mode', tone: 'muted', pulse: false });
	});

	it('says the mode is unknown instead of guessing Bridge when the mode request fails (#96)', () => {
		const chip = captureChip('failed', health('normal'));
		expect(chip.text).toBe('Mode unknown · enp3s0');
		expect(chip.text).not.toContain('Bridge');
	});

	it.each([
		['mirror', 'Mirror'],
		['dhcp_gateway', 'DHCP Gateway'],
		['bridge', 'Bridge'],
		['anything-else', 'Bridge'],
	])('labels mode %s as %s', (mode, label) => {
		expect(modeLabel(mode)).toBe(label);
	});
});

const storage = (over: Partial<StorageStatus> = {}): StorageStatus => ({
	disk_usage_percent: 41.2,
	disk_total_bytes: 1e12,
	disk_used_bytes: 4e11,
	disk_free_bytes: 549e9, // decimal GB, as formatBytes prints (NET-166)
	retention: { hot_days: 90 },
	disk_threshold_percent: 80,
	emergency_threshold_percent: 90,
	...over,
});

describe('storage foot', () => {
	it('states use, free space and retention', () => {
		expect(storageFoot(storage())).toEqual({ percent: 41, used: '41% used', detail: '549.0 GB free · 90-day retention' });
	});

	it('leaves out retention the daemon does not report, rather than assuming one', () => {
		expect(storageFoot(storage({ retention: null }))?.detail).toBe('549.0 GB free');
	});

	it('shows nothing for a failed or missing answer', () => {
		expect(storageFoot('failed')).toBeNull();
		expect(storageFoot(null)).toBeNull();
		expect(storageFoot(storage({ disk_usage_percent: Number.NaN }))).toBeNull();
	});
});
