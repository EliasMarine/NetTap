import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import HomePage from './+page.svelte';

/** /api/system/health gets `health` (or HTTP 503 when null); every other request 503s. */
function stubFetch(health: Record<string, unknown> | null) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			if (url.startsWith('/api/system/health') && health) {
				return { ok: true, status: 200, json: async () => health };
			}
			return { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

/** The pipeline stage's status line (System Health moved into the capture pipeline). */
function stage(label: string): string | undefined {
	const item = [...document.querySelectorAll('.pipe-item')].find((el) => el.querySelector('.pipe-k')?.textContent?.trim() === label);
	return item?.querySelector('.pipe-v')?.textContent?.trim();
}

describe('Home — System Health card (#96)', () => {
	beforeEach(() => {
		// jsdom has no ResizeObserver; the bandwidth chart needs one to mount
		vi.stubGlobal(
			'ResizeObserver',
			class {
				observe() {}
				unobserve() {}
				disconnect() {}
			},
		);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says the check failed instead of "Degraded" and "OpenSearch unreachable"', async () => {
		stubFetch(null);

		render(HomePage);

		expect(await screen.findByText("Couldn't check: the request failed")).toBeInTheDocument();
		expect(screen.queryByText('Degraded')).not.toBeInTheDocument();
		expect(screen.queryByText(/OpenSearch unreachable/)).not.toBeInTheDocument();
		expect(screen.queryByText('Unreachable')).not.toBeInTheDocument();
		expect(screen.queryByText(/OpenSearch is not reachable/)).not.toBeInTheDocument();
	});

	it('still reads Healthy when the check succeeds', async () => {
		stubFetch({ uptime: 60, timestamp: '2026-11-02T00:00:00Z', status: 'healthy', healthy: true, opensearch_reachable: true });

		render(HomePage);

		expect(await screen.findByText('Healthy')).toBeInTheDocument();
		// was the card's "OpenSearch connected" line; now the pipeline's OpenSearch stage
		expect(stage('OpenSearch')).toBe('Connected');
		expect(stage('System')).toBe('Healthy');
	});

	it('reads Incomplete, not Degraded, when a check could not run (S5)', async () => {
		stubFetch({ uptime: 60, timestamp: '2026-11-02T00:00:00Z', status: 'incomplete', healthy: null, opensearch_reachable: true });

		render(HomePage);

		expect(await screen.findByText("Incomplete · some checks couldn't run")).toBeInTheDocument();
		expect(screen.queryByText('Degraded')).not.toBeInTheDocument();
	});
});
