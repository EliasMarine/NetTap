import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ConnectionDrawerContent from './ConnectionDrawerContent.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const CONNECTION = {
	_id: 'c1',
	_source: { 'id.orig_h': '10.0.0.5', 'id.resp_h': '1.1.1.1', 'id.orig_p': 50000, 'id.resp_p': 443, proto: 'tcp' },
};

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

describe('ConnectionDrawerContent TShark tab when a request fails (#96)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says TShark could not be checked instead of "not available"', async () => {
		stubFetch({});

		render(ConnectionDrawerContent, { props: { connection: CONNECTION, activeTab: 'tshark' } });

		expect(await screen.findByText("Couldn't check whether TShark is available: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('TShark is not available')).not.toBeInTheDocument();
	});

	it('says the PCAP list failed instead of "No PCAP files available"', async () => {
		stubFetch({ '/api/tshark/status': { available: true, version: '4.2', container_running: true, container_name: 'tshark' } });

		render(ConnectionDrawerContent, { props: { connection: CONNECTION, activeTab: 'tshark' } });

		expect(await screen.findByText('Failed to load PCAP files')).toBeInTheDocument();
		expect(screen.queryByText('No PCAP files available')).not.toBeInTheDocument();
	});

	it('still says there are no PCAP files when the list really is empty', async () => {
		stubFetch({
			'/api/tshark/status': { available: true, version: '4.2', container_running: true, container_name: 'tshark' },
			'/api/tshark/pcaps': { pcaps: [], count: 0 },
		});

		render(ConnectionDrawerContent, { props: { connection: CONNECTION, activeTab: 'tshark' } });

		expect(await screen.findByText('No PCAP files available')).toBeInTheDocument();
	});
});
