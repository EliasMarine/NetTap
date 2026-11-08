import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { goto } from '$app/navigation';
// OLD CODE: import * as searchApi from '$api/search'; (NET-202: the suggestions are the registry's devices)
import * as registryApi from '$api/devices-registry';
import type { RegistryDevice, RegistryListResponse } from '$api/devices-registry';
import { addressHref } from '$lib/stores/lan';
import type { LanPolicy } from '$lib/api/network';
// OLD CODE: import { searchTarget, updatedText } from './topbar'; (NET-202)
import { deviceSuggestions, isSearchIp, searchTarget, updatedText } from './topbar';
import { registerPageRefresh, type PageRefreshHandle } from '$lib/stores/pageRefresh';
import TopBar from './TopBar.svelte';

const POLICY: LanPolicy = { version: 'v1', subnets: ['192.168.1.0/24'], source: 'env', ipv6: 'not-lan' };

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
// OLD CODE: vi.mock('$api/search', () => ({ getSearchSuggestions: vi.fn() })); (NET-202)
vi.mock('$api/devices-registry', () => ({ getRegistryDevices: vi.fn() }));
// The top bar's IP links follow the daemon's LAN policy (NET-160): 192.168.1.0/24 here
vi.mock('$lib/api/network', () => ({
	getLanPolicy: vi.fn(async () => ({ version: 'v1', subnets: ['192.168.1.0/24'], source: 'env', ipv6: 'not-lan' })),
}));
// The bell has its own tests; here it only has to render.
vi.mock('$components/NotificationBell.svelte', async () => ({
	default: (await import('./BrandMark.svelte')).default,
}));

// OLD CODE: const suggest = vi.mocked(searchApi.getSearchSuggestions); (NET-202)
const registry = vi.mocked(registryApi.getRegistryDevices);

function dev(mac: string, name: string, ips: string[], extra: Partial<RegistryDevice> = {}): RegistryDevice {
	return {
		mac, ips, hostnames: [], manufacturer: null, friendly_name: null, display_name: name, category: 'computer',
		first_seen: '2026-11-01T00:00:00Z', last_seen: '2026-11-07T00:00:00Z', is_new: false, ...extra,
	};
}

const KITCHEN = dev('AA:00:00:00:00:10', 'Kitchen iPad', ['192.168.1.10'], { hostnames: ['ipad.lan'] });
const PRINTER = dev('AA:00:00:00:00:20', 'Office printer', ['192.168.1.20']);
const APPLE_1 = dev('AA:00:00:00:00:30', 'Apple', ['192.168.1.30']);
const APPLE_2 = dev('AA:00:00:00:00:31', 'Apple', ['192.168.1.31']);
const GATEWAY = dev('D0:21:F9:5E:35:32', 'Gateway', ['192.168.1.1']);
const ROOM = dev('AA:00:00:00:00:40', 'Room 20', ['192.168.1.40']);
const DEVICES = [KITCHEN, PRINTER, APPLE_1, APPLE_2, GATEWAY, ROOM];
const reply = (devices: RegistryDevice[]): RegistryListResponse => ({ devices, total: devices.length });
const macHref = (d: RegistryDevice) => `/devices/mac/${encodeURIComponent(d.mac)}`;

