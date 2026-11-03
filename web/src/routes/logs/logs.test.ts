import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import Page from './+page.svelte';

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/logs') }),
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

describe('Log Explorer', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});
});

// #96: failed aggregations read as 0 events, 0 B and "No protocol data"

/** Replies by path; any path not listed answers 503. */
function stubDaemon(replies: Record<string, unknown>): void {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const body = replies[url.split('?')[0]];
			return body
				? { ok: true, status: 200, json: async () => body }
				: { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

describe('Log Explorer — failed aggregations', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('says what failed instead of 0 events and "No protocol data"', async () => {
		stubDaemon({});
		render(Page);
		expect(await screen.findByText("Couldn't load log totals: the request failed.")).toBeInTheDocument();
		expect(screen.getByText('Total Events').closest('.stat-card')).not.toHaveTextContent('0');
		expect(screen.getByText("Couldn't load protocols: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No protocol data')).not.toBeInTheDocument();
		expect(screen.getByText("Couldn't load the activity timeline: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load top DNS queries: the request failed.")).toBeInTheDocument();
	});

	it('still says "No protocol data" when the range really has none', async () => {
		stubDaemon({ '/api/logs/protocol-breakdown': { from: '', to: '', protocols: [] } });
		render(Page);
		expect(await screen.findByText('No protocol data')).toBeInTheDocument();
	});
});
