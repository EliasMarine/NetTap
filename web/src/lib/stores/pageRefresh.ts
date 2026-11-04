/**
 * Page refresh contract (PLAN.md §5.5).
 *
 * Pages fetch in onMount/effects, so invalidateAll() would not refresh them. Instead
 * the current page registers its loader; the top bar's Refresh button and "Updated"
 * time go through it. A loader reports what actually happened, and a load guard keeps
 * a slow, older request from overwriting newer data or touching a page that has gone.
 */
import { writable, type Readable } from 'svelte/store';

export type LoadResult = 'ok' | 'partial' | 'failed' | 'skipped';

export interface RefreshState {
	/** A page with a loader is registered (the top bar shows Refresh and "Updated"). */
	available: boolean;
	running: boolean;
	/** Epoch ms of the last load that returned 'ok'. */
	updatedAt: number | null;
	/** The last finished load was partial or failed. */
	status: 'ok' | 'partial' | 'failed' | null;
}

export interface LoadGuard {
	/** Start a load: returns its generation and invalidates every older one. */
	begin(): number;
	/** True while `generation` is the newest load and the page is still registered. */
	current(generation: number): boolean;
	/** The page has gone: no pending load may write again. */
	invalidate(): void;
}

export function createLoadGuard(): LoadGuard {
	let generation = 0;
	let alive = true;
	return {
		begin: () => (alive ? ++generation : -1),
		current: (g) => alive && g === generation,
		invalidate: () => {
			alive = false;
		},
	};
}

export interface PageRefreshHandle {
	guard: LoadGuard;
	/** Run the loader through the contract. Pages use this for every load, so "Updated" stays honest. */
	run(): Promise<LoadResult>;
	unregister(): void;
}

const IDLE: RefreshState = { available: false, running: false, updatedAt: null, status: null };
const state = writable<RefreshState>(IDLE);
export const pageRefresh: Readable<RefreshState> = { subscribe: state.subscribe };

let active: { id: number; run: () => Promise<LoadResult> } | null = null;
let nextId = 0;

/**
 * Register the current page's loader. The loader must await every request that feeds
 * visible data, check `guard.current(g)` before each state write, and return the result.
 * Call `unregister` on destroy.
 */
export function registerPageRefresh(
	loader: (guard: LoadGuard) => Promise<LoadResult>,
	now: () => number = Date.now,
): PageRefreshHandle {
	const guard = createLoadGuard();
	// Server rendering shares this module between requests, and loaders only run in the browser.
	if (typeof window === 'undefined') {
		return { guard, run: async () => 'skipped', unregister: () => guard.invalidate() };
	}
	const id = ++nextId;
	let inFlight = 0;

	async function run(): Promise<LoadResult> {
		if (active?.id !== id) return 'skipped';
		inFlight++;
		state.update((s) => ({ ...s, running: true }));
		let result: LoadResult;
		try {
			result = await loader(guard);
		} catch {
			result = 'failed';
		}
		inFlight--;
		if (active?.id !== id) return result;
		state.update((s) => ({
			...s,
			running: inFlight > 0,
			updatedAt: result === 'ok' ? now() : s.updatedAt,
			status: result === 'skipped' ? s.status : result,
		}));
		return result;
	}

	active = { id, run };
	state.set({ ...IDLE, available: true });

	return {
		guard,
		run,
		unregister() {
			guard.invalidate();
			if (active?.id === id) {
				active = null;
				state.set(IDLE);
			}
		},
	};
}

/** The top bar's Refresh button. */
export function refreshPage(): Promise<LoadResult> {
	return active ? active.run() : Promise.resolve('skipped');
}

/** A loader's result from the requests that feed the page: every one succeeded, some failed, or all failed. */
export function outcome(results: readonly PromiseSettledResult<unknown>[]): LoadResult {
	const failed = results.filter((r) => r.status === 'rejected').length;
	if (failed === 0) return 'ok';
	return failed === results.length ? 'failed' : 'partial';
}
