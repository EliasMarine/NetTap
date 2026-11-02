import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import BridgeStatus from './BridgeStatus.svelte';

const HEALTH = {
	bridge_state: 'up',
	wan_link: true,
	lan_link: true,
	bypass_active: false,
	watchdog_active: true,
	latency_us: 120,
	rx_bytes_delta: 2048,
	tx_bytes_delta: 1024,
	rx_packets_delta: 10,
	tx_packets_delta: 5,
	uptime_seconds: 3600,
	health_status: 'normal',
	issues: [],
	last_check: '',
};

/** Answer each URL with its body, or HTTP 500 when the body is null. */
function stubFetch(replies: Record<string, unknown>) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: RequestInfo | URL) => {
			const body = replies[String(input)];
			if (body == null) return new Response('{}', { status: 500 });
			return new Response(JSON.stringify(body), { status: 200 });
		}),
	);
}

describe('BridgeStatus when a request fails (#96)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says bridge health could not be checked instead of "Down"', async () => {
		stubFetch({});

		render(BridgeStatus);

		expect(await screen.findByText("Couldn't check bridge health: the request failed.")).toBeInTheDocument();
		expect(screen.getByText('Unknown')).toBeInTheDocument();
		expect(screen.queryByText('Down')).not.toBeInTheDocument();
		expect(screen.queryByText('Link Down')).not.toBeInTheDocument();
	});

	it('says bypass is unknown, not inactive, and offers no toggle', async () => {
		stubFetch({ '/api/bridge/health': HEALTH });

		render(BridgeStatus);

		expect(await screen.findByText('Bypass Mode')).toBeInTheDocument();
		expect(screen.getByText('Unknown')).toBeInTheDocument();
		expect(screen.queryByText('Inactive')).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Enable Bypass' })).toBeDisabled();
	});

	it('reads bypass as active when the daemon says bypass_active', async () => {
		stubFetch({ '/api/bridge/health': HEALTH, '/api/bridge/bypass/status': { bypass_active: true } });

		render(BridgeStatus);

		expect(await screen.findByRole('button', { name: 'Disable Bypass' })).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Enable Bypass' })).not.toBeInTheDocument();
	});

	it('still reads Normal and Inactive when both requests succeed', async () => {
		stubFetch({ '/api/bridge/health': HEALTH, '/api/bridge/bypass/status': { bypass_active: false } });

		render(BridgeStatus);

		expect(await screen.findByText('Inactive')).toBeInTheDocument();
		expect(screen.getAllByText('Normal').length).toBeGreaterThan(0);
		expect(screen.queryByText("Couldn't check bridge health: the request failed.")).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Enable Bypass' })).toBeEnabled();
	});
});

// The daemon now sends latency_us: null (with latency_note) instead of a made-up 50 µs.
describe('BridgeStatus latency', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	const NOTE = "Not measured: NetTap can't time packets through the bridge";

	it('says Not measured, with the reason, when the daemon has no latency', async () => {
		stubFetch({ '/api/bridge/health': { ...HEALTH, latency_us: null, latency_note: NOTE } });

		render(BridgeStatus);

		const latency = await screen.findByText('Not measured');
		expect(latency).toHaveAttribute('title', NOTE);
		expect(screen.queryByText(/null/)).not.toBeInTheDocument();
	});

	it('still shows a measured latency', async () => {
		stubFetch({ '/api/bridge/health': HEALTH });

		render(BridgeStatus);

		expect(await screen.findByText('120 us')).toBeInTheDocument();
	});
});
