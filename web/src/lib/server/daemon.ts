/**
 * Proxy helper for communicating with the nettap-storage-daemon HTTP API.
 */

const DAEMON_URL = process.env.DAEMON_URL || 'http://nettap-storage-daemon:8880';

export interface DaemonError {
	error: string;
	daemonAvailable: false;
}

/**
 * Fetch a path from the NetTap daemon API.
 * Handles connection errors gracefully — returns an error Response
 * instead of throwing if the daemon is unreachable.
 */
export async function daemonFetch(
	path: string,
	options?: RequestInit
): Promise<Response> {
	const url = `${DAEMON_URL}${path}`;

	try {
		const response = await fetch(url, {
			...options,
			headers: {
				'Content-Type': 'application/json',
				...options?.headers,
			},
			signal: options?.signal ?? AbortSignal.timeout(10_000),
		});
		return response;
	} catch (err) {
		const message =
			err instanceof Error ? err.message : 'Unknown error connecting to daemon';
		return new Response(
			JSON.stringify({
				error: `Daemon unreachable: ${message}`,
				daemonAvailable: false,
			} satisfies DaemonError),
			{
				status: 502,
				headers: { 'Content-Type': 'application/json' },
			}
		);
	}
}

/**
 * Convenience: fetch JSON from the daemon and parse it.
 */
export async function daemonJSON<T = unknown>(
	path: string,
	options?: RequestInit
): Promise<{ data?: T; error?: string; status: number }> {
	const res = await daemonFetch(path, options);
	try {
		const data = await res.json();
		if (!res.ok) {
			return { error: data.error || `Daemon returned ${res.status}`, status: res.status };
		}
		return { data: data as T, status: res.status };
	} catch {
		return { error: 'Failed to parse daemon response', status: res.status };
	}
}
