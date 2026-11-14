import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import ChangelogDetail from './ChangelogDetail.svelte';
import { joinChangelog, MISSING_TEXT, PER_ADDRESS_NOTE } from './changelog-rows';
import type { ChangelogEvent } from '$lib/api/changelog';
import type { Device, DeviceListResponse } from '$lib/api/devices';

const WIN = { from: '2026-11-13T11:00:00.000Z', to: '2026-11-13T12:00:00.000Z' };
const event = (over: Partial<ChangelogEvent> = {}): ChangelogEvent => ({
	_id: 'e1', '@timestamp': '2026-11-13T11:10:00.000Z', event_type: 'device_joined', title: 'New device aa:bb:cc:dd:ee:01',
	description: 'First seen at 192.168.1.10 (source: dhcp)', metadata: { mac: 'aa:bb:cc:dd:ee:01', ip: '192.168.1.10' }, ...over,
});
const device = (over: Partial<Device> = {}): Device => ({
	ip: '192.168.1.10', mac: 'aa:bb:cc:dd:ee:01', hostname: 'Kitchen iPad', manufacturer: 'Apple', os_hint: null,
	first_seen: WIN.from, last_seen: WIN.to, total_bytes: 4e6, upload_bytes: 1e6, download_bytes: 3e6, connection_count: 12,
	protocols: [], alert_count: 2, ...over,
});
const list = (devices: Device[]): DeviceListResponse => ({ ...WIN, limit: 500, devices, total: devices.length, as_of: WIN.to, online_since: WIN.to, online_total: 0 });
const rowOf = (e: ChangelogEvent, l: DeviceListResponse | null) => joinChangelog([e], l).rows[0];

function stubDetail(reply: () => Promise<{ ok: boolean; body: unknown }>) {
	const fetch = vi.fn(async () => {
		const r = await reply();
		return { ok: r.ok, status: r.ok ? 200 : 502, json: async () => r.body };
	});
	vi.stubGlobal('fetch', fetch);
	return fetch;
}

describe('ChangelogDetail (NET-272)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it("shows a system event's description and metadata, and asks for nothing", () => {
		const fetch = stubDetail(async () => ({ ok: true, body: {} }));
		render(ChangelogDetail, {
			row: rowOf(event({ event_type: 'storage_pruned', title: 'Manual cleanup', description: 'Deleted old data', metadata: { trigger: 'manual' } }), null),
			win: WIN, range: '1h', onclose: () => {},
		});
		expect(screen.getByRole('heading', { name: 'Manual cleanup', level: 2 })).toBeInTheDocument();
		expect(screen.getByText('Deleted old data')).toBeInTheDocument();
		expect(screen.getByText('manual')).toBeInTheDocument();
		expect(fetch).not.toHaveBeenCalled();
	});

	it('an unmatched device says why, with no window links and no destination request', () => {
		const fetch = stubDetail(async () => ({ ok: true, body: {} }));
		render(ChangelogDetail, { row: rowOf(event(), list([])), win: WIN, range: '1h', onclose: () => {} });
		expect(screen.getByText(MISSING_TEXT['no-figures'])).toBeInTheDocument();
		expect(screen.getByText('No destinations: no traffic figures for this device in this range.')).toBeInTheDocument();
		expect(screen.queryByRole('link', { name: 'This device in this range' })).not.toBeInTheDocument();
		expect(screen.getByRole('link', { name: /Device overview/ })).toHaveAttribute('href', '/devices/mac/aa%3Abb%3Acc%3Add%3Aee%3A01');
		expect(screen.queryByText(PER_ADDRESS_NOTE)).not.toBeInTheDocument();
		expect(fetch).not.toHaveBeenCalled();
	});

	it('a matched device shows its figures, the per-address note and its IPv6 notes', async () => {
		stubDetail(async () => ({ ok: true, body: { device: { top_destinations: [] } } }));
		render(ChangelogDetail, {
			row: rowOf(event(), list([device({ ipv6_left_out: 4, ipv6_left_out_reason: 'router' })])),
			win: WIN, range: '1h', onclose: () => {},
		});
		expect(screen.getByText(PER_ADDRESS_NOTE)).toBeInTheDocument();
		expect(screen.getByText(/The device at 192\.168\.1\.10 forwards other devices' traffic/)).toBeInTheDocument();
		expect(screen.getByText('4.0 MB')).toBeInTheDocument();
		expect(screen.getByText('Apple')).toBeInTheDocument();
		expect(await screen.findByText('No destinations for connections it started in this range.')).toBeInTheDocument();
	});

	it('a failed destination request says so, and Try again asks once more', async () => {
		let fail = true;
		const fetch = stubDetail(async () => (fail ? { ok: false, body: {} } : { ok: true, body: { device: { top_destinations: [{ ip: '1.1.1.1', bytes: 900, connections: 2 }] } } }));
		render(ChangelogDetail, { row: rowOf(event(), list([device()])), win: WIN, range: '1h', onclose: () => {} });
		expect(await screen.findByText("Couldn't load destinations: the request failed.")).toBeInTheDocument();
		fail = false;
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(await screen.findByRole('link', { name: '1.1.1.1' })).toHaveAttribute('href', '/address/1.1.1.1');
		expect(fetch).toHaveBeenCalledTimes(2);
	});

	it('Esc inside the panel and Close both close it', async () => {
		stubDetail(async () => ({ ok: true, body: { device: { top_destinations: [] } } }));
		const onclose = vi.fn();
		render(ChangelogDetail, { row: rowOf(event(), list([device()])), win: WIN, range: '1h', onclose });
		await fireEvent.keyDown(screen.getByRole('heading', { name: 'Kitchen iPad', level: 2 }), { key: 'Escape' });
		await fireEvent.click(screen.getByRole('button', { name: 'Close' }));
		expect(onclose).toHaveBeenCalledTimes(2);
	});
});
