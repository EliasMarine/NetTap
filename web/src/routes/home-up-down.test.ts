import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import HomePage from './+page.svelte';

// NET-226: down and up were the responder's and the originator's bytes, so a port forward's
// answers read as download and LAN-to-LAN traffic counted twice over. They now cross the network edge.

const HEALTH = { uptime: 60, timestamp: '2026-11-02T00:00:00Z', status: 'healthy', healthy: true, opensearch_reachable: true };
const summary = (local: number) => ({
	from: '', to: '', total_bytes: 4_000_000 + local, orig_bytes: 3_000_000, resp_bytes: 1_000_000 + local,
	upload_bytes: 1_000_000, download_bytes: 3_000_000, local_bytes: local,
	packet_count: 0, connection_count: 12, top_protocol: 'tcp',
});

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

const kpi = (label: string) => screen.getByText(label, { selector: '.kpi *' }).closest('.kpi');

describe('Home — download, upload and local (NET-226)', () => {
	beforeEach(() => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	});
	afterEach(() => vi.unstubAllGlobals());

	it('reads upload and download from the network edge, not the originator, and adds local', async () => {
		stubDaemon({ '/api/system/health': HEALTH, '/api/traffic/summary': summary(1_000_000) });
		render(HomePage);
		await screen.findByText('Healthy');
		expect(kpi('Bandwidth')).toHaveTextContent('↓ 3.0 MB down · ↑ 1.0 MB up · 1.0 MB local');
		expect(screen.getByText('On your network')).toBeInTheDocument();
	});

	it('leaves local out of the sub when nothing stayed on the network', async () => {
		stubDaemon({ '/api/system/health': HEALTH, '/api/traffic/summary': summary(0) });
		render(HomePage);
		await screen.findByText('Healthy');
		expect(kpi('Bandwidth')).toHaveTextContent('↓ 3.0 MB down · ↑ 1.0 MB up');
		expect(kpi('Bandwidth')).not.toHaveTextContent('local');
	});
});
