import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('$app/forms', () => ({ enhance: () => ({ destroy: () => {} }) }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import SetupPage from './+page.svelte';

// When the daemon didn't answer, /api/setup/nics answered built-in sample cards (eth0, eth1, wlan0)
// with source 'mock': the requirement check passed and the wizard offered the samples for selection.

const SAMPLE = {
	source: 'mock',
	interfaces: [
		{ name: 'eth0', mac: 'a8:a1:59:c2:0e:01', state: 'up', speed: '2500Mb/s', driver: 'igc', type: 'ethernet' },
		{ name: 'eth1', mac: 'a8:a1:59:c2:0e:02', state: 'up', speed: '2500Mb/s', driver: 'igc', type: 'ethernet' },
	],
};
const REAL = {
	source: 'daemon',
	interfaces: [{ name: 'enp1s0', mac: '00:11:22:33:44:55', state: 'up', speed: '1000Mb/s', driver: 'r8169', type: 'ethernet' }],
};

function stubNics(nics: unknown, storage: Response = new Response(JSON.stringify({ disk_free_gb: 500, source: 'daemon' }))) {
	globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
		const url = String(input);
		if (url === '/api/setup/nics') return new Response(JSON.stringify(nics));
		if (url === '/api/setup/storage') return storage;
		return new Response(JSON.stringify({ status: 'ok' }));
	}) as typeof fetch;
}

async function openMirrorInterfacesStep() {
	render(SetupPage, { props: { form: null } });
	const start = await screen.findByRole('button', { name: /Get started/ });
	await waitFor(() => expect(start).not.toBeDisabled());
	await fireEvent.click(start);
	await fireEvent.click(await screen.findByRole('button', { name: /Mirror \/ SPAN/ }));
	await fireEvent.click(screen.getByRole('button', { name: /Next/ }));
}

const originalFetch = globalThis.fetch;

describe('setup wizard network cards', () => {
	afterEach(() => {
		globalThis.fetch = originalFetch;
	});

	it("says the network card check couldn't run instead of passing on sample cards", async () => {
		stubNics(SAMPLE);
		render(SetupPage, { props: { form: null } });

		expect(await screen.findByText("Network interfaces: couldn't check")).toBeInTheDocument();
		expect(screen.queryByText('One or more network interfaces')).not.toBeInTheDocument();
	});

	it('does not offer sample cards for selection', async () => {
		stubNics(SAMPLE);
		await openMirrorInterfacesStep();

		expect(await screen.findByText("Couldn't detect the network cards: NetTap's service didn't answer.")).toBeInTheDocument();
		expect(screen.queryByRole('option', { name: /eth0/ })).not.toBeInTheDocument();
		expect(screen.queryByText(/showing sample interface data/)).not.toBeInTheDocument();
	});

	it('lists the real cards when the daemon answers', async () => {
		stubNics(REAL);
		await openMirrorInterfacesStep();

		// capture and management selects both list it
		expect(await screen.findAllByRole('option', { name: /enp1s0/ })).toHaveLength(2);
		expect(screen.queryByText(/Couldn't detect the network cards/)).not.toBeInTheDocument();
	});
});

// The disk check passed when /api/setup/storage failed, and on the proxy's sample reply (911 GB free).
describe('setup wizard disk check', () => {
	afterEach(() => {
		globalThis.fetch = originalFetch;
	});

	it.each([
		['the request fails', new Response('{}', { status: 502 })],
		['the daemon did not answer (sample data)', new Response(JSON.stringify({ disk_free_gb: 911.57, source: 'mock' }))],
	])("says it couldn't check when %s", async (_why, storage) => {
		stubNics(REAL, storage);
		render(SetupPage, { props: { form: null } });

		expect(await screen.findByText("Disk space: couldn't check")).toBeInTheDocument();
	});

	it('still checks the real free space', async () => {
		stubNics(REAL);
		render(SetupPage, { props: { form: null } });

		expect(await screen.findByText('Sufficient disk space (100GB+)')).toBeInTheDocument();
		expect(screen.queryByText("Disk space: couldn't check")).not.toBeInTheDocument();
	});
});
