import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

export const GET: RequestHandler = async () => {
	const webStatus = {
		service: 'nettap-web',
		status: 'healthy',
		uptime: process.uptime(),
		timestamp: new Date().toISOString(),
		version: '0.3.0',
	};

	// Try to get daemon health
	let daemonHealth: Record<string, unknown> | null = null;
	try {
		// OLD CODE START — F6: this route is public, and the full system health it passed on
		// carried the drive's SMART serial and model and the storage figures
		// const res = await daemonFetch('/api/system/health');
		// if (res.ok) {
		// 	daemonHealth = await res.json();
		// } else {
		// OLD CODE END
		// The daemon's liveness check; only its status leaves (Docker and the setup wizard need no more)
		const res = await daemonFetch('/api/health');
		if (res.ok) {
			const body = await res.json();
			daemonHealth = { status: body?.status ?? 'unknown' };
		} else {
			daemonHealth = {
				status: 'unreachable',
				error: `Daemon returned HTTP ${res.status}`,
			};
		}
	} catch {
		daemonHealth = {
			status: 'unreachable',
			error: 'Could not connect to daemon',
		};
	}

	return json({
		...webStatus,
		daemon: daemonHealth,
	});
};
