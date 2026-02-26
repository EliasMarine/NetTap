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
		const res = await daemonFetch('/api/system/health');
		if (res.ok) {
			daemonHealth = await res.json();
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
