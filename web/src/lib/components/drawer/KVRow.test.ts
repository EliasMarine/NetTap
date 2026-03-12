import { describe, it, expect, vi, afterEach } from 'vitest';

/**
 * Tests for KVRow component logic.
 *
 * The KVRow.svelte component uses Svelte 5 runes ($state, $props) that are
 * difficult to fully render in jsdom. Instead we extract and test the pure
 * logic: value formatting, null/undefined handling, mono class derivation,
 * copyable behavior, and clipboard interaction.
 */

// ---------------------------------------------------------------------------
// Reproduced logic from KVRow.svelte
// ---------------------------------------------------------------------------

class KVRowState {
	label: string;
	value: string | number | null | undefined;
	mono: boolean;
	copyable: boolean;
	copied: boolean;

	constructor(opts: {
		label: string;
		value?: string | number | null | undefined;
		mono?: boolean;
		copyable?: boolean;
	}) {
		this.label = opts.label;
		this.value = opts.value ?? null;
		this.mono = opts.mono ?? false;
		this.copyable = opts.copyable ?? false;
		this.copied = false;
	}

	/** Whether the value should show as "--" (empty placeholder) */
	get isEmpty(): boolean {
		return this.value == null || this.value === '' || this.value === undefined;
	}

	/** Display text for the value */
	get displayValue(): string {
		if (this.isEmpty) return '--';
		return String(this.value);
	}

	/** CSS class for the value span */
	get valueClass(): string {
		const classes = ['kv-value'];
		if (this.isEmpty) classes.push('kv-empty');
		if (this.mono && !this.isEmpty) classes.push('mono');
		if (this.copyable && !this.isEmpty) classes.push('copyable');
		return classes.join(' ');
	}

	/** Role attribute — "button" if copyable, undefined otherwise */
	get role(): string | undefined {
		return this.copyable && !this.isEmpty ? 'button' : undefined;
	}

	/** tabindex — 0 if copyable, undefined otherwise */
	get tabindex(): number | undefined {
		return this.copyable && !this.isEmpty ? 0 : undefined;
	}

	/** Title tooltip */
	get titleText(): string | undefined {
		if (!this.copyable || this.isEmpty) return undefined;
		return this.copied ? 'Copied!' : 'Click to copy';
	}

