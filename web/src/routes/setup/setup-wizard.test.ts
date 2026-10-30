import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';

vi.mock('$app/forms', () => ({ enhance: () => ({ destroy: () => {} }) }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import SetupPage from './+page.svelte';

/**
 * The real setup wizard, rendered with the step order unchanged: once the
 * createAdmin action succeeds (the action sets the session cookie), the
 * wizard saves the config and only then runs the verification calls, and
 * every verification row ends in a final state.
 */

type Responses = Record<string, { status?: number; body: unknown }>;

const BASE_RESPONSES: Responses = {
	'GET /api/setup/nics': {
		body: { interfaces: [{ name: 'eth0', type: 'ethernet' }, { name: 'eth1', type: 'ethernet' }] },
	},
	'GET /api/health': { body: { status: 'ok' } },
	'GET /api/setup/storage': { body: { disk_free_gb: 500 } },
	'POST /api/setup/configure': { body: { status: 'ok' } },
	'GET /api/opensearch/cluster': { body: { status: 'green' } },
	'GET /api/settings/excluded-ips': { body: { excluded_ips: ['192.168.1.5'] } },
	'GET /api/bridge/health': { body: { health_status: 'normal', bridge_state: 'up' } },
};

let calls: string[];
let bodies: Record<string, unknown>;

function mockFetch(overrides: Responses = {}) {
	const responses = { ...BASE_RESPONSES, ...overrides };
	globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
		const key = `${init?.method ?? 'GET'} ${String(input)}`;
		calls.push(key);
		if (init?.body) bodies[key] = JSON.parse(String(init.body));
		const match = responses[key] ?? { status: 404, body: { error: 'not mocked' } };
		return new Response(JSON.stringify(match.body), { status: match.status ?? 200 });
	}) as typeof fetch;
}

async function chooseBridgeModeThenCreateAccount() {
	const view = render(SetupPage, { props: { form: null } });
	const start = await screen.findByRole('button', { name: /Get Started/ });
	await waitFor(() => expect(start).not.toBeDisabled());
	await fireEvent.click(start);
	await fireEvent.click(await screen.findByRole('button', { name: /Advanced/ }));
	await fireEvent.click(await screen.findByRole('button', { name: /Inline Bridge/ }));

	// The createAdmin action returned success (and set the session cookie).
	await view.rerender({ form: { success: true, username: 'admin' } });
	await tick();
	return view;
}

/** Mirror mode: Welcome → Capture Mode → Interfaces → Storage → Enrichment (UniFi on) → Account */
async function walkMirrorModeWithUnifiThenCreateAccount() {
	const view = render(SetupPage, { props: { form: null } });
	const start = await screen.findByRole('button', { name: /Get Started/ });
	await waitFor(() => expect(start).not.toBeDisabled());
	await fireEvent.click(start);
	await fireEvent.click(await screen.findByRole('button', { name: /Mirror \/ SPAN/ }));
	await fireEvent.click(screen.getByRole('button', { name: /Next/ }));
	const nicSelect = await screen.findByLabelText(/Capture Interface/);
	await fireEvent.change(nicSelect, { target: { value: 'eth0' } });
	await fireEvent.click(screen.getByRole('button', { name: /Next/ }));
	await fireEvent.click(await screen.findByRole('button', { name: /Skip/ }));
	await fireEvent.click(await screen.findByRole('checkbox'));

	await view.rerender({ form: { success: true, username: 'admin' } });
	await tick();
	return view;
}

const originalFetch = globalThis.fetch;

beforeEach(() => {
	calls = [];
	bodies = {};
});

afterEach(() => {
	globalThis.fetch = originalFetch;
});

