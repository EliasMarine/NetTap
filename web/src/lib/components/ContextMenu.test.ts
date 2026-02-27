import { describe, it, expect, vi, afterEach } from 'vitest';

/**
 * Tests for ContextMenu logic.
 *
 * The ContextMenu.svelte component manages a floating menu that appears at
 * mouse coordinates with viewport-boundary adjustment. Since the component
 * relies on Svelte 5 runes and DOM measurements (getBoundingClientRect), we
 * test the pure logic functions separately: icon path resolution, viewport
 * adjustment calculations, and ContextMenuItem interface behavior.
 */

// ---------------------------------------------------------------------------
// Reproduced logic from ContextMenu.svelte
// ---------------------------------------------------------------------------

/** Mirrors the ContextMenuItem interface exported by ContextMenu.svelte */
interface ContextMenuItem {
	label: string;
	icon?: string;
	action: () => void;
	separator?: boolean;
}

/** Mirrors the iconPath helper inside ContextMenu.svelte */
function iconPath(icon: string | undefined): string {
	switch (icon) {
		case 'search':
			return 'M11 17.25a6.25 6.25 0 110-12.5 6.25 6.25 0 010 12.5zM16 16l4.5 4.5';
		case 'device':
			return 'M2 3h20v14H2zM8 21h8M12 17v4';
		case 'geoip':
			return 'M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zM2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10A15.3 15.3 0 0112 2z';
		case 'copy':
			return 'M8 4H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2v-2M16 4h2a2 2 0 012 2v4M8 4a2 2 0 012-2h4a2 2 0 012 2v0a2 2 0 01-2 2h-4a2 2 0 01-2-2z';
		case 'external':
			return 'M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L20.5 3.5';
		default:
			return 'M12 12m-1 0a1 1 0 102 0 1 1 0 10-2 0';
	}
}

/**
 * Mirrors the viewport adjustment logic from the $effect block in ContextMenu.svelte.
 * Adjusts x/y so the menu stays within the viewport.
 */
