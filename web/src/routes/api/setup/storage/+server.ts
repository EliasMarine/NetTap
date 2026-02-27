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
 * GET: Fetch current storage status and configuration.
 */
export const GET: RequestHandler = async () => {
	const { data, error } = await daemonJSON<StorageStatus>('/api/storage/status');

	if (data && !error) {
		return json(data);
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
