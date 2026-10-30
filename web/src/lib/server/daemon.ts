/**
 * Proxy helper for communicating with the nettap-storage-daemon HTTP API.
 *
 * Every daemon request carries the shared token from the read-only
 * daemon-auth volume. The token never reaches the browser, logs or responses.
 */

import { readFileSync } from 'fs';

const DAEMON_URL = process.env.DAEMON_URL || 'http://nettap-storage-daemon:8880';
const DAEMON_TOKEN_FILE = process.env.DAEMON_TOKEN_FILE || '/run/nettap-auth/daemon-token';
const DAEMON_TOKEN_HEADER = 'X-NetTap-Daemon-Token';

let cachedToken: string | null = null;
let warnedTokenMissing = false;

/** Read the token lazily; cached once found, re-read after a 401. */
function readDaemonToken(): string | null {
	if (cachedToken) return cachedToken;
	try {
		cachedToken = readFileSync(DAEMON_TOKEN_FILE, 'utf-8').trim() || null;
		warnedTokenMissing = false;
	} catch (err) {
		// Warn once per outage; daemon calls go out without the header and get 401.
		if (!warnedTokenMissing) {
			warnedTokenMissing = true;
			const code = (err as NodeJS.ErrnoException).code ?? 'unknown error';
			console.error(`Daemon token not readable at ${DAEMON_TOKEN_FILE} (${code})`);
		}
	}
	return cachedToken;
}

export interface DaemonError {
	error: string;
	daemonAvailable: false;
}

/**
 * Fetch a path from the NetTap daemon API.
 * Handles connection errors gracefully — returns an error Response
 * instead of throwing if the daemon is unreachable.
 *
 * @param path - API path (e.g. '/api/tshark/analyze')
 * @param options - Standard RequestInit options
 * @param timeout - Request timeout in milliseconds (default 10_000).
 *                  Override for long-running operations like TShark analysis.
 */
export async function daemonFetch(
	path: string,
	options?: RequestInit,
	timeout: number = 10_000
): Promise<Response> {
	const url = `${DAEMON_URL}${path}`;
	const signal = options?.signal ?? AbortSignal.timeout(timeout);
	const send = (token: string | null) =>
		fetch(url, {
			...options,
			headers: {
				'Content-Type': 'application/json',
				...options?.headers,
				...(token ? { [DAEMON_TOKEN_HEADER]: token } : {}),
			},
			signal,
		});

	try {
		// OLD CODE START — sent no daemon token (2026-10-29)
		// const response = await fetch(url, {
		// 	...options,
		// 	headers: {
		// 		'Content-Type': 'application/json',
		// 		...options?.headers,
		// 	},
		// 	signal: options?.signal ?? AbortSignal.timeout(timeout),
		// });
		// return response;
		// OLD CODE END
		const sentToken = readDaemonToken();
		const response = await send(sentToken);
		if (response.status !== 401) return response;

		// The daemon may have regenerated its token: re-read and retry once.
		// Safe for any method because the daemon rejects before any handler runs.
		cachedToken = null;
		const freshToken = readDaemonToken();
		return freshToken && freshToken !== sentToken ? await send(freshToken) : response;
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
	options?: RequestInit,
	timeout?: number
): Promise<{ data?: T; error?: string; status: number }> {
	const res = await daemonFetch(path, options, timeout);
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
