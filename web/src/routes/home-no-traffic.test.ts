import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import HomePage from './+page.svelte';

// The "No traffic data yet" banner needed a null traffic summary, which a successful load never is,
// so it never showed on a network with no traffic.

const HEALTH = { uptime: 60, timestamp: '2026-11-02T00:00:00Z', status: 'healthy', healthy: true, opensearch_reachable: true };
const summary = (connections: number) => ({
	from: '', to: '', total_bytes: connections * 1000, orig_bytes: 0, resp_bytes: 0,
	upload_bytes: 0, download_bytes: connections * 1000, local_bytes: 0,
	packet_count: 0, connection_count: connections, top_protocol: 'tcp',
});

/** Replies by path; any path not listed answers 503. */
function stubDaemon(replies: Record<string, unknown>): void {
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

const BANNER = /No traffic data yet/;

describe('Home — "No traffic data yet" banner', () => {
	beforeEach(() => {
		// jsdom has no ResizeObserver; the bandwidth chart needs one to mount
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows when OpenSearch is up and the summary loaded with 0 connections', async () => {
		stubDaemon({ '/api/system/health': HEALTH, '/api/traffic/summary': summary(0) });
		render(HomePage);
		expect(await screen.findByText(BANNER)).toBeInTheDocument();
	});

	it('does not show when the summary failed to load', async () => {
		stubDaemon({ '/api/system/health': HEALTH });
		render(HomePage);
		expect(await screen.findByText("Couldn't load traffic totals: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText(BANNER)).not.toBeInTheDocument();
	});

	it('does not show when there is traffic', async () => {
		stubDaemon({ '/api/system/health': HEALTH, '/api/traffic/summary': summary(12) });
		render(HomePage);
		expect(await screen.findByText('Healthy')).toBeInTheDocument();
		expect(screen.queryByText(BANNER)).not.toBeInTheDocument();
	});
});
