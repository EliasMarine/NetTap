<!--
  DrawerSection.svelte — Collapsible section for the detail drawer, headed by a system eyebrow.
  Click the header to collapse/expand the content.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from '$lib/components/ui/Icon.svelte';

	let {
		title,
		defaultExpanded = true,
		children,
	}: {
		title: string;
		defaultExpanded?: boolean;
		children: Snippet;
	} = $props();

	let isOpen = $state(defaultExpanded);
</script>

<div class="drawer-section" class:collapsed={!isOpen}>
	<button class="section-header" type="button" onclick={() => isOpen = !isOpen}>
		<span class="section-title eyebrow">{title}</span>
		<span class="section-chevron" class:rotated={isOpen}><Icon name="chevdown" /></span>
	</button>

	{#if isOpen}
		<div class="section-body">
			{@render children()}
		</div>
	{/if}
</div>

<style>
	.drawer-section {
		border-bottom: 1px solid var(--line);
	}

	.drawer-section:last-child {
		border-bottom: none;
	}

	.section-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: var(--sp-3) 0;
		background: none;
		border: none;
		cursor: pointer;
		color: var(--text-3);
		transition: color var(--dur-fast);
	}

	.section-header:hover,
	.section-header:hover .section-title {
		color: var(--text-1);
	}

	.section-chevron {
		display: inline-flex;
		flex-shrink: 0;
		transform: rotate(-90deg);
		transition: transform var(--dur-fast);
	}

	.section-chevron :global(.ic) {
		width: 14px;
		height: 14px;
	}

	.section-chevron.rotated {
		transform: none;
	}

	.section-body {
		padding: var(--sp-1) 0 var(--sp-4) 0;
	}
</style>
