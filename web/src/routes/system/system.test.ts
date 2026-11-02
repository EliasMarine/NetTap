import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import SystemPage from './+page.svelte';

/** Every request fails except /api/capture/mode; returns the list of requested URLs. */
function stubFetch(mode: string): string[] {
	const urls: string[] = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			urls.push(url);
			if (url === '/api/capture/mode') {
				return new Response(JSON.stringify({ mode, interface: 'enp1s0' }), { status: 200 });
			}
			return new Response(JSON.stringify({ error: 'not under test' }), { status: 503 });
		})
	);
	return urls;
}

describe('System page bridge panel', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it.each(['dhcp_gateway', 'mirror'])('hides BridgeStatus and never polls /api/bridge in %s mode', async (mode) => {
		const urls = stubFetch(mode);

		const { container } = render(SystemPage);
		await vi.waitFor(() => expect(urls).toContain('/api/capture/mode'));
		await new Promise((r) => setTimeout(r, 0));

		expect(container.querySelector('.bridge-card')).toBeNull();
		expect(urls.filter((u) => u.startsWith('/api/bridge'))).toEqual([]);
	});

	it('shows BridgeStatus and fetches bridge health in bridge mode', async () => {
		const urls = stubFetch('bridge');

		const { container } = render(SystemPage);

		await vi.waitFor(() => expect(container.querySelector('.bridge-card')).not.toBeNull());
		await vi.waitFor(() => expect(urls.some((u) => u.startsWith('/api/bridge'))).toBe(true));
	});

	it('says the capture mode could not be read instead of assuming bridge (#96)', async () => {
		const urls = stubFetch('unused');
		vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
			urls.push(String(input));
			return new Response(JSON.stringify({ error: 'down' }), { status: 503 });
		});

		const { container } = render(SystemPage);

		expect(await screen.findByText("Couldn't read the capture mode, so bridge status isn't shown.")).toBeInTheDocument();
		expect(container.querySelector('.bridge-card')).toBeNull();
	});
});

describe('System page when status requests fail (#96)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says each card could not be loaded instead of "Degraded" or "requires smartmontools"', async () => {
		stubFetch('mirror');

		render(SystemPage);

		expect(await screen.findByText("Couldn't load system health: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load storage status: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load drive health: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('Degraded')).not.toBeInTheDocument();
		expect(screen.queryByText('Disconnected')).not.toBeInTheDocument();
		expect(screen.queryByText(/requires smartmontools/)).not.toBeInTheDocument();
		expect(screen.queryByText(/% used/)).not.toBeInTheDocument();
		// TShark and CyberChef: a failed status check is not "Not Deployed"
		expect(screen.getAllByText("couldn't check")).toHaveLength(2);
		expect(screen.queryByText('Not Deployed')).not.toBeInTheDocument();
	});

	it('still shows Healthy and the disk usage when the requests succeed', async () => {
		const replies: Record<string, unknown> = {
			'/api/capture/mode': { mode: 'mirror', interface: 'enp4s0' },
			'/api/system/health': { uptime: 60, timestamp: '2026-11-02T00:00:00Z', healthy: true, opensearch_reachable: true },
			'/api/storage/status': { disk_usage_percent: 42, disk_total_bytes: 100, disk_used_bytes: 42, disk_free_bytes: 58, retention: null },
		};
		vi.stubGlobal(
			'fetch',
			vi.fn(async (input: RequestInfo | URL) => {
				const body = replies[String(input)];
				return body ? new Response(JSON.stringify(body), { status: 200 }) : new Response('{}', { status: 503 });
			}),
		);

		render(SystemPage);

		expect(await screen.findByText('Healthy')).toBeInTheDocument();
		expect(screen.getByText('42.0% used')).toBeInTheDocument();
		expect(screen.queryByText("Couldn't load system health: the request failed.")).not.toBeInTheDocument();
	});
});
