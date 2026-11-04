<!--
  ThemePicker.svelte: chooses the colour variant (Ember, Graphite, Spectrum).
  Applies at once and is remembered in this browser. Protocol: src/lib/stores/theme.ts.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { theme, setTheme, type ThemeVariant } from '$lib/stores/theme';

	const OPTIONS: { value: ThemeVariant; label: string; hint: string }[] = [
		{ value: 'ember', label: 'Ember', hint: 'Warm black, amber accent (default)' },
		{ value: 'graphite', label: 'Graphite', hint: 'Monochrome' },
		{ value: 'spectrum', label: 'Spectrum', hint: 'Violet accent, multi-colour charts' },
	];

	// Ember during SSR and hydration, so server and client markup match.
	// The saved choice is adopted after mount.
	let selected = $state<ThemeVariant>('ember');
	onMount(() => theme.subscribe((v) => (selected = v)));
</script>

<fieldset class="theme-picker">
	<legend class="label">Theme</legend>
	<div class="options">
		{#each OPTIONS as opt (opt.value)}
			<label class="option" class:active={selected === opt.value}>
				<input
					type="radio"
					name="theme"
					value={opt.value}
					aria-label={opt.label}
					aria-describedby="theme-hint-{opt.value}"
					checked={selected === opt.value}
					onchange={() => setTheme(opt.value)}
				/>
				<span class="swatch" data-theme-preview={opt.value} aria-hidden="true">
					<span class="swatch-accent"></span>
				</span>
				<span class="text">
					<span class="name">{opt.label}</span>
					<span class="hint" id="theme-hint-{opt.value}">{opt.hint}</span>
				</span>
			</label>
		{/each}
	</div>
	<p class="field-help">Applies straight away and is remembered in this browser.</p>
</fieldset>

<style>
	.theme-picker {
		border: none;
		margin-bottom: var(--space-lg);
	}

	.options {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-sm);
		margin-top: var(--space-sm);
	}

	.option {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-sm) var(--space-md);
		border: 1px solid var(--line);
		border-radius: var(--r-md);
		background: var(--surface-1);
		color: var(--text-2);
		cursor: pointer;
		transition: border-color var(--transition-fast);
	}

	.option:hover {
		border-color: var(--line-strong);
	}

	.option.active {
		border-color: var(--accent);
		color: var(--text-1);
	}

	.option:has(input:focus-visible) {
		outline: 2px solid var(--focus);
		outline-offset: 2px;
	}

	input {
		position: absolute;
		opacity: 0;
		pointer-events: none;
	}

	/* data-theme-preview gives the swatch that variant's own tokens (see global.css) */
	.swatch {
		display: grid;
		place-items: center;
		width: var(--space-xl);
		height: var(--space-xl);
		border-radius: var(--r-sm);
		background: var(--surface-2);
		border: 1px solid var(--line-strong);
	}

	.swatch-accent {
		width: var(--space-md);
		height: var(--space-md);
		border-radius: var(--r-pill);
		background: var(--accent);
	}

	.text {
		display: flex;
		flex-direction: column;
	}

	.name {
		font-weight: 600;
		font-size: var(--text-sm);
	}

	.hint {
		font-size: var(--text-xs);
		color: var(--text-3);
	}
</style>