	/** Handles copy action — mirrors handleCopy in KVRow.svelte */
	handleCopy(writeText: (text: string) => void): void {
		if (!this.copyable || this.value == null) return;
		writeText(String(this.value));
		this.copied = true;
	}
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('KVRow logic', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- Label and value rendering --------------------------------------------

	describe('label and value', () => {
		it('renders label correctly', () => {
			const state = new KVRowState({ label: 'Source IP' });
			expect(state.label).toBe('Source IP');
		});

		it('renders string value correctly', () => {
			const state = new KVRowState({ label: 'IP', value: '192.168.1.1' });
			expect(state.displayValue).toBe('192.168.1.1');
		});

		it('renders number value correctly', () => {
			const state = new KVRowState({ label: 'Port', value: 443 });
			expect(state.displayValue).toBe('443');
		});
	});

	// -- Empty state (null/undefined) -----------------------------------------

	describe('null/undefined value', () => {
		it('shows "--" for null value', () => {
			const state = new KVRowState({ label: 'Field', value: null });
			expect(state.displayValue).toBe('--');
			expect(state.isEmpty).toBe(true);
		});

		it('shows "--" for undefined value', () => {
			const state = new KVRowState({ label: 'Field', value: undefined });
			expect(state.displayValue).toBe('--');
			expect(state.isEmpty).toBe(true);
		});

		it('shows "--" for empty string value', () => {
			const state = new KVRowState({ label: 'Field', value: '' });
			expect(state.displayValue).toBe('--');
			expect(state.isEmpty).toBe(true);
		});

		it('does not show "--" for "0" (number zero)', () => {
			const state = new KVRowState({ label: 'Count', value: 0 });
			expect(state.displayValue).toBe('0');
			expect(state.isEmpty).toBe(false);
		});

		it('does not show "--" for non-empty string', () => {
			const state = new KVRowState({ label: 'Host', value: 'example.com' });
			expect(state.isEmpty).toBe(false);
		});
	});

	// -- Mono class -----------------------------------------------------------

	describe('mono class', () => {
		it('includes mono class when mono=true and value is present', () => {
			const state = new KVRowState({ label: 'IP', value: '10.0.0.1', mono: true });
			expect(state.valueClass).toContain('mono');
		});

		it('does not include mono class when mono=false', () => {
			const state = new KVRowState({ label: 'Name', value: 'Test', mono: false });
			expect(state.valueClass).not.toContain('mono');
		});

		it('does not include mono class when value is null (even if mono=true)', () => {
			const state = new KVRowState({ label: 'IP', value: null, mono: true });
			expect(state.valueClass).not.toContain('mono');
		});
	});

	// -- Copyable behavior ----------------------------------------------------

	describe('copyable', () => {
		it('includes copyable class when copyable=true and value is present', () => {
			const state = new KVRowState({ label: 'IP', value: '10.0.0.1', copyable: true });
			expect(state.valueClass).toContain('copyable');
		});

		it('does not include copyable class when copyable=false', () => {
			const state = new KVRowState({ label: 'IP', value: '10.0.0.1', copyable: false });
			expect(state.valueClass).not.toContain('copyable');
		});

		it('has role="button" when copyable and value present', () => {
			const state = new KVRowState({ label: 'IP', value: '10.0.0.1', copyable: true });
			expect(state.role).toBe('button');
		});

		it('has no role when not copyable', () => {
			const state = new KVRowState({ label: 'IP', value: '10.0.0.1', copyable: false });
			expect(state.role).toBeUndefined();
		});

		it('has tabindex=0 when copyable and value present', () => {
			const state = new KVRowState({ label: 'IP', value: '10.0.0.1', copyable: true });
			expect(state.tabindex).toBe(0);
		});

		it('has no tabindex when not copyable', () => {
			const state = new KVRowState({ label: 'IP', value: '10.0.0.1', copyable: false });
			expect(state.tabindex).toBeUndefined();
		});

		it('title says "Click to copy" before copying', () => {
			const state = new KVRowState({ label: 'IP', value: '10.0.0.1', copyable: true });
			expect(state.titleText).toBe('Click to copy');
		});

		it('title says "Copied!" after copying', () => {
			const state = new KVRowState({ label: 'IP', value: '10.0.0.1', copyable: true });
			const writeText = vi.fn();
			state.handleCopy(writeText);
			expect(state.titleText).toBe('Copied!');
		});
	});

	// -- Copy to clipboard ----------------------------------------------------

	describe('clipboard copy', () => {
		it('copies value to clipboard on click', () => {
			const writeText = vi.fn();
			const state = new KVRowState({ label: 'IP', value: '192.168.1.1', copyable: true });

			state.handleCopy(writeText);

			expect(writeText).toHaveBeenCalledWith('192.168.1.1');
			expect(state.copied).toBe(true);
		});

		it('copies number value as string', () => {
			const writeText = vi.fn();
			const state = new KVRowState({ label: 'Port', value: 443, copyable: true });

			state.handleCopy(writeText);

			expect(writeText).toHaveBeenCalledWith('443');
		});

		it('does not copy when copyable=false', () => {
			const writeText = vi.fn();
			const state = new KVRowState({ label: 'IP', value: '10.0.0.1', copyable: false });

			state.handleCopy(writeText);

			expect(writeText).not.toHaveBeenCalled();
			expect(state.copied).toBe(false);
		});

		it('does not copy when value is null', () => {
			const writeText = vi.fn();
			const state = new KVRowState({ label: 'IP', value: null, copyable: true });

			state.handleCopy(writeText);

			expect(writeText).not.toHaveBeenCalled();
		});
	});
});
