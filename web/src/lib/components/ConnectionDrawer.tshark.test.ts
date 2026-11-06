import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import ConnectionDrawer from './ConnectionDrawer.svelte';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

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

// NET-160: the TLS name (SNI) opens its domain page
describe('ConnectionDrawer TLS details', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('links the SNI to its domain page, with nothing nested', () => {
		stubFetch({});
		const { container } = render(ConnectionDrawer, {
			props: { connection: { ...CONNECTION, zeek: { ssl: { server_name: 'WWW.Example.com' } } }, deviceIp: '10.0.0.5', onclose: () => {} },
		});
		expect(screen.getByRole('link', { name: 'WWW.Example.com' })).toHaveAttribute('href', '/domain/www.example.com');
		expectNoNestedInteractive(container);
	});
});

// NET-160: a related source that isn't on your network opens its address page, not a device page
describe('ConnectionDrawer related activity', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('links an internet source to its address page', async () => {
		stubFetch({});
		render(ConnectionDrawer, { props: { connection: { ...CONNECTION, source: { ip: '203.0.113.7' } }, deviceIp: '10.0.0.5', onclose: () => {} } });
		await fireEvent.click(screen.getByRole('button', { name: 'Related activity' }));
		expect(screen.getByRole('link', { name: /Address: 203.0.113.7/ })).toHaveAttribute('href', '/address/203.0.113.7');
	});
});
