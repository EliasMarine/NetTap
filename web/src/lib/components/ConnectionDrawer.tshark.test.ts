import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import ConnectionDrawer from './ConnectionDrawer.svelte';

const CONNECTION = { 'id.orig_h': '10.0.0.5', 'id.resp_h': '1.1.1.1', 'id.orig_p': 50000, 'id.resp_p': 443, proto: 'tcp' };

/** Answer each URL prefix with its body, or HTTP 500 when it has none. */
function stubFetch(replies: Record<string, unknown>) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			const key = Object.keys(replies).find((prefix) => url.startsWith(prefix));
			if (!key) return new Response('{}', { status: 500 });
			return new Response(JSON.stringify(replies[key]), { status: 200 });
		}),
	);
}

async function openTSharkTab() {
	render(ConnectionDrawer, { props: { connection: CONNECTION, deviceIp: '10.0.0.5', onclose: () => {} } });
	await fireEvent.click(screen.getByRole('button', { name: 'TShark analysis' }));
}

describe('ConnectionDrawer TShark tab when a request fails (#96)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says TShark could not be checked instead of "not available"', async () => {
		stubFetch({});
		await openTSharkTab();

		expect(await screen.findByText("Couldn't check whether TShark is available: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('TShark is not available.')).not.toBeInTheDocument();
	});

	it('says the PCAP list failed instead of "No PCAP files available"', async () => {
		stubFetch({ '/api/tshark/status': { available: true, version: '4.2', container_running: true, container_name: 'tshark' } });
		await openTSharkTab();

		expect(await screen.findByText('Failed to load PCAP files')).toBeInTheDocument();
		expect(screen.queryByText('No PCAP files available on the appliance.')).not.toBeInTheDocument();
	});

	it('still says TShark is not available when the daemon says so', async () => {
		stubFetch({ '/api/tshark/status': { available: false, version: '', container_running: false, container_name: '' } });
		await openTSharkTab();

		expect(await screen.findByText('TShark is not available.')).toBeInTheDocument();
	});
});