function adjustPosition(
	x: number,
	y: number,
	menuWidth: number,
	menuHeight: number,
	viewportWidth: number,
	viewportHeight: number,
): { adjustedX: number; adjustedY: number } {
	const pad = 8;
	let newX = x;
	let newY = y;

	// Adjust horizontally
	if (newX + menuWidth + pad > viewportWidth) {
		newX = viewportWidth - menuWidth - pad;
	}
	if (newX < pad) {
		newX = pad;
	}

	// Adjust vertically
	if (newY + menuHeight + pad > viewportHeight) {
		newY = viewportHeight - menuHeight - pad;
	}
	if (newY < pad) {
		newY = pad;
	}

	return { adjustedX: newX, adjustedY: newY };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ContextMenu logic', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- iconPath -------------------------------------------------------------

	describe('iconPath', () => {
		it('returns search icon path for "search"', () => {
			const path = iconPath('search');
			expect(path).toContain('M11 17.25');
			expect(path).toContain('4.5');
		});

		it('returns device icon path for "device"', () => {
			const path = iconPath('device');
			expect(path).toContain('M2 3h20v14H2');
		});

		it('returns geoip icon path for "geoip"', () => {
			const path = iconPath('geoip');
			expect(path).toContain('M12 22c5.523');
		});

		it('returns copy icon path for "copy"', () => {
			const path = iconPath('copy');
			expect(path).toContain('M8 4H6');
		});

		it('returns external icon path for "external"', () => {
			const path = iconPath('external');
			expect(path).toContain('M18 13v6');
		});

		it('returns default circle-dot path for undefined icon', () => {
			const path = iconPath(undefined);
			expect(path).toContain('M12 12m-1 0');
		});

		it('returns default circle-dot path for unknown icon name', () => {
			const path = iconPath('nonexistent');
			expect(path).toContain('M12 12m-1 0');
		});

		it('returns default circle-dot path for empty string icon', () => {
			const path = iconPath('');
			expect(path).toContain('M12 12m-1 0');
		});
	});

	// -- adjustPosition -------------------------------------------------------

	describe('adjustPosition (viewport boundary adjustment)', () => {
		const vw = 1024;
		const vh = 768;
		const menuW = 200;
		const menuH = 150;

		it('returns original position when menu fits within viewport', () => {
			const result = adjustPosition(100, 100, menuW, menuH, vw, vh);
			expect(result.adjustedX).toBe(100);
			expect(result.adjustedY).toBe(100);
		});

		it('adjusts X leftward when menu overflows right edge', () => {
			const result = adjustPosition(900, 100, menuW, menuH, vw, vh);
			// 900 + 200 + 8 = 1108 > 1024, so newX = 1024 - 200 - 8 = 816
			expect(result.adjustedX).toBe(816);
			expect(result.adjustedY).toBe(100);
		});

		it('adjusts Y upward when menu overflows bottom edge', () => {
			const result = adjustPosition(100, 700, menuW, menuH, vw, vh);
			// 700 + 150 + 8 = 858 > 768, so newY = 768 - 150 - 8 = 610
			expect(result.adjustedX).toBe(100);
			expect(result.adjustedY).toBe(610);
		});

		it('adjusts both X and Y when overflowing bottom-right corner', () => {
			const result = adjustPosition(900, 700, menuW, menuH, vw, vh);
			expect(result.adjustedX).toBe(816);
			expect(result.adjustedY).toBe(610);
		});

		it('enforces minimum padding on left edge', () => {
			const result = adjustPosition(2, 100, menuW, menuH, vw, vh);
			// newX = 2 < pad(8), so newX = 8
			expect(result.adjustedX).toBe(8);
		});

		it('enforces minimum padding on top edge', () => {
			const result = adjustPosition(100, 3, menuW, menuH, vw, vh);
			// newY = 3 < pad(8), so newY = 8
			expect(result.adjustedY).toBe(8);
		});

		it('handles zero coordinates', () => {
			const result = adjustPosition(0, 0, menuW, menuH, vw, vh);
			expect(result.adjustedX).toBe(8);
			expect(result.adjustedY).toBe(8);
		});

		it('handles exact fit (no adjustment needed)', () => {
			// Position where menu exactly fills: x + menuW + pad = vw
			// x = 1024 - 200 - 8 = 816
			const result = adjustPosition(816, 610, menuW, menuH, vw, vh);
			expect(result.adjustedX).toBe(816);
			expect(result.adjustedY).toBe(610);
		});
	});

	// -- ContextMenuItem interface behavior -----------------------------------

	describe('ContextMenuItem behavior', () => {
		it('executes the action callback when invoked', () => {
			const action = vi.fn();
			const item: ContextMenuItem = {
				label: 'Test Action',
				action,
			};

			item.action();
			expect(action).toHaveBeenCalledOnce();
		});

		it('supports separator property', () => {
			const item: ContextMenuItem = {
				label: 'With Separator',
				action: vi.fn(),
				separator: true,
			};

			expect(item.separator).toBe(true);
		});

		it('defaults separator to undefined when not provided', () => {
			const item: ContextMenuItem = {
				label: 'No Separator',
				action: vi.fn(),
			};

			expect(item.separator).toBeUndefined();
		});

		it('supports optional icon property', () => {
			const item: ContextMenuItem = {
				label: 'With Icon',
				icon: 'search',
				action: vi.fn(),
			};

			expect(item.icon).toBe('search');
		});

		it('builds a full menu item list correctly', () => {
			const items: ContextMenuItem[] = [
				{ label: 'Copy IP', icon: 'copy', action: vi.fn() },
				{ label: 'View device', icon: 'device', separator: true, action: vi.fn() },
				{ label: 'GeoIP lookup', icon: 'geoip', action: vi.fn() },
			];

			expect(items).toHaveLength(3);
			expect(items[0].label).toBe('Copy IP');
			expect(items[1].separator).toBe(true);
			expect(items[2].icon).toBe('geoip');
		});
	});
});
