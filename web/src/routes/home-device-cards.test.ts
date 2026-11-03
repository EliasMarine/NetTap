import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import HomePage from './+page.svelte';

// On the G11 every Device Overview card read Traffic "--" and Connections "--": the registry
// carries no traffic, and Home never joined the device list's figures to it.

const FROM = '2026-11-01T22:00:00Z';

function stubDaemon(): void {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	const replies: Record<string, unknown> = {
		'/api/capture/mode': { mode: 'mirror', interface: 'enp4s0' },
		'/api/devices/registry': {
			count: 2,
			devices: [
				{ mac: 'D0:21:F9:5E:35:32', ips: ['192.168.1.1', '10.10.0.1'], hostnames: [], manufacturer: 'Ubiquiti Inc',
				  friendly_name: null, display_name: 'Gateway', category: 'infrastructure', first_seen: FROM,
				  last_seen: '2026-11-02T21:00:00+00:00', is_new: false },
				{ mac: 'AA:00:00:00:00:01', ips: ['192.168.1.9'], hostnames: [], manufacturer: null,
				  friendly_name: null, display_name: 'Old printer', category: 'infrastructure', first_seen: '2026-10-01T00:00:00Z',
				  last_seen: '2026-11-01T10:00:00+00:00', is_new: false },
			],
		},
		'/api/devices': {
			from: FROM, to: '2026-11-02T22:00:00Z', limit: 500,
			devices: [
				{ ip: '192.168.1.1', total_bytes: 1024, connection_count: 1200, last_seen: '2026-11-02T21:50:00Z' },
				{ ip: '10.10.0.1', total_bytes: 1024, connection_count: 34, last_seen: '2026-11-02T21:40:00Z' },
			].map((d) => ({ mac: null, hostname: null, manufacturer: null, os_hint: null, first_seen: FROM, protocols: [], alert_count: 0, ...d })),
		},
	};
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const body = replies[url.split('?')[0]];
			return body
				? { ok: true, status: 200, json: async () => body }
				: { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

function stat(device: string, label: string): string | undefined {
	const card = screen.getByText(device).closest('.device-card');
	const labelEl = Array.from(card?.querySelectorAll('.stat-label') ?? []).find((el) => el.textContent?.trim() === label);
	return labelEl?.nextElementSibling?.textContent?.trim();
}

describe('Home — device cards carry the range traffic', () => {
	afterEach(() => vi.unstubAllGlobals());

	it("sums a device's IPs from the device list, and a device quiet all range reads 0 B", async () => {
		stubDaemon();
		render(HomePage);
		await screen.findByText('Gateway');
		await vi.waitFor(() => expect(stat('Gateway', 'Traffic')).toBe('2.0 KB'));
		expect(stat('Gateway', 'Connections')).toBe((1234).toLocaleString());
		expect(stat('Old printer', 'Traffic')).toBe('0 B');
		expect(stat('Old printer', 'Connections')).toBe('0');
	});
});
