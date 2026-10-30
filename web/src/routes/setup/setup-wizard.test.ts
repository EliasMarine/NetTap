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

function mockFetch(overrides: Responses = {}) {
	const responses = { ...BASE_RESPONSES, ...overrides };
	globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
		const key = `${init?.method ?? 'GET'} ${String(input)}`;
		calls.push(key);
		const match = responses[key] ?? { status: 404, body: { error: 'not mocked' } };
		return new Response(JSON.stringify(match.body), { status: match.status ?? 200 });
	}) as typeof fetch;
}

async function chooseBridgeModeThenCreateAccount() {
	const view = render(SetupPage, { props: { form: null } });
	const start = await screen.findByRole('button', { name: /Get Started/ });
	await waitFor(() => expect(start).not.toBeDisabled());
	await fireEvent.click(start);
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
