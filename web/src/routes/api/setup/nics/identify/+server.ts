import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonJSON } from '$lib/server/daemon.js';

export interface NicIdentifyRequest {
	interface: string;
	duration?: number;
}

export interface NicIdentifyResponse {
	result: string;
	interface: string;
	duration: number;
}

/**
 * POST /api/setup/nics/identify
 *
 * Proxy to daemon's NIC LED blink identification endpoint.
 * Falls back to a mock success response when the daemon is unreachable
 * (development without real hardware).
 */
export const POST: RequestHandler = async ({ request }) => {
	const body: NicIdentifyRequest = await request.json();

	const { data, error } = await daemonJSON<NicIdentifyResponse>(
		'/api/setup/nics/identify',
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body),
		}
	);

	if (data && !error) {
		return json(data);
	}

	// Daemon unavailable — return mock success for development
	const duration = Math.min(Math.max(body.duration ?? 15, 1), 30);
	const mockResponse: NicIdentifyResponse = {
		result: 'blinking',
		interface: body.interface,
		duration,
	};

	return json(mockResponse);
};
