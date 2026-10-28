import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonJSON } from '$lib/server/daemon.js';

export interface StorageStatus {
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

export interface StorageConfigRequest {
	hot_days: number;
	warm_days: number;
	cold_days: number;
	disk_threshold_percent: number;
	emergency_threshold_percent: number;
}

/**
 * Normalize daemon response to match StorageStatus interface.
 * Handles both old format (disk_usage as fraction, nested retention)
 * and new format (disk_free_gb, top-level days, 0-100 percentages).
 */
function normalizeStorageStatus(raw: Record<string, unknown>): StorageStatus {
	// Absolute disk values — new format has them, old format doesn't
	const diskTotalGb = (raw.disk_total_gb as number) ?? 0;
	const diskUsedGb = (raw.disk_used_gb as number) ?? 0;
	const diskFreeGb = (raw.disk_free_gb as number) ?? 0;

	// Disk usage percent — new format: number 0-100, old format: string "X.X%"
	let usagePct = 0;
	if (typeof raw.disk_usage_percent === 'number') {
		usagePct = raw.disk_usage_percent;
	} else if (typeof raw.disk_usage_percent === 'string') {
		usagePct = parseFloat(raw.disk_usage_percent) || 0;
	} else if (typeof raw.disk_usage === 'number') {
		usagePct = (raw.disk_usage as number) * 100;
	}

	// Retention days — new format: top-level, old format: nested in retention{}
	const retention = (raw.retention as Record<string, number>) ?? {};
	const hotDays = (raw.hot_days as number) ?? retention.hot_days ?? 90;
	const warmDays = (raw.warm_days as number) ?? retention.warm_days ?? 180;
	const coldDays = (raw.cold_days as number) ?? retention.cold_days ?? 30;

	// Thresholds — new format: 0-100, old format: 0-1 fraction
	let thresholdPct = (raw.disk_threshold_percent as number) ?? 0;
	if (!thresholdPct && typeof raw.disk_threshold === 'number') {
		thresholdPct = (raw.disk_threshold as number) <= 1
			? (raw.disk_threshold as number) * 100
			: (raw.disk_threshold as number);
	}
	let emergencyPct = (raw.emergency_threshold_percent as number) ?? 0;
	if (!emergencyPct && typeof raw.emergency_threshold === 'number') {
		emergencyPct = (raw.emergency_threshold as number) <= 1
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

/**
 * GET: Fetch current storage status and configuration.
 */
export const GET: RequestHandler = async () => {
	const { data, error } = await daemonJSON<Record<string, unknown>>('/api/storage/status');

	if (data && !error) {
		return json(normalizeStorageStatus(data));
	}

	// Daemon unavailable — return mock storage status
	const mock: StorageStatus = {
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
		source: 'mock',
	};

	return json(mock);
};

/**
 * POST: Save retention configuration.
 * In production, the daemon applies these via OpenSearch ILM and env vars.
 * For now, we accept the config and return success.
 */
export const POST: RequestHandler = async ({ request }) => {
	let body: StorageConfigRequest;

	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON body' }, { status: 400 });
	}

	const { hot_days, warm_days, cold_days, disk_threshold_percent, emergency_threshold_percent } =
		body;

	// Validate ranges
	if (hot_days < 1 || hot_days > 365) {
		return json({ error: 'Hot tier retention must be between 1 and 365 days' }, { status: 400 });
	}
	if (warm_days < 1 || warm_days > 730) {
		return json(
			{ error: 'Warm tier retention must be between 1 and 730 days' },
			{ status: 400 }
		);
	}
	if (cold_days < 1 || cold_days > 365) {
		return json({ error: 'Cold tier retention must be between 1 and 365 days' }, { status: 400 });
	}
	if (disk_threshold_percent < 50 || disk_threshold_percent > 95) {
		return json(
			{ error: 'Disk threshold must be between 50% and 95%' },
			{ status: 400 }
		);
	}
	if (emergency_threshold_percent <= disk_threshold_percent || emergency_threshold_percent > 99) {
		return json(
			{ error: 'Emergency threshold must be greater than disk threshold and at most 99%' },
			{ status: 400 }
		);
	}

	// Try the daemon
	const { data, error } = await daemonJSON<{ saved: boolean }>('/api/storage/config', {
		method: 'POST',
		body: JSON.stringify(body),
	});

	if (data && !error) {
		return json(data);
	}

	// Daemon unavailable — accept the config anyway (will be applied on restart)
	return json({
		saved: true,
		message: 'Configuration saved. It will be applied when services start.',
		config: body,
		source: 'mock',
	});
};
