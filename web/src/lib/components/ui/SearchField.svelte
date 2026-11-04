<!--
  SearchField.svelte: the pill search input (nettap-design-system/components/SearchField).
  Any other input attribute (oninput, onkeydown, role="combobox", aria-expanded,
  aria-controls, aria-activedescendant, autocomplete, …) passes through to the <input>.
-->
<script lang="ts">
	import type { HTMLInputAttributes } from 'svelte/elements';
	import Icon from './Icon.svelte';

	interface Props extends Omit<HTMLInputAttributes, 'id' | 'value' | 'size' | 'type'> {
		/** Stable id on the input. */
		id: string;
		/** Visually hidden name: "Search", "Filter connections". */
		label: string;
		placeholder?: string;
		value?: string;
		/** top: the 40 px top-bar field; toolbar: the 36 px table-toolbar field. */
		size?: 'top' | 'toolbar';
		/** Keyboard shortcut hint, such as "⌘K". */
		kbdHint?: string;
	}

	let { id, label, placeholder, value = $bindable(''), size = 'top', kbdHint, ...rest }: Props = $props();
</script>

<label class={['search', size === 'toolbar' && 'is-toolbar']}>
	<Icon name="search" />
	<span class="sr-only">{label}</span>
	<input type="search" {id} {placeholder} bind:value {...rest} />
	{#if kbdHint}<kbd aria-hidden="true">{kbdHint}</kbd>{/if}
</label>

<style>
	/* The toolbar size outside a .toolbar: the same values as bundle.css:327 (.toolbar .search) */
	.search.is-toolbar { height: 36px; flex: 1 1 220px; max-width: 360px; }
</style>
