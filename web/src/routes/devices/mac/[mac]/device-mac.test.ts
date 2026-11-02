import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import Page from './+page.svelte';

// #89: the daemon wraps both replies ({device}, {from, to, traffic}); the page read the wrappers,
// crashed on device.ips.length and stayed on its loader. Its in/out and destination bytes were
// missing from the traffic reply too, so they would have read 0.

const { MAC } = vi.hoisted(() => ({ MAC: 'D0:21:F9:5E:35:32' }));
vi.mock('$app/stores', () => ({
	page: readable({ url: new URL(`http://localhost/devices/mac/${MAC}`), params: { mac: MAC } }),
}));

const REPLIES: Record<string, unknown> = {
	[`/api/devices/registry/${encodeURIComponent(MAC)}`]: {
		device: {
			mac: MAC,
			ips: ['192.168.1.1'],
			hostnames: ['gateway'],
			manufacturer: 'Ubiquiti Inc',
			friendly_name: null,
			display_name: 'Ubiquiti gateway',
			category: 'infrastructure',
			first_seen: '2026-11-01T00:00:00Z',
			last_seen: '2026-11-02T00:00:00Z',
			is_new: false,
		},
	},
	[`/api/devices/registry/${encodeURIComponent(MAC)}/traffic`]: {
		from: '',
		to: '',
		traffic: {
			mac: MAC,
			total_bytes: 3 * 1024 * 1024,
			inbound_bytes: 2 * 1024 * 1024,
			outbound_bytes: 1024 * 1024,
			connection_count: 1234,
			protocols: ['udp'],
			top_protocols: [{ name: 'udp', count: 1234 }],
			top_destinations: [{ ip: '192.168.1.174', connections: 600, bytes: 512 * 1024 }],
		},
	},
};

describe('Device by MAC page', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('loads with the daemon replies and shows real in/out and destination bytes', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const body = REPLIES[url.split('?')[0]];
				return body
					? { ok: true, status: 200, json: async () => body }
					: { ok: false, status: 404, json: async () => ({}) };
			}),
		);

		render(Page);

		await vi.waitFor(() => expect(screen.getByText('2.0MB in / 1.0MB out')).toBeInTheDocument());
		expect(screen.getAllByText('1,234')).toHaveLength(2); // connections and the UDP count
		expect(screen.getByText('512KB')).toBeInTheDocument();
		expect(document.querySelector('.loading-state')).toBeNull();
	});
});
