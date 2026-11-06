import type { SmartHealth, StorageStatus } from '../../../src/lib/api/system.ts';
import { HOUR, MIN, iso, type FixtureRoute } from './types.ts';

// OLD CODE START — 2026-11-06 (NET-166): the daemon's disk_*_gb were GiB; they are decimal GB now
// const GIB = 1024 ** 3;
// /** A 1 TB NVMe as the filesystem reports it. */
// const TOTAL_GIB = 931.51;
// OLD CODE END
const GB = 1000 ** 3;
/** A 1 TB NVMe as the filesystem reports it (931.51 GiB), in decimal GB. */
const TOTAL_GB = 1000.2;
const round = (n: number, places: number): number => Math.round(n * 10 ** places) / 10 ** places;

/** The daemon's disk figures for a given used size: bytes, decimal GB (2 dp) and percent (1 dp). */
function diskUsage(usedGb: number) {
	const total = Math.round(TOTAL_GB * GB);
	const used = Math.round(usedGb * GB);
	return {
		disk_total_bytes: total,
		disk_used_bytes: used,
		disk_free_bytes: total - used,
		disk_total_gb: round(TOTAL_GB, 2),
		disk_used_gb: round(usedGb, 2),
		disk_free_gb: round(TOTAL_GB - usedGb, 2),
		disk_usage_percent: round((usedGb / TOTAL_GB) * 100, 1),
	};
}

/** GET /api/storage/status; the extra keys are the ones the Settings page and the web setup route read. */
function storageStatus(usedGb: number, indexCounts: Record<string, number>) {
	return {
		...diskUsage(usedGb),
		hot_days: 90,
		warm_days: 180,
		cold_days: 30,
		disk_threshold_percent: 80,
		emergency_threshold_percent: 90,
		estimated_daily_gb: 1.2,
		source: 'daemon',
		index_counts: indexCounts,
		total_indices: Object.values(indexCounts).reduce((sum, n) => sum + n, 0),
		retention: { hot_days: 90, warm_days: 180, cold_days: 30 },
		last_prune_at: iso(4 * MIN),
		ilm_status: {
			synced: true,
			last_applied: iso(3 * HOUR),
			pending_retry: false,
			policies: {
				'nettap-hot-policy': 'updated',
				'nettap-warm-policy': 'updated',
				'nettap-cold-policy': 'updated',
			},
		},
	} satisfies StorageStatus & Record<string, unknown>;
}

/** Exported so /api/system/health can embed the same figures. */
export const STORAGE_STATUS_POPULATED = storageStatus(372.6, { hot: 38, warm: 12, cold: 4, unknown: 0 });
export const STORAGE_STATUS_EMPTY = storageStatus(18.4, { hot: 0, warm: 0, cold: 0, unknown: 0 });

export const SMART_HEALTH_POPULATED = {
	device: '/dev/nvme0n1',
	device_type: 'nvme',
	model: 'Generic NVMe SSD 1TB',
	serial: 'EXAMPLE0000000001',
	temperature_c: 38,
	percentage_used: 3,
	power_on_hours: 1264,
	total_bytes_written: 18_400_000_000_000,
	total_bytes_read: 22_100_000_000_000,
	media_errors: 0,
	reallocated_sectors: null,
	healthy: true,
	warnings: [],
	timestamp: iso(2 * MIN),
} satisfies SmartHealth;

/** A drive that has barely been used yet. */
export const SMART_HEALTH_EMPTY = {
	...SMART_HEALTH_POPULATED,
	temperature_c: 34,
	percentage_used: 0,
	power_on_hours: 12,
	total_bytes_written: 412_000_000_000,
	total_bytes_read: 96_000_000_000,
} satisfies SmartHealth;

export const STORAGE_ROUTES: FixtureRoute[] = [
	{ path: '/api/storage/status', empty: STORAGE_STATUS_EMPTY, populated: STORAGE_STATUS_POPULATED },
	{ path: '/api/smart/health', empty: SMART_HEALTH_EMPTY, populated: SMART_HEALTH_POPULATED },
];
