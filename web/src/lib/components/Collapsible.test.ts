import { describe, it, expect } from 'vitest';

/**
 * Tests for Collapsible component logic.
 *
 * The Collapsible.svelte component uses Svelte 5 runes ($state, $props)
 * and Snippet children that are difficult to fully render in a jsdom test
 * environment.  Instead we extract and test the pure logic that lives inside
 * the component: toggle state management, initial expanded/collapsed state,
 * prop defaults, and badge/subtitle conditional rendering logic.
 */

// ---------------------------------------------------------------------------
// Reproduced state logic from Collapsible.svelte
// ---------------------------------------------------------------------------

/** Simulates the toggle logic from the Collapsible component */
class CollapsibleState {
	isExpanded: boolean;
	title: string;
	subtitle: string;
	badge: string;

	constructor(opts: {
		title: string;
		subtitle?: string;
		expanded?: boolean;
		badge?: string;
	}) {
		this.title = opts.title;
		this.subtitle = opts.subtitle ?? '';
		this.isExpanded = opts.expanded ?? false;
		this.badge = opts.badge ?? '';
	}

	toggle() {
		this.isExpanded = !this.isExpanded;
	}

	/** Whether the subtitle slot should render */
	get hasSubtitle(): boolean {
		return this.subtitle.length > 0;
	}

	/** Whether the badge should render */
	get hasBadge(): boolean {
		return this.badge.length > 0;
	}

	/** CSS class for the expanded body — mirrors class:collapsible-body-expanded */
	get bodyClass(): string {
		return this.isExpanded ? 'collapsible-body-expanded' : '';
	}

	/** CSS class for the container — mirrors class:collapsible-expanded */
	get containerClass(): string {
		return this.isExpanded ? 'collapsible-expanded' : '';
	}

	/** Chevron CSS class — mirrors class:chevron-expanded */
	get chevronClass(): string {
		return this.isExpanded ? 'chevron-expanded' : '';
	}

	/** aria-expanded attribute value */
	get ariaExpanded(): boolean {
		return this.isExpanded;
	}
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Collapsible logic', () => {
	// -- Initial state --------------------------------------------------------

	describe('initial state', () => {
		it('defaults to collapsed when expanded prop is not provided', () => {
			const state = new CollapsibleState({ title: 'Test' });
			expect(state.isExpanded).toBe(false);
		});

		it('starts expanded when expanded prop is true', () => {
			const state = new CollapsibleState({ title: 'Test', expanded: true });
			expect(state.isExpanded).toBe(true);
		});

		it('starts collapsed when expanded prop is explicitly false', () => {
			const state = new CollapsibleState({ title: 'Test', expanded: false });
			expect(state.isExpanded).toBe(false);
		});

		it('stores the title correctly', () => {
			const state = new CollapsibleState({ title: 'My Section' });
			expect(state.title).toBe('My Section');
		});

		it('defaults subtitle to empty string', () => {
			const state = new CollapsibleState({ title: 'Test' });
			expect(state.subtitle).toBe('');
		});

		it('defaults badge to empty string', () => {
			const state = new CollapsibleState({ title: 'Test' });
			expect(state.badge).toBe('');
		});
	});

	// -- Toggle behavior ------------------------------------------------------

	describe('toggle', () => {
		it('expands a collapsed section', () => {
			const state = new CollapsibleState({ title: 'Test' });
			expect(state.isExpanded).toBe(false);
			state.toggle();
			expect(state.isExpanded).toBe(true);
		});

		it('collapses an expanded section', () => {
			const state = new CollapsibleState({ title: 'Test', expanded: true });
			expect(state.isExpanded).toBe(true);
			state.toggle();
			expect(state.isExpanded).toBe(false);
		});

		it('toggles back and forth correctly', () => {
			const state = new CollapsibleState({ title: 'Test' });
			state.toggle(); // open
			expect(state.isExpanded).toBe(true);
			state.toggle(); // close
			expect(state.isExpanded).toBe(false);
			state.toggle(); // open again
			expect(state.isExpanded).toBe(true);
		});
	});

	// -- Conditional rendering helpers ----------------------------------------

	describe('hasSubtitle', () => {
		it('returns false when subtitle is empty', () => {
			const state = new CollapsibleState({ title: 'Test' });
			expect(state.hasSubtitle).toBe(false);
		});

		it('returns true when subtitle is provided', () => {
			const state = new CollapsibleState({ title: 'Test', subtitle: 'Details' });
			expect(state.hasSubtitle).toBe(true);
		});
	});

	describe('hasBadge', () => {
		it('returns false when badge is empty', () => {
			const state = new CollapsibleState({ title: 'Test' });
			expect(state.hasBadge).toBe(false);
		});

		it('returns true when badge is provided', () => {
			const state = new CollapsibleState({ title: 'Test', badge: '5' });
			expect(state.hasBadge).toBe(true);
		});
	});

	// -- CSS class derivation -------------------------------------------------

	describe('CSS class derivation', () => {
		it('bodyClass is empty when collapsed', () => {
			const state = new CollapsibleState({ title: 'Test' });
			expect(state.bodyClass).toBe('');
		});

		it('bodyClass is "collapsible-body-expanded" when expanded', () => {
			const state = new CollapsibleState({ title: 'Test', expanded: true });
			expect(state.bodyClass).toBe('collapsible-body-expanded');
		});

		it('containerClass is empty when collapsed', () => {
			const state = new CollapsibleState({ title: 'Test' });
			expect(state.containerClass).toBe('');
		});

		it('containerClass is "collapsible-expanded" when expanded', () => {
			const state = new CollapsibleState({ title: 'Test', expanded: true });
			expect(state.containerClass).toBe('collapsible-expanded');
		});

		it('chevronClass is empty when collapsed', () => {
			const state = new CollapsibleState({ title: 'Test' });
			expect(state.chevronClass).toBe('');
		});

		it('chevronClass is "chevron-expanded" when expanded', () => {
			const state = new CollapsibleState({ title: 'Test', expanded: true });
			expect(state.chevronClass).toBe('chevron-expanded');
		});

		it('CSS classes update after toggle', () => {
			const state = new CollapsibleState({ title: 'Test' });
			expect(state.bodyClass).toBe('');
			state.toggle();
			expect(state.bodyClass).toBe('collapsible-body-expanded');
			expect(state.containerClass).toBe('collapsible-expanded');
			expect(state.chevronClass).toBe('chevron-expanded');
		});
	});

	// -- aria-expanded --------------------------------------------------------

	describe('ariaExpanded', () => {
		it('returns false when collapsed', () => {
			const state = new CollapsibleState({ title: 'Test' });
			expect(state.ariaExpanded).toBe(false);
		});

		it('returns true when expanded', () => {
			const state = new CollapsibleState({ title: 'Test', expanded: true });
			expect(state.ariaExpanded).toBe(true);
		});

		it('updates after toggle', () => {
			const state = new CollapsibleState({ title: 'Test' });
			state.toggle();
			expect(state.ariaExpanded).toBe(true);
			state.toggle();
			expect(state.ariaExpanded).toBe(false);
		});
	});
});
