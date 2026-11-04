import type { LoadResult } from '$lib/stores/pageRefresh';

/**
 * A loader's result from the requests that feed the page (PLAN.md §5.5): every one
 * succeeded, some failed, or all failed.
 * shortcut: lives with the device routes (lib/ is lead-owned); move to lib/stores/pageRefresh.ts.
 */
export function outcome(results: readonly PromiseSettledResult<unknown>[]): LoadResult {
	const failed = results.filter((r) => r.status === 'rejected').length;
	if (failed === 0) return 'ok';
	return failed === results.length ? 'failed' : 'partial';
}
