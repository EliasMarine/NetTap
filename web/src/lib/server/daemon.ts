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
// Review L5: with the daemon down, Live and the shell poll every few seconds, so the log says it
// once when it goes down and once when it answers again
let daemonDown = false;
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
 * The threat report and its beaconing scan read every internet pair's timings: on the G11 that is
 * ~13 s for 24 h and ~65 s for 7 days (2026-11-07), past the 10 s default. The browser's own limit
 * (getThreatReport) sits just above this one, so the route always answers first.
 */
export const THREAT_SCAN_TIMEOUT_MS = 120_000;

/**
 * A rule update, or saving/removing the ET Pro code, can take minutes: the daemon waits up to 240 s for
 * the rules lock, runs suricata-update and restarts Suricata, and answers 202 by ~270 s (NET-191 slice 2).
 */
export const RULE_UPDATE_TIMEOUT_MS = 290_000;

/**
 * NET-203: each Tools page's daemon call, 5 s above the daemon's own limit for that tool, so a slow
 * but working tool answers instead of being cut off. The 10 s default sat below all four: a 15 s DNS
 * lookup on the G11 (2026-11-07) read "Daemon unreachable". All stay under nginx's 60 s proxy_read_timeout.
 */
export const TOOL_TIMEOUT_MS = {
	'dns-recon': 15_000, // daemon/services/dns_recon_service.py QUERY_TIMEOUT (10 s; its queries run at once)
	'dns-compare': 15_000, // the same QUERY_TIMEOUT: one dig per resolver, all at once (NET-262)
	ping: 20_000, // daemon/services/network_diag_service.py PING_TIMEOUT (15 s)
	traceroute: 35_000, // daemon/services/network_diag_service.py TRACEROUTE_TIMEOUT (30 s)
	'ssl-cert': 25_000, // daemon/services/ssl_cert_service.py CERT_TIMEOUT (10 s), twice: s_client, then x509
	throughput: 55_000, // daemon/services/throughput_service.py: MAX_DURATION (30 s) + DEADLINE_SLACK (20 s), NET-266
} as const;

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
		if (daemonDown) {
			daemonDown = false;
			console.info('Daemon reachable again');
		}
		if (response.status !== 401) return response;

		// The daemon may have regenerated its token: re-read and retry once.
		// Safe for any method because the daemon rejects before any handler runs.
		cachedToken = null;
		const freshToken = readDaemonToken();
		return freshToken && freshToken !== sentToken ? await send(freshToken) : response;
	} catch (err) {
		const message =
			err instanceof Error ? err.message : 'Unknown error connecting to daemon';
		// NET-203: a time limit running out is not "unreachable"; the daemon may still be working.
		// AbortSignal.timeout rejects with a DOMException named TimeoutError.
		const timedOut = (err as { name?: unknown } | null)?.name === 'TimeoutError';
		// A caller's own abort (e.g. the packet download's deadline) says nothing about the daemon
		const aborted = (err as { name?: unknown } | null)?.name === 'AbortError';
		// NET-229 (B-p): the reason (host:port, errno) stays in this log, not in the reply
		// OLD CODE: if (!timedOut) console.error(`Daemon unreachable for ${path}: ${message}`); (review L5: a line per poll while down)
		if (!timedOut && !aborted && !daemonDown) {
			daemonDown = true;
			console.error(`Daemon unreachable for ${path}: ${message} (logged once until it answers again)`);
		}
		return new Response(
			JSON.stringify({
				// OLD CODE: error: `Daemon unreachable: ${message}`, (NET-203: a timeout read as the daemon being down)
				// OLD CODE: error: timedOut ? 'NetTap took too long to answer. Try again.' : `Daemon unreachable: ${message}`, (NET-229: carried the exception text)
				error: timedOut ? 'NetTap took too long to answer. Try again.' : 'Daemon unreachable',
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
