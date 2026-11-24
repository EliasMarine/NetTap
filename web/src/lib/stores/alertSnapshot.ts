/**
 * One global alert count per time window, shared by the sidebar badge, Home's Alerts KPI
 * and the Alerts page's severity summary (PLAN.md §4.1: "Numbers agree across screens").
 *
 * Callers read the store, not their own copy, so a refresh from any of them moves every
 * reader at once. Each refresh generation fixes one absolute window per range, so readers
 * never ask the daemon about slightly different minutes.
 */
import { writable, get, type Readable } from 'svelte/store';
import { getAlertCount, type AlertCountResponse } from '$api/alerts';

export interface AlertSnapshot {
	status: 'loading' | 'ok' | 'error';
	hours: number;
	from: string;
	to: string;
	/** On 'error', the last good counts for this range (stale, #96), or null if none loaded yet. */
	data: AlertCountResponse | null;
	/** When `data` landed (ms). On 'error' with kept counts, `from`, `to` and `at` stay theirs (NET-348). */
	at?: number;
}

type Fetcher = (params: { from: string; to: string }) => Promise<AlertCountResponse>;

const MINUTE = 60_000;

/** The absolute window for `hours` ending at `nowMs`, rounded down to the minute. */
export function snapshotWindow(hours: number, nowMs: number): { from: string; to: string } {
	const to = Math.floor(nowMs / MINUTE) * MINUTE;
	return { from: new Date(to - hours * 3_600_000).toISOString(), to: new Date(to).toISOString() };
}

const state = writable<Record<number, AlertSnapshot>>({});
export const alertSnapshots: Readable<Record<number, AlertSnapshot>> = { subscribe: state.subscribe };

let generation = 0;
let generationStart = Date.now();
const inFlight = new Map<number, { generation: number; promise: Promise<AlertSnapshot> }>();
/** NET-361: under the shell's 30 s refresh, above the web route's 10 s daemon budget. */
const COUNT_TIMEOUT_MS = 15_000;
// OLD CODE: let fetcher: Fetcher = (p) => getAlertCount(p); (NET-361: a stalled count, body included, outlived the next refresh)
let fetcher: Fetcher = (p) => getAlertCount(p, AbortSignal.timeout(COUNT_TIMEOUT_MS));
let clock: () => number = Date.now;

/** Test seam. */
export function _configure(options: { fetcher?: Fetcher; now?: () => number }): void {
	if (options.fetcher) fetcher = options.fetcher;
	if (options.now) clock = options.now;
	generation = 0;
	generationStart = clock();
	inFlight.clear();
	state.set({});
}

/**
 * Load (or join the in-flight load of) the snapshot for `hours` in the current generation.
 * A response from an older generation never replaces a newer one.
 */
export function loadAlertSnapshot(hours: number): Promise<AlertSnapshot> {
	// Server rendering shares this module between requests and can't call relative /api URLs.
	if (typeof window === 'undefined') {
		return Promise.resolve({ status: 'loading', hours, ...snapshotWindow(hours, Date.now()), data: null });
	}
	const pending = inFlight.get(hours);
	if (pending && pending.generation === generation) return pending.promise;

	const myGeneration = generation;
	const range = snapshotWindow(hours, generationStart);
	const existing = get(state)[hours];
	// Keep showing the previous numbers while the next generation loads.
	if (!existing) state.update((s) => ({ ...s, [hours]: { status: 'loading', hours, ...range, data: null } }));

	// OLD CODE START — NET-348: kept counts took the failed attempt's window, so they named minutes they never counted
	// const promise = fetcher(range)
	// 	.then((data): AlertSnapshot => ({ status: 'ok', hours, ...range, data }))
	// 	.catch((): AlertSnapshot => ({ status: 'error', hours, ...range, data: get(state)[hours]?.data ?? null }))
	// OLD CODE END
	const promise = fetcher(range)
		.then((data): AlertSnapshot => ({ status: 'ok', hours, ...range, data, at: clock() }))
		.catch((): AlertSnapshot => {
			const kept = get(state)[hours];
			return kept?.data ? { ...kept, status: 'error' } : { status: 'error', hours, ...range, data: null };
		})
		.then((snap) => {
			if (myGeneration === generation) state.update((s) => ({ ...s, [hours]: snap }));
			if (inFlight.get(hours)?.promise === promise) inFlight.delete(hours);
			return get(state)[hours] ?? snap;
		});
	inFlight.set(hours, { generation: myGeneration, promise });
	return promise;
}

/** Start a new generation (new window) and reload every range someone has loaded. */
export function refreshAlertSnapshots(): Promise<AlertSnapshot[]> {
	generation++;
	generationStart = clock();
	return Promise.all(Object.keys(get(state)).map((h) => loadAlertSnapshot(Number(h))));
}
