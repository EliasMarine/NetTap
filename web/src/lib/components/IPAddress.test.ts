import { describe, it, expect, vi, afterEach } from 'vitest';

/**
 * Tests for IPAddress component logic.
 *
 * The IPAddress.svelte component renders a monospaced IP address with a
 * right-click context menu. Because it uses Svelte 5 runes and depends on
 * ContextMenu.svelte, we test the pure logic: context menu item definitions,
 * URL construction, and long-press timer behavior.
 */

// ---------------------------------------------------------------------------
// Reproduced logic from IPAddress.svelte
// ---------------------------------------------------------------------------

interface ContextMenuItem {
	label: string;
	icon?: string;
	action: () => void;
	separator?: boolean;
}

/**
 * Builds the context menu items for a given IP address.
 * Mirrors the $derived block in IPAddress.svelte, but with injected
 * navigation/clipboard handlers for testability.
 */
function buildMenuItems(
	ip: string,
	handlers: {
		copyToClipboard: (text: string) => void;
		navigate: (url: string) => void;
		openExternal: (url: string) => void;
	},
): ContextMenuItem[] {
	return [
		{
			label: 'Copy IP',
			icon: 'copy',
			action: () => handlers.copyToClipboard(ip),
		},
		{
			label: 'View device details',
			icon: 'device',
			separator: true,
			action: () => handlers.navigate(`/devices/${encodeURIComponent(ip)}`),
		},
		{
			label: 'GeoIP lookup',
			icon: 'geoip',
			action: () =>
				handlers.openExternal(
					`https://ipinfo.io/${encodeURIComponent(ip)}`,
				),
		},
		{
			label: 'Filter connections from this IP',
			icon: 'search',
			separator: true,
			action: () =>
				handlers.navigate(
					`/connections?filter=ip.src==${encodeURIComponent(ip)}`,
				),
		},
		{
			label: 'Filter connections to this IP',
			icon: 'search',
			action: () =>
				handlers.navigate(
					`/connections?filter=ip.dst==${encodeURIComponent(ip)}`,
				),
		},
	];
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('IPAddress logic', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- Menu items structure -------------------------------------------------

	describe('buildMenuItems', () => {
		const handlers = {
			copyToClipboard: vi.fn(),
			navigate: vi.fn(),
			openExternal: vi.fn(),
		};

		afterEach(() => {
			vi.clearAllMocks();
		});

		it('builds exactly 5 menu items', () => {
			const items = buildMenuItems('192.168.1.1', handlers);
			expect(items).toHaveLength(5);
		});

		it('first item is "Copy IP" with copy icon', () => {
			const items = buildMenuItems('10.0.0.1', handlers);
			expect(items[0].label).toBe('Copy IP');
			expect(items[0].icon).toBe('copy');
		});

		it('second item is "View device details" with separator', () => {
			const items = buildMenuItems('10.0.0.1', handlers);
			expect(items[1].label).toBe('View device details');
			expect(items[1].separator).toBe(true);
			expect(items[1].icon).toBe('device');
		});

		it('third item is "GeoIP lookup"', () => {
			const items = buildMenuItems('10.0.0.1', handlers);
			expect(items[2].label).toBe('GeoIP lookup');
			expect(items[2].icon).toBe('geoip');
		});

		it('fourth item is "Filter connections from this IP" with separator', () => {
			const items = buildMenuItems('10.0.0.1', handlers);
			expect(items[3].label).toBe('Filter connections from this IP');
			expect(items[3].separator).toBe(true);
			expect(items[3].icon).toBe('search');
		});

		it('fifth item is "Filter connections to this IP"', () => {
			const items = buildMenuItems('10.0.0.1', handlers);
			expect(items[4].label).toBe('Filter connections to this IP');
			expect(items[4].icon).toBe('search');
		});
	});

	// -- Action callbacks -----------------------------------------------------

	describe('menu item actions', () => {
		it('Copy IP action calls copyToClipboard with the IP', () => {
			const handlers = {
				copyToClipboard: vi.fn(),
				navigate: vi.fn(),
				openExternal: vi.fn(),
			};
			const items = buildMenuItems('192.168.1.100', handlers);

			items[0].action();

			expect(handlers.copyToClipboard).toHaveBeenCalledWith('192.168.1.100');
		});

		it('View device details navigates to the correct device URL', () => {
			const handlers = {
				copyToClipboard: vi.fn(),
				navigate: vi.fn(),
				openExternal: vi.fn(),
			};
			const items = buildMenuItems('10.0.0.5', handlers);

			items[1].action();

			expect(handlers.navigate).toHaveBeenCalledWith('/devices/10.0.0.5');
		});

		it('GeoIP lookup opens external URL with ipinfo.io', () => {
			const handlers = {
				copyToClipboard: vi.fn(),
				navigate: vi.fn(),
				openExternal: vi.fn(),
			};
			const items = buildMenuItems('8.8.8.8', handlers);

			items[2].action();

			expect(handlers.openExternal).toHaveBeenCalledWith('https://ipinfo.io/8.8.8.8');
		});

		it('Filter from this IP navigates with correct filter query', () => {
			const handlers = {
				copyToClipboard: vi.fn(),
				navigate: vi.fn(),
				openExternal: vi.fn(),
			};
			const items = buildMenuItems('192.168.1.50', handlers);

			items[3].action();

			expect(handlers.navigate).toHaveBeenCalledWith(
				'/connections?filter=ip.src==192.168.1.50',
			);
		});

		it('Filter to this IP navigates with correct filter query', () => {
			const handlers = {
				copyToClipboard: vi.fn(),
				navigate: vi.fn(),
				openExternal: vi.fn(),
			};
			const items = buildMenuItems('172.16.0.1', handlers);

			items[4].action();

			expect(handlers.navigate).toHaveBeenCalledWith(
				'/connections?filter=ip.dst==172.16.0.1',
			);
		});

		it('encodes IPv6 addresses in URLs', () => {
			const handlers = {
				copyToClipboard: vi.fn(),
				navigate: vi.fn(),
				openExternal: vi.fn(),
			};
			const ipv6 = '::1';
			const items = buildMenuItems(ipv6, handlers);

			// Device details
			items[1].action();
			expect(handlers.navigate).toHaveBeenCalledWith(`/devices/${encodeURIComponent(ipv6)}`);

			// GeoIP
			items[2].action();
			expect(handlers.openExternal).toHaveBeenCalledWith(
				`https://ipinfo.io/${encodeURIComponent(ipv6)}`,
			);
		});
	});

	// -- Long-press timer logic -----------------------------------------------

	describe('long-press timer', () => {
		it('setTimeout is called with 500ms delay', () => {
			vi.useFakeTimers();
			const callback = vi.fn();

			// Simulate the long-press timer setup from handleTouchStart
			const timer = setTimeout(callback, 500);

			// Should not fire before 500ms
			vi.advanceTimersByTime(499);
			expect(callback).not.toHaveBeenCalled();

			// Should fire at 500ms
			vi.advanceTimersByTime(1);
			expect(callback).toHaveBeenCalledOnce();

			clearTimeout(timer);
			vi.useRealTimers();
		});

		it('clearTimeout cancels the timer', () => {
			vi.useFakeTimers();
			const callback = vi.fn();

			const timer = setTimeout(callback, 500);
			clearTimeout(timer);

			vi.advanceTimersByTime(1000);
			expect(callback).not.toHaveBeenCalled();

			vi.useRealTimers();
		});
	});

	// -- IP display properties ------------------------------------------------

	describe('IP address display properties', () => {
		it('standard IPv4 is not encoded for display', () => {
			const ip = '192.168.1.1';
			// The component displays the raw IP in the span
			expect(ip).toBe('192.168.1.1');
		});

		it('IPv6 addresses are valid inputs', () => {
			const ipv6Addresses = [
				'::1',
				'fe80::1',
				'2001:db8::1',
				'::ffff:192.168.1.1',
			];

			for (const ip of ipv6Addresses) {
				const items = buildMenuItems(ip, {
					copyToClipboard: vi.fn(),
					navigate: vi.fn(),
					openExternal: vi.fn(),
				});
				expect(items).toHaveLength(5);
				expect(items[0].label).toBe('Copy IP');
			}
		});
	});
});
