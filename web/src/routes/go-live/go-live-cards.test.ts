/** Go Live's redesigned cards: the loading state, the step indicator and the health words. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/svelte';
import * as bridgeApi from '$lib/api/bridge.js';
import GoLivePage from './+page.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

vi.mock('$lib/api/bridge.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/bridge.js')>()),
	getBridgeReadiness: vi.fn(),
	getBridgeHealth: vi.fn(),
}));

function stubMode(reply: Promise<Response>) {
	vi.stubGlobal(
		'fetch',
		vi.fn((input: RequestInfo | URL) =>
			String(input) === '/api/capture/mode' ? reply : Promise.reject(new Error(`unexpected fetch ${String(input)}`)),
		),
	);
}

const bridgeMode = () => Promise.resolve(new Response(JSON.stringify({ mode: 'bridge', interface: '' }), { status: 200 }));
const check = (name: string, passed: boolean) => ({ name, passed, detail: '' });
const HEALTH = {
	bridge_state: 'up', wan_link: true, lan_link: false, bypass_active: false, watchdog_active: true,
	rx_bytes_delta: 0, tx_bytes_delta: 0, rx_packets_delta: 1500, tx_packets_delta: 5, uptime_seconds: 3700,
	latency_us: null, health_status: 'not_configured', issues: ['LAN link is down'], last_check: '',
};

afterEach(() => {
	vi.clearAllMocks();
	vi.unstubAllGlobals();
});

const progress = () => screen.getByRole('list', { name: 'Go Live progress' });

describe('Go Live cards', () => {
	it('shows the loading state while the capture mode is unknown', async () => {
		stubMode(new Promise(() => {}));
		render(GoLivePage);

		expect(await screen.findByRole('status')).toHaveTextContent('Loading the capture mode');
		expect(screen.getByRole('heading', { level: 1, name: 'Go Live' })).toHaveClass('page-title');
	});

	it('marks Readiness as the current step and says each check result', async () => {
		stubMode(bridgeMode());
		vi.mocked(bridgeApi.getBridgeReadiness).mockResolvedValue({
			ready: false,
			message: '',
			checks: [check('bridge_exists', false), check('wan_carrier', true)],
		});
		render(GoLivePage);

		expect(await screen.findByRole('img', { name: 'Passed' })).toBeInTheDocument();
		expect(screen.getByRole('img', { name: 'Failed' })).toBeInTheDocument();
		const current = within(progress()).getByText('Readiness').closest('li');
		expect(current).toHaveAttribute('aria-current', 'step');
		expect(within(progress()).queryByRole('img', { name: 'Done' })).not.toBeInTheDocument();
	});

	it('in monitoring, marks the earlier steps done and words the health', async () => {
		stubMode(bridgeMode());
		vi.mocked(bridgeApi.getBridgeReadiness).mockResolvedValue({
			ready: true,
			message: '',
			checks: ['bridge_exists', 'wan_carrier', 'lan_carrier'].map((n) => check(n, true)),
		});
		vi.mocked(bridgeApi.getBridgeHealth).mockResolvedValue(HEALTH as never);
		render(GoLivePage);

		expect(await screen.findByText('Not configured')).toHaveClass('chip', 'is-bad');
		expect(within(progress()).getAllByRole('img', { name: 'Done' })).toHaveLength(2);
		expect(within(progress()).getByText('Monitoring').closest('li')).toHaveAttribute('aria-current', 'step');
		expect(screen.getByText('Up')).toBeInTheDocument();
		expect(screen.getByText('Down')).toBeInTheDocument();
		expect(screen.getByText('1.5K')).toBeInTheDocument();
		expect(screen.getByText('LAN link is down')).toBeInTheDocument();
	});
});
