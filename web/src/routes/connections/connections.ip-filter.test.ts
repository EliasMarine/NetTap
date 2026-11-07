/**
 * NET-160: the IP filter is the daemon's structured `ip` parameter (either side), not free text in
 * `q`, and ?ip= is read whenever the URL changes, so a link to another address reloads for it.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { getConnections, getConnectionStats, getConnectionSankey, getConnectionTimeline } from '$api/traffic';
import type { ConnectionsResponse } from '$api/traffic';
import { getLiveDashboard } from '$api/live';
import { getRegistryDevices } from '$api/devices-registry';
import Page from './+page.svelte';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

const { page } = vi.hoisted(() => {
	let value = { url: new URL('http://localhost/connections?ip=203.0.113.9') };
	const subs = new Set<(v: typeof value) => void>();
	return {
		page: {
			subscribe(fn: (v: typeof value) => void) {
				subs.add(fn);
				fn(value);
				return () => subs.delete(fn);
			},
			goto(url: string) {
				value = { url: new URL(url, 'http://localhost') };
				subs.forEach((fn) => fn(value));
			},
		},
	};
});

vi.mock('$app/stores', () => ({ page }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$api/traffic', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/traffic')>()),
	getConnections: vi.fn(),
	getConnectionStats: vi.fn(),
	getConnectionSankey: vi.fn(),
	getConnectionTimeline: vi.fn(),
}));
vi.mock('$api/live', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/live')>()),
	getLiveDashboard: vi.fn(),
}));
vi.mock('$api/devices-registry', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/devices-registry')>()),
	getRegistryDevices: vi.fn(),
}));

vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });

function deferred<T>() {
	let resolve!: (v: T) => void;
	const promise = new Promise<T>((res) => (resolve = res));
	return { promise, resolve };
}

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

const table = (src: string): ConnectionsResponse => ({
	from: '', to: '', page: 1, size: 50, total: 1, total_pages: 1,
	connections: [{ _id: src, _index: 'zeek-conn', '@timestamp': '2026-11-03T10:00:00Z', source: { ip: src }, destination: { ip: '8.8.8.8' } }],
});

const rowLabels = () => screen.queryAllByRole('button', { name: /^Open connection from/ }).map((b) => b.getAttribute('aria-label'));

describe('Connections — address filter', () => {
	beforeEach(() => {
		page.goto('http://localhost/connections?ip=203.0.113.9');
		vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })));
		vi.mocked(getConnectionStats).mockResolvedValue({
			from: '', to: '', total_sessions: 1, bytes_in: 1, bytes_out: 1, alert_sessions: 0, protocols: [], top_sources: [], top_destinations: [],
		});
		vi.mocked(getConnectionSankey).mockResolvedValue({ from: '', to: '', nodes: { sources: [], protocols: [], destinations: [] }, links: [] });
		vi.mocked(getConnectionTimeline).mockResolvedValue({ from: '', to: '', interval: '5m', buckets: [] } as never);
		vi.mocked(getLiveDashboard).mockResolvedValue({ stats: { active_devices: 1 } } as never);
		vi.mocked(getRegistryDevices).mockResolvedValue({ devices: [], total: 0 });
	});

	afterEach(() => {
		vi.mocked(getConnections).mockReset();
		vi.unstubAllGlobals();
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	});

	it('sends ?ip= as the structured ip filter, not inside the free-text query', async () => {
		vi.mocked(getConnections).mockResolvedValue(table('203.0.113.9'));
		const { container } = render(Page);
		await flush();
		const opts = vi.mocked(getConnections).mock.calls[0][0]!;
		expect(opts.ip).toBe('203.0.113.9');
		expect(opts.q).toBeUndefined();
		expectNoNestedInteractive(container);
	});

	it('still searches part of an address as text, since only a whole address is a structured filter', async () => {
		page.goto('http://localhost/connections?ip=192.168.1');
		vi.mocked(getConnections).mockResolvedValue(table('192.168.1.20'));
		render(Page);
		await flush();
		const opts = vi.mocked(getConnections).mock.calls[0][0]!;
		expect(opts.ip).toBeUndefined();
		expect(opts.q).toBe('192.168.1');
	});

	it('searches free text with a colon ("tcp:443") as text, not as an address', async () => {
		page.goto('http://localhost/connections?ip=tcp:443');
		vi.mocked(getConnections).mockResolvedValue(table('192.168.1.20'));
		render(Page);
		await flush();
		const opts = vi.mocked(getConnections).mock.calls[0][0]!;
		expect(opts.ip).toBeUndefined();
		expect(opts.q).toBe('tcp:443');
	});

	it("shows the daemon's reason when the table fails", async () => {
		vi.mocked(getConnections).mockRejectedValue(new Error('That is not an IP address.'));
		render(Page);
		expect(await screen.findByText('That is not an IP address.')).toBeInTheDocument();
	});

	it('applies a link to the same address again after the box was edited', async () => {
		vi.mocked(getConnections).mockResolvedValue(table('203.0.113.9'));
		render(Page);
		await flush();
		const box = screen.getByLabelText('Filter by IP address');
		await fireEvent.input(box, { target: { value: '10.0.0.1' } });
		vi.mocked(getConnections).mockClear();
		page.goto('http://localhost/connections?ip=203.0.113.9'); // the same link, clicked again
		await flush();
		expect(box).toHaveValue('203.0.113.9');
		expect(vi.mocked(getConnections).mock.calls.at(-1)![0]!.ip).toBe('203.0.113.9');
	});

	it('reloads page 1 for the new address on same-page navigation, dropping a late reply for the old one', async () => {
		const forA = deferred<ConnectionsResponse>();
		vi.mocked(getConnections).mockImplementation(async (opts = {}) => (opts.ip === '203.0.113.9' ? forA.promise : table('2001:db8::1')));
		render(Page);
		await flush();

		page.goto('http://localhost/connections?ip=2001:db8::1');
		await flush();
		const last = vi.mocked(getConnections).mock.calls.at(-1)![0]!;
		expect(last.ip).toBe('2001:db8::1');
		expect(last.page).toBe(1);
		expect(last.q).toBeUndefined();
		expect(rowLabels()).toEqual(['Open connection from 2001:db8::1 to 8.8.8.8']);

		forA.resolve(table('203.0.113.9')); // A answers late
		await flush();
		expect(rowLabels()).toEqual(['Open connection from 2001:db8::1 to 8.8.8.8']);
		expect(screen.getByLabelText('Filter by IP address')).toHaveValue('2001:db8::1');
	});

	it('links top addresses and the drawer to where each address drills down', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ version: 'v', subnets: ['192.168.1.0/24'], source: 'env', ipv6: 'not-lan' }) })));
		vi.mocked(getConnectionStats).mockResolvedValue({
			from: '', to: '', total_sessions: 1, bytes_in: 1, bytes_out: 1, alert_sessions: 0, protocols: [],
			top_sources: [{ ip: '192.168.1.20', total_bytes: 10, connections: 1 }],
			top_destinations: [{ ip: '203.0.113.9', total_bytes: 10, connections: 1, asn: '', country: '' }],
		});
		vi.mocked(getConnections).mockResolvedValue({
			...table('192.168.1.20'),
			connections: [{ _id: 'x', _index: 'zeek-conn', '@timestamp': '2026-11-03T10:00:00Z', source: { ip: '192.168.1.20' }, destination: { ip: '203.0.113.9' } }],
		});
		const { container } = render(Page);
		await vi.waitFor(() => expect(container.querySelector('a.bar-label[href="/devices/192.168.1.20"]')).not.toBeNull());
		expect(container.querySelector('a.bar-label[href="/address/203.0.113.9"]')).not.toBeNull();

		await fireEvent.click(screen.getByRole('button', { name: /^Open connection from 192.168.1.20/ }));
		const dialog = await screen.findByRole('complementary', { name: 'Detail panel' });
		expect(within(dialog).getByRole('link', { name: 'Open source device' })).toHaveAttribute('href', '/devices/192.168.1.20');
		expect(within(dialog).getByRole('link', { name: 'Open destination address' })).toHaveAttribute('href', '/address/203.0.113.9');
		// NET-188: this record has no ports, so its packets link is all traffic between the two addresses, labelled inexact
		const packets = new URL(within(dialog).getByRole('link', { name: 'Open these packets' }).getAttribute('href')!, 'http://localhost');
		expect(packets.pathname).toBe('/packets');
		expect(packets.searchParams.get('filter')).toBe('ip.addr == 192.168.1.20 && ip.addr == 203.0.113.9');
		expect(packets.searchParams.get('exact')).toBe('0');
		expectNoNestedInteractive(container);
	});
});
