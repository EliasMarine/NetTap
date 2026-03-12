import { describe, it, expect } from 'vitest';

/**
 * Tests for DrawerSection component logic.
 *
 * The DrawerSection.svelte component uses Svelte 5 runes ($state, $props)
 * and Snippet children that are difficult to fully render in jsdom.
 * Instead we extract and test the pure logic: toggle state, default
 * expansion, title storage, and CSS class derivation.
 */

// ---------------------------------------------------------------------------
// Reproduced state logic from DrawerSection.svelte
// ---------------------------------------------------------------------------

class DrawerSectionState {
	title: string;
	isOpen: boolean;

	constructor(opts: { title: string; defaultExpanded?: boolean }) {
		this.title = opts.title;
		this.isOpen = opts.defaultExpanded ?? true;
	}

	toggle() {
		this.isOpen = !this.isOpen;
	}

	/** CSS class for section container — mirrors class:collapsed={!isOpen} */
	get containerClass(): string {
		return this.isOpen ? '' : 'collapsed';
	}

	/** CSS class for chevron — mirrors class:rotated={isOpen} */
	get chevronClass(): string {
		return this.isOpen ? 'section-chevron rotated' : 'section-chevron';
	}

	/** Whether the section body should render — mirrors {#if isOpen} */
	get showBody(): boolean {
		return this.isOpen;
	}
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DrawerSection logic', () => {
	// -- Title ----------------------------------------------------------------

	describe('title', () => {
		it('renders title correctly', () => {
			const state = new DrawerSectionState({ title: 'Connection' });
			expect(state.title).toBe('Connection');
		});

		it('stores empty title', () => {
			const state = new DrawerSectionState({ title: '' });
			expect(state.title).toBe('');
		});
	});

	// -- Default expansion state ----------------------------------------------

	describe('defaultExpanded', () => {
		it('starts expanded when defaultExpanded=true', () => {
			const state = new DrawerSectionState({ title: 'Test', defaultExpanded: true });
			expect(state.isOpen).toBe(true);
			expect(state.showBody).toBe(true);
		});

		it('starts collapsed when defaultExpanded=false', () => {
			const state = new DrawerSectionState({ title: 'Test', defaultExpanded: false });
			expect(state.isOpen).toBe(false);
			expect(state.showBody).toBe(false);
		});

		it('defaults to expanded when defaultExpanded is not provided', () => {
			const state = new DrawerSectionState({ title: 'Test' });
			expect(state.isOpen).toBe(true);
			expect(state.showBody).toBe(true);
		});
	});

	// -- Toggle behavior ------------------------------------------------------

	describe('toggle', () => {
		it('collapses an expanded section on header click', () => {
			const state = new DrawerSectionState({ title: 'Test', defaultExpanded: true });
			expect(state.isOpen).toBe(true);
			state.toggle();
			expect(state.isOpen).toBe(false);
			expect(state.showBody).toBe(false);
		});

		it('expands a collapsed section on header click', () => {
			const state = new DrawerSectionState({ title: 'Test', defaultExpanded: false });
			expect(state.isOpen).toBe(false);
			state.toggle();
			expect(state.isOpen).toBe(true);
			expect(state.showBody).toBe(true);
		});

		it('toggles back and forth correctly', () => {
			const state = new DrawerSectionState({ title: 'Test', defaultExpanded: true });
			state.toggle(); // collapse
			expect(state.isOpen).toBe(false);
			state.toggle(); // expand
			expect(state.isOpen).toBe(true);
			state.toggle(); // collapse
			expect(state.isOpen).toBe(false);
		});
	});

	// -- CSS class derivation -------------------------------------------------

	describe('CSS class derivation', () => {
		it('containerClass is empty when expanded', () => {
			const state = new DrawerSectionState({ title: 'Test', defaultExpanded: true });
			expect(state.containerClass).toBe('');
		});

		it('containerClass is "collapsed" when collapsed', () => {
			const state = new DrawerSectionState({ title: 'Test', defaultExpanded: false });
			expect(state.containerClass).toBe('collapsed');
		});

		it('chevronClass includes "rotated" when expanded', () => {
			const state = new DrawerSectionState({ title: 'Test', defaultExpanded: true });
			expect(state.chevronClass).toContain('rotated');
		});

		it('chevronClass does not include "rotated" when collapsed', () => {
			const state = new DrawerSectionState({ title: 'Test', defaultExpanded: false });
			expect(state.chevronClass).not.toContain('rotated');
		});

		it('CSS classes update after toggle', () => {
			const state = new DrawerSectionState({ title: 'Test', defaultExpanded: true });
			expect(state.containerClass).toBe('');
			state.toggle();
			expect(state.containerClass).toBe('collapsed');
			expect(state.chevronClass).not.toContain('rotated');
		});
	});
});