/** A registry reply the test resolves (or fails) when it chooses. */
function deferred() {
	let resolve: (v: RegistryListResponse) => void = () => {};
	let reject: (e: unknown) => void = () => {};
	const promise = new Promise<RegistryListResponse>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

async function type(text: string) {
	const box = screen.getByRole('combobox');
	await fireEvent.focus(box); // as a click or Ctrl-K would; focus loads the LAN policy
	await fireEvent.input(box, { target: { value: text } });
	await vi.advanceTimersByTimeAsync(250);
	return box;
}

/** Enter in the box, then let the registry wait (if any) settle. */
async function enter(box: HTMLElement) {
	await fireEvent.keyDown(box, { key: 'Enter' });
	await vi.advanceTimersByTimeAsync(0);
}

let handle: PageRefreshHandle | undefined;

beforeEach(() => {
	vi.useFakeTimers();
	// OLD CODE: suggest.mockResolvedValue({ suggestions: ['192.168.1.10', '192.168.1.20'] }); (NET-202)
	registry.mockResolvedValue(reply(DEVICES));
});

afterEach(() => {
	handle?.unregister();
	handle = undefined;
	vi.useRealTimers();
	vi.clearAllMocks();
});

// OLD CODE START — NET-202: every IP went to Log Explorer, and every other text was a log query
// describe('searchTarget', () => {
// 	it.each([
// 		['192.168.1.42', '/logs?ip=192.168.1.42'],
// 		[' 10.0.0.1 ', '/logs?ip=10.0.0.1'],
// 		['fe80::1', '/logs?ip=fe80%3A%3A1'],
// 		['github.com', '/logs?query=github.com'],
// 		['Kitchen iPad', '/logs?query=Kitchen%20iPad'],
// 	])('%s → %s', (q, target) => {
// 		expect(searchTarget(q)).toBe(target);
// 	});
//
// 	it('does nothing for empty input', () => {
// 		expect(searchTarget('   ')).toBeNull();
// 	});
// });
// OLD CODE END
describe('searchTarget (NET-202)', () => {
	const ipHref = (ip: string) => addressHref(POLICY, ip);
	const target = (q: string) => searchTarget(q, ipHref, DEVICES);

	it.each([
		// an IP opens its own page: the device page on the LAN, the address page otherwise
		['192.168.1.42', '/devices/192.168.1.42'],
		[' 8.8.8.8 ', '/address/8.8.8.8'],
		['fe80::1', '/address/fe80%3A%3A1'],
		['::ffff:192.168.1.5', '/address/%3A%3Affff%3A192.168.1.5'],
		// a MAC is not IPv6: its device, or a log search when no device has it
		['d0:21:f9:5e:35:32', macHref(GATEWAY)],
		['AA:BB:CC:DD:EE:FF', '/logs?query=AA%3ABB%3ACC%3ADD%3AEE%3AFF'],
		['a:b:c', '/logs?query=a%3Ab%3Ac'],
		['1:2:3:4:5:6:7:8:9', '/logs?query=1%3A2%3A3%3A4%3A5%3A6%3A7%3A8%3A9'],
		// a device's exact name or hostname (before the domain rule), any case
		['kitchen ipad', macHref(KITCHEN)],
		['IPAD.lan', macHref(KITCHEN)],
		['github.com', '/domain/github.com'],
		['Kitchen', '/logs?query=Kitchen'],
	])('%s → %s', (q, href) => {
		expect(target(q)).toEqual({ href });
	});

	it('returns the devices to pick from when several share the name', () => {
		expect(target('apple')).toEqual({ matches: [APPLE_1, APPLE_2] });
	});

	it('searches without devices when the registry is unknown', () => {
		expect(searchTarget('Kitchen iPad', ipHref)).toEqual({ href: '/logs?query=Kitchen%20iPad' });
	});

	it('does nothing for empty input', () => {
		expect(target('   ')).toBeNull();
	});

	it('takes only real addresses as IPs', () => {
		expect(['10.0.0.1', '::1', '2001:db8::8a2e:370:7334', '::ffff:10.0.0.1'].every(isSearchIp)).toBe(true);
		// "::1]#[" parses as a URL with host [::1]; a MAC and a bad octet are not addresses either
		expect(['::1]#[', 'D0:21:F9:5E:35:32', '256.1.1.1', 'fe80::1%eth0', 'router'].some(isSearchIp)).toBe(false);
	});
});

describe('deviceSuggestions (NET-202)', () => {
	it('lists name matches before address matches, each opening its MAC', () => {
		// Room 20 is named "20"; the printer only has an address with 20 in it
		expect(deviceSuggestions(DEVICES, '20')).toEqual([
			{ label: 'Room 20', detail: '192.168.1.40 · AA:00:00:00:00:40', href: macHref(ROOM) },
			{ label: 'Office printer', detail: '192.168.1.20 · AA:00:00:00:00:20', href: macHref(PRINTER) },
		]);
	});

	it('matches hostnames and MACs, any case, and shows the MAC alone without an IP', () => {
		const bare = dev('BB:00:00:00:00:01', '', []);
		expect(deviceSuggestions([KITCHEN, bare], 'IPAD').map((s) => s.label)).toEqual(['Kitchen iPad']);
		expect(deviceSuggestions([KITCHEN, bare], 'bb:00')).toEqual([{ label: 'BB:00:00:00:00:01', detail: 'BB:00:00:00:00:01', href: macHref(bare) }]);
	});

	it('shows at most 6', () => {
		const many = Array.from({ length: 8 }, (_, i) => dev(`CC:00:00:00:00:0${i}`, `Sensor ${i}`, []));
		expect(deviceSuggestions(many, 'sensor')).toHaveLength(6);
	});
});

describe('updatedText', () => {
	const t0 = new Date(2026, 10, 3, 21, 5, 0).getTime();

	it.each([
		[null, 'Not updated yet'],
		[t0, 'Updated just now'],
		[t0 - 12_000, 'Updated 12 s ago'],
		[t0 - 5 * 60_000, 'Updated 5 min ago'],
		[t0 - 2 * 3_600_000, 'Updated at 19:05'],
	])('%s', (at, text) => {
		expect(updatedText(at, t0)).toBe(text);
	});
});

// OLD CODE START — NET-202: the suggestions were the daemon's canned sentences, opened in Log Explorer
// describe('TopBar search', () => {
// 	it('lists suggestions and announces how many', async () => {
// 		render(TopBar, { props: { offline: false } });
// 		const box = await type('192.168');
// 		expect(box).toHaveAttribute('aria-expanded', 'true');
// 		expect(box).toHaveAttribute('aria-controls', 'global-search-list');
// 		expect(screen.getAllByRole('option')).toHaveLength(2);
// 		expect(screen.getByRole('status')).toHaveTextContent('2 suggestions.');
// 	});
//
// 	it('moves through results with the arrow keys and opens the chosen one', async () => {
// 		render(TopBar, { props: { offline: false } });
// 		const box = await type('192.168');
// 		await fireEvent.keyDown(box, { key: 'ArrowDown' });
// 		await fireEvent.keyDown(box, { key: 'ArrowDown' });
// 		expect(box).toHaveAttribute('aria-activedescendant', 'global-search-list-1');
// 		expect(screen.getAllByRole('option')[1]).toHaveAttribute('aria-selected', 'true');
// 		await fireEvent.keyDown(box, { key: 'ArrowUp' });
// 		await fireEvent.keyDown(box, { key: 'Enter' });
// 		expect(goto).toHaveBeenCalledWith('/logs?ip=192.168.1.10');
// 	});
//
// 	it('searches the typed text when nothing is highlighted', async () => {
// 		render(TopBar, { props: { offline: false } });
// 		const box = await type('github.com');
// 		await fireEvent.keyDown(box, { key: 'Enter' });
// 		expect(goto).toHaveBeenCalledWith('/logs?query=github.com');
// 	});
//
// 	it('says when nothing matches', async () => {
// 		suggest.mockResolvedValue({ suggestions: [] });
// 		render(TopBar, { props: { offline: false } });
// 		const box = await type('zzzz');
// 		expect(screen.getByRole('status')).toHaveTextContent('No matches for "zzzz".');
// 		expect(box).toHaveAttribute('aria-expanded', 'false');
// 		expect(screen.queryAllByRole('option')).toHaveLength(0);
// 	});
//
// 	it('says when suggestions could not load', async () => {
// 		suggest.mockRejectedValue(new Error('network'));
// 		render(TopBar, { props: { offline: false } });
// 		await type('router');
// 		expect(screen.getByRole('status')).toHaveTextContent("Couldn't load suggestions.");
// 	});
//
// 	it('closes the list on Escape, then clears the field on a second Escape', async () => {
// 		render(TopBar, { props: { offline: false } });
// 		const box = (await type('192.168')) as HTMLInputElement;
// 		await fireEvent.keyDown(box, { key: 'Escape' });
// 		expect(box).toHaveAttribute('aria-expanded', 'false');
// 		expect(box.value).toBe('192.168');
// 		await fireEvent.keyDown(box, { key: 'Escape' });
// 		expect(box.value).toBe('');
// 	});
//
// 	it('only shows the newest keystroke\'s suggestions', async () => {
// 		let resolveSlow: (v: { suggestions: string[] }) => void = () => {};
// 		suggest
// 			.mockReturnValueOnce(new Promise((r) => (resolveSlow = r)))
// 			.mockResolvedValueOnce({ suggestions: ['new.example'] });
// 		render(TopBar, { props: { offline: false } });
// 		await type('ol');
// 		await type('new');
// 		resolveSlow({ suggestions: ['old.example'] });
// 		await vi.advanceTimersByTimeAsync(0);
// 		expect(screen.getByRole('option')).toHaveTextContent('new.example');
// 	});
//
// 	it('keeps the list shut when Enter beats the debounce', async () => {
// 		render(TopBar, { props: { offline: false } });
// 		const box = screen.getByRole('combobox');
// 		await fireEvent.input(box, { target: { value: '10.0.0.5' } });
// 		await fireEvent.keyDown(box, { key: 'Enter' });
// 		await vi.advanceTimersByTimeAsync(250);
// 		expect(goto).toHaveBeenCalledTimes(1);
// 		expect(suggest).not.toHaveBeenCalled();
// 		expect(box).toHaveAttribute('aria-expanded', 'false');
// 	});
//
// 	it('keeps the list shut when a slow answer lands after the text got too short', async () => {
// 		let resolveSlow: (v: { suggestions: string[] }) => void = () => {};
// 		suggest.mockReturnValueOnce(new Promise((r) => (resolveSlow = r)));
// 		render(TopBar, { props: { offline: false } });
// 		const box = await type('ro');
// 		await fireEvent.input(box, { target: { value: 'r' } });
// 		resolveSlow({ suggestions: ['router.lan'] });
// 		await vi.advanceTimersByTimeAsync(0);
// 		expect(box).toHaveAttribute('aria-expanded', 'false');
// 		expect(screen.queryAllByRole('option')).toHaveLength(0);
// 	});
//
// 	it('focuses search on Ctrl-K', async () => {
// 		render(TopBar, { props: { offline: false } });
// 		await fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
// 		expect(document.activeElement).toBe(screen.getByRole('combobox'));
// 	});
// });
// OLD CODE END
describe('TopBar search (NET-202)', () => {
	it('lists the matching devices and announces how many', async () => {
		render(TopBar, { props: { offline: false } });
		const box = await type('apple');
		expect(box).toHaveAttribute('aria-expanded', 'true');
		expect(box).toHaveAttribute('aria-controls', 'global-search-list');
		const options = screen.getAllByRole('option');
		expect(options).toHaveLength(2);
		expect(options[1]).toHaveTextContent('Apple 192.168.1.31 · AA:00:00:00:00:31');
		expect(screen.getByRole('status')).toHaveTextContent('2 suggestions.');
	});

	it('moves through results with the arrow keys and opens the chosen device', async () => {
		render(TopBar, { props: { offline: false } });
		const box = await type('apple');
		await fireEvent.keyDown(box, { key: 'ArrowDown' });
		await fireEvent.keyDown(box, { key: 'ArrowDown' });
		expect(box).toHaveAttribute('aria-activedescendant', 'global-search-list-1');
		expect(screen.getAllByRole('option')[1]).toHaveAttribute('aria-selected', 'true');
		await fireEvent.keyDown(box, { key: 'ArrowUp' });
		await fireEvent.keyDown(box, { key: 'Enter' });
		expect(goto).toHaveBeenCalledWith(macHref(APPLE_1));
	});

	// NET-202 review: read at mount, every page (sign-in and setup too) asked for the policy, a 401 before sign-in
	it('asks for the LAN policy only once search takes focus', async () => {
		const { getLanPolicy } = await import('$lib/api/network');
		render(TopBar, { props: { offline: false } });
		await vi.advanceTimersByTimeAsync(0);
		expect(getLanPolicy).not.toHaveBeenCalled();
		await fireEvent.focus(screen.getByRole('combobox'));
		await vi.advanceTimersByTimeAsync(0);
		expect(getLanPolicy).toHaveBeenCalledTimes(1);
	});

	it("opens a LAN IP's device page and an outside IP's address page", async () => {
		render(TopBar, { props: { offline: false } });
		await enter(await type('192.168.1.42'));
		expect(goto).toHaveBeenLastCalledWith('/devices/192.168.1.42');
		await enter(await type('8.8.8.8'));
		expect(goto).toHaveBeenLastCalledWith('/address/8.8.8.8');
	});

	it('opens a domain, and searches Log Explorer for anything else', async () => {
		render(TopBar, { props: { offline: false } });
		await enter(await type('github.com'));
		expect(goto).toHaveBeenLastCalledWith('/domain/github.com');
		await enter(await type('dns failures'));
		expect(goto).toHaveBeenLastCalledWith('/logs?query=dns%20failures');
	});

	it('waits for the devices when Enter beats the debounce, then opens the named device', async () => {
		const slow = deferred();
		registry.mockReturnValueOnce(slow.promise);
		render(TopBar, { props: { offline: false } });
		const box = screen.getByRole('combobox');
		await fireEvent.input(box, { target: { value: 'Kitchen iPad' } });
		await enter(box);
		expect(goto).not.toHaveBeenCalled();
		slow.resolve(reply(DEVICES));
		await vi.advanceTimersByTimeAsync(250);
		expect(goto).toHaveBeenCalledTimes(1);
		expect(goto).toHaveBeenCalledWith(macHref(KITCHEN));
		expect(registry).toHaveBeenCalledTimes(1);
		expect(box).toHaveAttribute('aria-expanded', 'false');
	});

	it('shares one registry request between the suggestions and an Enter while it is pending', async () => {
		const slow = deferred();
		registry.mockReturnValueOnce(slow.promise);
		render(TopBar, { props: { offline: false } });
		const box = await type('Kitchen iPad'); // the suggestions' request is pending
		await enter(box);
		slow.resolve(reply(DEVICES));
		await vi.advanceTimersByTimeAsync(0);
		expect(goto).toHaveBeenCalledWith(macHref(KITCHEN));
		expect(registry).toHaveBeenCalledTimes(1);
	});

	it('still searches when the devices cannot load', async () => {
		registry.mockRejectedValue(new Error('network'));
		render(TopBar, { props: { offline: false } });
		const box = screen.getByRole('combobox');
		await fireEvent.input(box, { target: { value: 'Kitchen iPad' } });
		await enter(box);
		expect(goto).toHaveBeenCalledWith('/logs?query=Kitchen%20iPad');
	});

	it('drops a waiting Enter when the text changes', async () => {
		const slow = deferred();
		registry.mockReturnValueOnce(slow.promise);
		render(TopBar, { props: { offline: false } });
		const box = screen.getByRole('combobox');
		await fireEvent.input(box, { target: { value: 'Kitchen iPad' } });
		await enter(box);
		await fireEvent.input(box, { target: { value: 'Kitch' } });
		slow.resolve(reply(DEVICES));
		await vi.advanceTimersByTimeAsync(0);
		expect(goto).not.toHaveBeenCalled();
	});

	it('lists the devices sharing a typed name to pick from, by MAC', async () => {
		render(TopBar, { props: { offline: false } });
		const box = screen.getByRole('combobox');
		await fireEvent.input(box, { target: { value: 'Apple' } });
		await enter(box);
		expect(goto).not.toHaveBeenCalled();
		expect(box).toHaveAttribute('aria-expanded', 'true');
		expect(screen.getAllByRole('option')).toHaveLength(2);
		expect(screen.getByRole('status')).toHaveTextContent('2 devices are called "Apple". Pick one.');
		await fireEvent.mouseDown(screen.getAllByRole('option')[1]);
		expect(goto).toHaveBeenCalledWith(macHref(APPLE_2));
	});

	it('says when nothing matches', async () => {
		render(TopBar, { props: { offline: false } });
		const box = await type('zzzz');
		expect(screen.getByRole('status')).toHaveTextContent('No matches for "zzzz".');
		expect(box).toHaveAttribute('aria-expanded', 'false');
		expect(screen.queryAllByRole('option')).toHaveLength(0);
	});

	it('says when suggestions could not load, and asks again on the next keystroke', async () => {
		registry.mockRejectedValueOnce(new Error('network'));
		render(TopBar, { props: { offline: false } });
		await type('router');
		expect(screen.getByRole('status')).toHaveTextContent("Couldn't load suggestions.");
		await type('apple');
		expect(registry).toHaveBeenCalledTimes(2);
		expect(screen.getAllByRole('option')).toHaveLength(2);
	});

	it('asks for the devices at most once a minute', async () => {
		render(TopBar, { props: { offline: false } });
		await type('apple');
		await type('kitchen');
		expect(registry).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(61_000);
		await type('office');
		expect(registry).toHaveBeenCalledTimes(2);
	});

	it('closes the list on Escape, then clears the field on a second Escape', async () => {
		render(TopBar, { props: { offline: false } });
		const box = (await type('apple')) as HTMLInputElement;
		await fireEvent.keyDown(box, { key: 'Escape' });
		expect(box).toHaveAttribute('aria-expanded', 'false');
		expect(box.value).toBe('apple');
		await fireEvent.keyDown(box, { key: 'Escape' });
		expect(box.value).toBe('');
	});

	it("only shows the newest keystroke's suggestions", async () => {
		const slow = deferred();
		registry.mockReturnValueOnce(slow.promise);
		render(TopBar, { props: { offline: false } });
		await type('ol');
		await type('new');
		slow.resolve(reply([dev('EE:00:00:00:00:01', 'Old box', []), dev('EE:00:00:00:00:02', 'New box', [])]));
		await vi.advanceTimersByTimeAsync(0);
		expect(screen.getByRole('option')).toHaveTextContent('New box');
	});

	it('keeps the list shut when Enter beats the debounce on an IP, with no registry request', async () => {
		render(TopBar, { props: { offline: false } });
		const box = screen.getByRole('combobox');
		await fireEvent.input(box, { target: { value: '10.0.0.5' } });
		await fireEvent.keyDown(box, { key: 'Enter' });
		await vi.advanceTimersByTimeAsync(250);
		expect(goto).toHaveBeenCalledTimes(1);
		expect(goto).toHaveBeenCalledWith('/address/10.0.0.5');
		expect(registry).not.toHaveBeenCalled();
		expect(box).toHaveAttribute('aria-expanded', 'false');
	});

	it('keeps the list shut when a slow answer lands after the text got too short', async () => {
		const slow = deferred();
		registry.mockReturnValueOnce(slow.promise);
		render(TopBar, { props: { offline: false } });
		const box = await type('ro');
		await fireEvent.input(box, { target: { value: 'r' } });
		slow.resolve(reply([dev('EE:00:00:00:00:03', 'router.lan', [])]));
		await vi.advanceTimersByTimeAsync(0);
		expect(box).toHaveAttribute('aria-expanded', 'false');
		expect(screen.queryAllByRole('option')).toHaveLength(0);
	});

	it('focuses search on Ctrl-K', async () => {
		render(TopBar, { props: { offline: false } });
		await fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
		expect(document.activeElement).toBe(screen.getByRole('combobox'));
	});
});

describe('TopBar refresh and status', () => {
	it('hides Refresh and the timestamp on pages without a loader', () => {
		render(TopBar, { props: { offline: false } });
		expect(screen.queryByRole('button', { name: 'Refresh this page' })).not.toBeInTheDocument();
		expect(screen.queryByText(/Updated|Not updated/)).not.toBeInTheDocument();
	});

	it('runs the page loader and shows when it last fully succeeded', async () => {
		const loader = vi.fn(async () => 'ok' as const);
		handle = registerPageRefresh(loader);
		render(TopBar, { props: { offline: false } });
		expect(screen.getByText('Not updated yet')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Refresh this page' }));
		await vi.advanceTimersByTimeAsync(1000);
		expect(loader).toHaveBeenCalledTimes(1);
		expect(screen.getByText('Updated just now')).toBeInTheDocument();
	});

	it('says some data failed after a partial refresh', async () => {
		handle = registerPageRefresh(async () => 'partial');
		render(TopBar, { props: { offline: false } });
		await fireEvent.click(screen.getByRole('button', { name: 'Refresh this page' }));
		await vi.advanceTimersByTimeAsync(0);
		expect(screen.getByText('Some data failed to refresh')).toBeInTheDocument();
		expect(screen.getByText('Not updated yet')).toBeInTheDocument();
	});

	it("warns when NetTap can't be reached", () => {
		render(TopBar, { props: { offline: true } });
		expect(screen.getByText("Can't reach NetTap")).toBeInTheDocument();
	});
});
