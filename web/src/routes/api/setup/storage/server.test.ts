import { describe, it, expect } from 'vitest';

/**
 * Tests for the normalizeStorageStatus function in the storage API proxy.
 *
 * We re-implement the normalization logic here to test it in isolation
 * (the actual function is inside +server.ts which depends on SvelteKit imports).
 */

interface StorageStatus {
	disk_total_gb: number;
	disk_used_gb: number;
	disk_free_gb: number;
	disk_usage_percent: number;
	hot_days: number;
	warm_days: number;
	cold_days: number;
	disk_threshold_percent: number;
	emergency_threshold_percent: number;
	estimated_daily_gb: number;
	source: 'daemon' | 'mock';
}

/** Mirror of normalizeStorageStatus from +server.ts */
function normalizeStorageStatus(raw: Record<string, unknown>): StorageStatus {
	const diskTotalGb = (raw.disk_total_gb as number) ?? 0;
	const diskUsedGb = (raw.disk_used_gb as number) ?? 0;
	const diskFreeGb = (raw.disk_free_gb as number) ?? 0;

	let usagePct = 0;
	if (typeof raw.disk_usage_percent === 'number') {
		usagePct = raw.disk_usage_percent;
	} else if (typeof raw.disk_usage_percent === 'string') {
		usagePct = parseFloat(raw.disk_usage_percent) || 0;
	} else if (typeof raw.disk_usage === 'number') {
		usagePct = (raw.disk_usage as number) * 100;
	}

	const retention = (raw.retention as Record<string, number>) ?? {};
	const hotDays = (raw.hot_days as number) ?? retention.hot_days ?? 90;
	const warmDays = (raw.warm_days as number) ?? retention.warm_days ?? 180;
	const coldDays = (raw.cold_days as number) ?? retention.cold_days ?? 30;

	let thresholdPct = (raw.disk_threshold_percent as number) ?? 0;
	if (!thresholdPct && typeof raw.disk_threshold === 'number') {
		thresholdPct =
			(raw.disk_threshold as number) <= 1
				? (raw.disk_threshold as number) * 100
				: (raw.disk_threshold as number);
	}
	let emergencyPct = (raw.emergency_threshold_percent as number) ?? 0;
	if (!emergencyPct && typeof raw.emergency_threshold === 'number') {
		emergencyPct =
			(raw.emergency_threshold as number) <= 1
				? (raw.emergency_threshold as number) * 100
				: (raw.emergency_threshold as number);
	}

	return {
		disk_total_gb: diskTotalGb,
		disk_used_gb: diskUsedGb,
		disk_free_gb: diskFreeGb,
		disk_usage_percent: Math.round(usagePct * 10) / 10,
		hot_days: hotDays,
		warm_days: warmDays,
		cold_days: coldDays,
		disk_threshold_percent: thresholdPct || 80,
		emergency_threshold_percent: emergencyPct || 90,
		estimated_daily_gb: (raw.estimated_daily_gb as number) ?? 1.2,
		source: 'daemon',
	};
}

describe('normalizeStorageStatus', () => {
	it('handles new daemon format (absolute GB values, 0-100 percentages)', () => {
		const raw = {
			disk_total_gb: 953.87,
			disk_used_gb: 42.3,
			disk_free_gb: 911.57,
			disk_usage_percent: 4.4,
			hot_days: 90,
			warm_days: 180,
			cold_days: 30,
			disk_threshold_percent: 80,
			emergency_threshold_percent: 90,
			estimated_daily_gb: 1.2,
			source: 'daemon',
		};

		const result = normalizeStorageStatus(raw);

		expect(result.disk_total_gb).toBe(953.87);
		expect(result.disk_free_gb).toBe(911.57);
		expect(result.disk_usage_percent).toBe(4.4);
		expect(result.hot_days).toBe(90);
		expect(result.disk_threshold_percent).toBe(80);
		expect(result.emergency_threshold_percent).toBe(90);
		expect(result.source).toBe('daemon');
	});

	it('handles old daemon format (fraction-based, nested retention, string percent)', () => {
		const raw = {
			disk_usage: 0.023,
			disk_usage_percent: '2.3%',
			disk_threshold: 0.8,
			emergency_threshold: 0.9,
			check_path: '/',
			retention: {
				hot_days: 90,
				warm_days: 180,
				cold_days: 30,
			},
			index_counts: { hot: 5, warm: 2, cold: 1, unknown: 0 },
			total_indices: 8,
		};

		const result = normalizeStorageStatus(raw);

		// Percentage parsed from string
		expect(result.disk_usage_percent).toBe(2.3);
		// GB values default to 0 (old format doesn't have them)
		expect(result.disk_total_gb).toBe(0);
		expect(result.disk_free_gb).toBe(0);
		// Retention extracted from nested object
		expect(result.hot_days).toBe(90);
		expect(result.warm_days).toBe(180);
		expect(result.cold_days).toBe(30);
		// Thresholds converted from 0-1 to 0-100
		expect(result.disk_threshold_percent).toBe(80);
		expect(result.emergency_threshold_percent).toBe(90);
		// Default estimated daily
		expect(result.estimated_daily_gb).toBe(1.2);
	});

	it('handles completely empty response with safe defaults', () => {
		const result = normalizeStorageStatus({});

		expect(result.disk_total_gb).toBe(0);
		expect(result.disk_free_gb).toBe(0);
		expect(result.disk_usage_percent).toBe(0);
		expect(result.hot_days).toBe(90);
		expect(result.warm_days).toBe(180);
		expect(result.cold_days).toBe(30);
		expect(result.disk_threshold_percent).toBe(80);
		expect(result.emergency_threshold_percent).toBe(90);
		expect(result.estimated_daily_gb).toBe(1.2);
	});

	it('handles old format with only disk_usage fraction (no disk_usage_percent)', () => {
		const raw = {
			disk_usage: 0.65,
			disk_threshold: 0.8,
			emergency_threshold: 0.9,
		};

		const result = normalizeStorageStatus(raw);

		expect(result.disk_usage_percent).toBe(65);
		expect(result.disk_threshold_percent).toBe(80);
		expect(result.emergency_threshold_percent).toBe(90);
	});

	it('prefers top-level retention days over nested', () => {
		const raw = {
			hot_days: 60,
			warm_days: 120,
			cold_days: 14,
			retention: {
				hot_days: 90,
				warm_days: 180,
				cold_days: 30,
			},
		};

		const result = normalizeStorageStatus(raw);

		expect(result.hot_days).toBe(60);
		expect(result.warm_days).toBe(120);
		expect(result.cold_days).toBe(14);
	});
});