describe('setup wizard after account creation', () => {
	it('saves the config before running the verification checks', async () => {
		mockFetch();
		await chooseBridgeModeThenCreateAccount();

		await waitFor(() => expect(calls).toContain('GET /api/bridge/health'));
		const configure = calls.indexOf('POST /api/setup/configure');
		expect(configure).toBeGreaterThan(-1);
		for (const check of ['GET /api/opensearch/cluster', 'GET /api/bridge/health']) {
			expect(calls.indexOf(check)).toBeGreaterThan(configure);
		}
	});

	it('shows a failed config save on the Verification step and hides Go Live', async () => {
		mockFetch({
			'POST /api/setup/configure': { status: 400, body: { error: 'dhcp_subnet overlaps 192.168.1.0/24 on eth1' } },
		});
		await chooseBridgeModeThenCreateAccount();

		await screen.findByText('System Verification');
		const alert = await screen.findByRole('alert');
		expect(alert).toHaveTextContent('Your capture settings were not saved.');
		expect(alert).toHaveTextContent('dhcp_subnet overlaps 192.168.1.0/24 on eth1');
		await waitFor(() => expect(screen.getByRole('link', { name: 'Go to Dashboard' })).toBeInTheDocument());
		expect(screen.queryByRole('link', { name: 'Go Live Setup' })).not.toBeInTheDocument();

		// Retrying the save clears the error once the daemon accepts it
		mockFetch();
		await fireEvent.click(screen.getByRole('button', { name: 'Try saving again' }));
		await waitFor(() => expect(screen.queryByText('Your capture settings were not saved.')).not.toBeInTheDocument());
		expect(calls).toContain('POST /api/setup/configure');
		expect(screen.getByRole('link', { name: 'Go Live Setup' })).toBeInTheDocument();
	});

	it("passes the bridge row on health_status 'normal'", async () => {
		mockFetch();
		await chooseBridgeModeThenCreateAccount();

		expect(await screen.findByText('Bridge active')).toBeInTheDocument();
		expect(screen.queryByText('Bridge not fully healthy')).not.toBeInTheDocument();
	});

	it('never leaves a row on "Checking..." when a check gets an error status', async () => {
		mockFetch({
			'GET /api/settings/excluded-ips': { status: 500, body: { error: 'boom' } },
			'GET /api/bridge/health': { status: 502, body: { error: 'daemon down' } },
		});
		await chooseBridgeModeThenCreateAccount();

		expect(await screen.findByText('Could not check (HTTP 500)')).toBeInTheDocument();
		expect(await screen.findByText('Could not check (HTTP 502)')).toBeInTheDocument();
		await waitFor(() => expect(screen.queryByText('Checking...')).not.toBeInTheDocument());
	});

	it('does not report UniFi as connected until the daemon says so', async () => {
		mockFetch({
			'GET /api/integrations/unifi/status': {
				body: { configured: true, connected: false, cache_counts: { clients: 0 } },
			},
		});
		await walkMirrorModeWithUnifiThenCreateAccount();

		expect(await screen.findByText('Configured, not connected yet')).toBeInTheDocument();
		expect(screen.queryByText(/^Connected \(/)).not.toBeInTheDocument();
	});

	it('reports UniFi connected with its client count', async () => {
		mockFetch({
			'GET /api/integrations/unifi/status': {
				body: { configured: true, connected: true, cache_counts: { clients: 7 } },
			},
		});
		await walkMirrorModeWithUnifiThenCreateAccount();

		expect(await screen.findByText('Connected (7 clients)')).toBeInTheDocument();
	});
});

describe('setup wizard UniFi test connection', () => {
	it('reports a failure when the daemon answers 200 with success: false', async () => {
		mockFetch({
			'POST /api/integrations/unifi/configure': { body: { status: 'configured' } },
			'POST /api/integrations/unifi/test': {
				body: { success: false, status: { last_error: 'Invalid API key' } },
			},
		});
		render(SetupPage, { props: { form: null } });
		const start = await screen.findByRole('button', { name: /Get Started/ });
		await waitFor(() => expect(start).not.toBeDisabled());
		await fireEvent.click(start);
		await fireEvent.click(await screen.findByRole('button', { name: /Mirror \/ SPAN/ }));
		await fireEvent.click(screen.getByRole('button', { name: /Next/ }));
		const nicSelect = await screen.findByLabelText(/Capture Interface/);
		await fireEvent.change(nicSelect, { target: { value: 'eth0' } });
		await fireEvent.click(screen.getByRole('button', { name: /Next/ }));
		await fireEvent.click(await screen.findByRole('button', { name: /Skip/ }));
		await fireEvent.click(await screen.findByRole('checkbox'));
		await fireEvent.input(screen.getByLabelText('Controller URL'), { target: { value: 'https://10.0.0.1' } });
		await fireEvent.input(screen.getByLabelText('API Key'), { target: { value: 'wrong-key' } });

		await fireEvent.click(screen.getByRole('button', { name: /Test Connection/ }));

		expect(await screen.findByText('Connection failed: Invalid API key')).toBeInTheDocument();
		expect(screen.queryByText('Successfully connected to UniFi controller.')).not.toBeInTheDocument();
	});
});

/** eth1 is the port plugged into the router (it has a router address); eth0 has none. */
const DHCP_NICS: Responses = {
	'GET /api/setup/nics': {
		body: {
			interfaces: [
				{ name: 'eth0', type: 'ethernet', state: 'up' },
				{ name: 'eth1', type: 'ethernet', state: 'up', ipv4: '192.168.1.50' },
			],
		},
	},
};

async function startWizard() {
	const view = render(SetupPage, { props: { form: null } });
	const start = await screen.findByRole('button', { name: /Get Started/ });
	await waitFor(() => expect(start).not.toBeDisabled());
	await fireEvent.click(start);
	await screen.findByText('Choose Capture Mode');
	return view;
}

const dhcpCard = () => screen.getByRole('button', { name: /hands out addresses/ });
const nextButton = () => screen.getByRole('button', { name: /Next/ });

/** DHCP mode: Welcome → Capture Mode → Interfaces (router port) → DHCP Gateway */
async function walkToDhcpStep(routerPort = 'eth1') {
	const view = await startWizard();
	await fireEvent.click(dhcpCard());
	await fireEvent.click(nextButton());
	await fireEvent.change(await screen.findByLabelText(/Router Port/), { target: { value: routerPort } });
	await fireEvent.click(nextButton());
	await screen.findByLabelText(/Subnet for your devices/);
	return view;
}

describe('setup wizard capture mode choice', () => {
	it('shows DHCP Gateway first and marks it Recommended instead of Mirror', async () => {
		mockFetch();
		const view = await startWizard();

		const cards = view.container.querySelectorAll('.mode-cards .mode-card');
		expect(cards[0].textContent).toContain('DHCP Gateway');
		expect(cards[0].textContent).toContain('Recommended');
		expect(cards[1].textContent).toContain('Mirror / SPAN');
		expect(cards[1].textContent).not.toContain('Recommended');
	});

	it('keeps the inline bridge inside a collapsed Advanced section until it is opened', async () => {
		mockFetch();
		await startWizard();

		const advanced = screen.getByRole('button', { name: /Advanced/ });
		const bridgeBody = screen.getByRole('button', { name: /Inline Bridge/ }).closest('.collapsible-body');
		expect(advanced).toHaveAttribute('aria-expanded', 'false');
		expect(bridgeBody).not.toHaveClass('collapsible-body-expanded');

		await fireEvent.click(advanced);

		expect(advanced).toHaveAttribute('aria-expanded', 'true');
		expect(bridgeBody).toHaveClass('collapsible-body-expanded');
	});

	it('opens Advanced on its own when the bridge is already selected', async () => {
		mockFetch();
		await startWizard();
		await fireEvent.click(screen.getByRole('button', { name: /Advanced/ }));
		await fireEvent.click(screen.getByRole('button', { name: /Inline Bridge/ }));
		await fireEvent.click(nextButton());
		await fireEvent.click(await screen.findByRole('button', { name: /Back/ }));

		await waitFor(() =>
			expect(screen.getByRole('button', { name: /Advanced/ })).toHaveAttribute('aria-expanded', 'true')
		);
	});

	it('shows the eight DHCP gateway steps once DHCP Gateway is chosen', async () => {
		mockFetch();
		const view = await startWizard();

		await fireEvent.click(dhcpCard());

		const labels = [...view.container.querySelectorAll('.step-label')].map((el) => el.textContent);
		expect(labels).toEqual([
			'Welcome', 'Capture Mode', 'Interfaces', 'DHCP Gateway', 'Storage', 'Enrichment', 'Account', 'Verification',
		]);
	});
});

describe('setup wizard DHCP gateway flow', () => {
	it('shows the router port address and warns when the port has none', async () => {
		mockFetch(DHCP_NICS);
		await startWizard();
		await fireEvent.click(dhcpCard());
		await fireEvent.click(nextButton());
		const select = await screen.findByLabelText(/Router Port/);

		await fireEvent.change(select, { target: { value: 'eth1' } });
		expect(screen.getByText('192.168.1.50')).toBeInTheDocument();
		expect(screen.queryByText(/This port has no IPv4 address/)).not.toBeInTheDocument();

		await fireEvent.change(select, { target: { value: 'eth0' } });
		expect(screen.getByText(/This port has no IPv4 address/)).toBeInTheDocument();
	});

	it('blocks Next while the subnet is invalid', async () => {
		mockFetch(DHCP_NICS);
		await walkToDhcpStep();
		const subnet = screen.getByLabelText(/Subnet for your devices/);
		await waitFor(() => expect(nextButton()).not.toBeDisabled());

		await fireEvent.input(subnet, { target: { value: '10.77.0.5/24' } });
		await waitFor(() => expect(nextButton()).toBeDisabled());

		// Contains eth1's own router address
		await fireEvent.input(subnet, { target: { value: '192.168.1.0/24' } });
		await waitFor(() => expect(nextButton()).toBeDisabled());

		await fireEvent.input(subnet, { target: { value: '10.88.0.0/24' } });
		await waitFor(() => expect(nextButton()).not.toBeDisabled());
	});

	it('sends the DHCP gateway mode, router port and subnet to /api/setup/configure', async () => {
		mockFetch(DHCP_NICS);
		const view = await walkToDhcpStep();
		await fireEvent.input(screen.getByLabelText(/Subnet for your devices/), { target: { value: '10.88.0.0/24' } });
		await waitFor(() => expect(nextButton()).not.toBeDisabled());
		await fireEvent.click(nextButton());
		await fireEvent.click(await screen.findByRole('button', { name: /Skip/ })); // Storage
		await screen.findByText('Device Enrichment');
		await fireEvent.click(screen.getByRole('button', { name: /Skip/ })); // Enrichment

		await view.rerender({ form: { success: true, username: 'admin' } });
		await tick();

		await waitFor(() => expect(bodies['POST /api/setup/configure']).toBeDefined());
		const payload = bodies['POST /api/setup/configure'] as Record<string, unknown>;
		expect(payload).toMatchObject({
			capture_mode: 'dhcp_gateway',
			capture_interface: 'eth1',
			dhcp_subnet: '10.88.0.0/24',
		});
		expect(payload).not.toHaveProperty('wan_interface');
		expect(payload).not.toHaveProperty('lan_interface');
	});
});
