<!--
  DrawerSection.svelte — UniFi-style collapsible section for the detail drawer.
  Click the header to collapse/expand the content.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

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
	<button class="section-header" onclick={() => isOpen = !isOpen}>
		<span class="section-title">{title}</span>
		<svg class="section-chevron" class:rotated={isOpen} viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
			<polyline points="6 4 10 8 6 12" />
		</svg>
	</button>

	{#if isOpen}
		<div class="section-body">
			{@render children()}
		</div>
	{/if}
</div>

<style>
	.drawer-section {
		border-bottom: 1px solid var(--border-dim);
	}

	.drawer-section:last-child {
		border-bottom: none;
	}

	.section-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: var(--space-sm) 0;
		background: none;
		border: none;
		cursor: pointer;
		color: var(--text-secondary);
		transition: color var(--transition-fast);
	}

	.section-header:hover {
		color: var(--text-primary);
	}

	.section-title {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.section-chevron {
		transition: transform var(--transition-fast);
		flex-shrink: 0;
	}

	.section-chevron.rotated {
		transform: rotate(90deg);
	}

	.section-body {
		padding: var(--space-xs) 0 var(--space-md) 0;
	}
</style>
