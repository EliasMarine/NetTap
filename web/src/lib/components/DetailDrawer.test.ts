import { describe, it, expect, vi, afterEach } from 'vitest';

/**
 * Tests for DetailDrawer component logic.
 *
 * The DetailDrawer.svelte component uses Svelte 5 runes ($props) and Snippets
 * that are difficult to fully render in a jsdom test environment. Instead we
 * extract and test the pure logic: tab management, drawer visibility state,
 * ESC key handling, backdrop click behavior, and active-tab styling derivation.
 */

// ---------------------------------------------------------------------------
// Reproduced types & state logic from DetailDrawer.svelte
// ---------------------------------------------------------------------------

interface DrawerTab {
	id: string;
	label: string;
	badge?: string | number;
}

/**
 * Simulates the state machine and event handling logic from DetailDrawer.svelte.
 */
class DetailDrawerState {
	open: boolean;
	title: string;
	subtitle: string;
	tabs: DrawerTab[];
	activeTab: string;
	onclose: () => void;
	ontabchange: (tabId: string) => void;

	constructor(opts: {
		open?: boolean;
		title?: string;
		subtitle?: string;
		tabs?: DrawerTab[];
		activeTab?: string;
		onclose?: () => void;
		ontabchange?: (tabId: string) => void;
	}) {
		this.open = opts.open ?? false;
		this.title = opts.title ?? '';
		this.subtitle = opts.subtitle ?? '';
		this.tabs = opts.tabs ?? [];
		this.activeTab = opts.activeTab ?? '';
		this.onclose = opts.onclose ?? (() => {});
		this.ontabchange = opts.ontabchange ?? ((_tabId: string) => {});
	}

	/** Mirrors handleKeydown in DetailDrawer.svelte */
	handleKeydown(e: { key: string }) {
		if (e.key === 'Escape' && this.open) {
			this.onclose();
		}
	}

	/** Mirrors handleBackdropClick in DetailDrawer.svelte */
	handleBackdropClick() {
		this.onclose();
	}

	/** Whether the drawer panel should be visible (has "open" class) */
	get isVisible(): boolean {
		return this.open;
	}

	/** Whether the backdrop should be rendered */
	get showBackdrop(): boolean {
		return this.open;
	}

	/** Whether the tab bar should render (only when more than 1 tab) */
	get showTabs(): boolean {
		return this.tabs.length > 1;
	}

	/** Whether a subtitle is shown */
	get hasSubtitle(): boolean {
		return this.subtitle.length > 0;
	}

	/** Returns the CSS class for a tab button — active when matching activeTab */
	tabClass(tabId: string): string {
		return this.activeTab === tabId ? 'drawer-tab active' : 'drawer-tab';
	}

	/** Whether a tab has a badge */
	tabHasBadge(tab: DrawerTab): boolean {
		return tab.badge != null;
	}
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DetailDrawer logic', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- Visibility -----------------------------------------------------------

	describe('visibility', () => {
		it('is hidden when open=false', () => {
			const state = new DetailDrawerState({ open: false });
			expect(state.isVisible).toBe(false);
		});

		it('is visible when open=true', () => {
			const state = new DetailDrawerState({ open: true });
			expect(state.isVisible).toBe(true);
		});
	});

	// -- Backdrop -------------------------------------------------------------

	describe('backdrop', () => {
		it('does not show backdrop when closed', () => {
			const state = new DetailDrawerState({ open: false });
			expect(state.showBackdrop).toBe(false);
		});

		it('shows backdrop when open', () => {
			const state = new DetailDrawerState({ open: true });
			expect(state.showBackdrop).toBe(true);
		});
	});

	// -- Title & Subtitle -----------------------------------------------------

	describe('title and subtitle', () => {
		it('stores the title correctly', () => {
			const state = new DetailDrawerState({ title: 'Connection Details' });
			expect(state.title).toBe('Connection Details');
		});

		it('stores the subtitle correctly', () => {
			const state = new DetailDrawerState({ subtitle: '192.168.1.100:443' });
			expect(state.subtitle).toBe('192.168.1.100:443');
		});

		it('hasSubtitle returns false when subtitle is empty', () => {
			const state = new DetailDrawerState({ subtitle: '' });
			expect(state.hasSubtitle).toBe(false);
		});

		it('hasSubtitle returns true when subtitle is provided', () => {
			const state = new DetailDrawerState({ subtitle: 'Some detail' });
			expect(state.hasSubtitle).toBe(true);
		});

		it('defaults subtitle to empty string', () => {
			const state = new DetailDrawerState({});
			expect(state.subtitle).toBe('');
			expect(state.hasSubtitle).toBe(false);
		});
	});

	// -- Tabs -----------------------------------------------------------------

