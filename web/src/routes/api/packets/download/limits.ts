/**
 * How long the download route waits for the daemon's headers. The daemon sends them
 * with the first verified packet, after its slot wait and job start (about 45 s at
 * most); the stream after that has no limit. Kept out of +server.ts: SvelteKit
 * refuses any other export from an endpoint at build time.
 */
export const DOWNLOAD_HEADERS_TIMEOUT_MS = 60_000;