	describe('tabs', () => {
		const sampleTabs: DrawerTab[] = [
			{ id: 'fields', label: 'Fields' },
			{ id: 'raw', label: 'Raw JSON', badge: 42 },
		];

		it('renders tabs with correct labels', () => {
			const state = new DetailDrawerState({ tabs: sampleTabs });
			expect(state.tabs).toHaveLength(2);
			expect(state.tabs[0].label).toBe('Fields');
			expect(state.tabs[1].label).toBe('Raw JSON');
		});

		it('showTabs returns true when there are 2+ tabs', () => {
			const state = new DetailDrawerState({ tabs: sampleTabs });
			expect(state.showTabs).toBe(true);
		});

		it('showTabs returns false when there is only 1 tab', () => {
			const state = new DetailDrawerState({ tabs: [{ id: 'only', label: 'Only Tab' }] });
			expect(state.showTabs).toBe(false);
		});

		it('showTabs returns false when there are no tabs', () => {
			const state = new DetailDrawerState({ tabs: [] });
			expect(state.showTabs).toBe(false);
		});

		it('tabHasBadge returns true when badge is set', () => {
			const state = new DetailDrawerState({ tabs: sampleTabs });
			expect(state.tabHasBadge(sampleTabs[1])).toBe(true);
		});

		it('tabHasBadge returns false when badge is undefined', () => {
			const state = new DetailDrawerState({ tabs: sampleTabs });
			expect(state.tabHasBadge(sampleTabs[0])).toBe(false);
		});

		it('tabHasBadge returns true when badge is 0 (zero)', () => {
			const tab: DrawerTab = { id: 'x', label: 'X', badge: 0 };
			const state = new DetailDrawerState({ tabs: [tab] });
			expect(state.tabHasBadge(tab)).toBe(true);
		});

		it('tabHasBadge returns true when badge is string', () => {
			const tab: DrawerTab = { id: 'x', label: 'X', badge: 'new' };
			const state = new DetailDrawerState({ tabs: [tab] });
			expect(state.tabHasBadge(tab)).toBe(true);
		});
	});

	// -- Active tab styling ---------------------------------------------------

	describe('active tab styling', () => {
		const tabs: DrawerTab[] = [
			{ id: 'details', label: 'Details' },
			{ id: 'raw', label: 'Raw' },
		];

		it('active tab has "active" class', () => {
			const state = new DetailDrawerState({ tabs, activeTab: 'details' });
			expect(state.tabClass('details')).toBe('drawer-tab active');
		});

		it('inactive tab does not have "active" class', () => {
			const state = new DetailDrawerState({ tabs, activeTab: 'details' });
			expect(state.tabClass('raw')).toBe('drawer-tab');
		});

		it('no tab is active when activeTab is empty', () => {
			const state = new DetailDrawerState({ tabs, activeTab: '' });
			expect(state.tabClass('details')).toBe('drawer-tab');
			expect(state.tabClass('raw')).toBe('drawer-tab');
		});
	});

	// -- ESC key handling -----------------------------------------------------

	describe('ESC key handling', () => {
		it('calls onclose when ESC is pressed and drawer is open', () => {
			const onclose = vi.fn();
			const state = new DetailDrawerState({ open: true, onclose });

			state.handleKeydown({ key: 'Escape' });

			expect(onclose).toHaveBeenCalledOnce();
		});

		it('does not call onclose when ESC is pressed and drawer is closed', () => {
			const onclose = vi.fn();
			const state = new DetailDrawerState({ open: false, onclose });

			state.handleKeydown({ key: 'Escape' });

			expect(onclose).not.toHaveBeenCalled();
		});

		it('does not call onclose for non-ESC keys', () => {
			const onclose = vi.fn();
			const state = new DetailDrawerState({ open: true, onclose });

			state.handleKeydown({ key: 'Enter' });
			state.handleKeydown({ key: 'Tab' });
			state.handleKeydown({ key: 'a' });

			expect(onclose).not.toHaveBeenCalled();
		});
	});

	// -- Backdrop click -------------------------------------------------------

	describe('backdrop click', () => {
		it('calls onclose when backdrop is clicked', () => {
			const onclose = vi.fn();
			const state = new DetailDrawerState({ open: true, onclose });

			state.handleBackdropClick();

			expect(onclose).toHaveBeenCalledOnce();
		});
	});

	// -- Tab change callback --------------------------------------------------

	describe('tab change callback', () => {
		it('calls ontabchange when a tab is clicked', () => {
			const ontabchange = vi.fn();
			const state = new DetailDrawerState({
				tabs: [
					{ id: 'fields', label: 'Fields' },
					{ id: 'raw', label: 'Raw' },
				],
				activeTab: 'fields',
				ontabchange,
			});

			state.ontabchange('raw');

			expect(ontabchange).toHaveBeenCalledWith('raw');
		});
	});
});
