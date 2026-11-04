<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from '$lib/components/ui/Icon.svelte';

	let {
		title = '',
		subtitle = '',
		expanded = false,
		badge = '',
		children,
	}: {
		title: string;
		subtitle?: string;
		expanded?: boolean;
		badge?: string;
		children: Snippet;
	} = $props();

	let isExpanded = $state(false);

	$effect(() => {
		isExpanded = expanded;
	});

	function toggle() {
		isExpanded = !isExpanded;
	}
</script>

<div class="collapsible" class:collapsible-expanded={isExpanded}>
	<button class="collapsible-header" onclick={toggle} aria-expanded={isExpanded}>
		<div class="collapsible-header-left">
			<span class="collapsible-chevron" class:chevron-expanded={isExpanded}><Icon name="chevdown" /></span>
			<div class="collapsible-title-group">
				<span class="collapsible-title">{title}</span>
				{#if subtitle}
					<span class="collapsible-subtitle">{subtitle}</span>
				{/if}
			</div>
		</div>
		<div class="collapsible-header-right">
			{#if badge}
				<span class="chip">{badge}</span>
			{/if}
		</div>
	</button>

	<div class="collapsible-body" class:collapsible-body-expanded={isExpanded}>
		<div class="collapsible-body-inner">
			{@render children()}
		</div>
	</div>
</div>

<style>
	.collapsible {
		background: var(--card-bg);
		border: 1px solid var(--line);
		border-radius: var(--r-lg);
		box-shadow: var(--sheen);
		overflow: hidden;
	}

	.collapsible-expanded {
		border-color: var(--line-strong);
	}

	.collapsible-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--sp-3);
		width: 100%;
		padding: var(--sp-4) var(--sp-5);
		background: none;
		border: none;
		cursor: pointer;
		text-align: left;
		color: var(--text-1);
		transition: background-color var(--dur-fast);
	}

	.collapsible-header:hover {
		background-color: var(--row-hover);
	}

	.collapsible-header-left {
		display: flex;
		align-items: center;
		gap: var(--sp-3);
		min-width: 0;
	}

	.collapsible-header-right {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		flex-shrink: 0;
	}

	/* The chevron points right when collapsed and down when open. */
	.collapsible-chevron {
		display: inline-flex;
		flex-shrink: 0;
		color: var(--text-3);
		transform: rotate(-90deg);
		transition: transform var(--dur-fast) var(--ease);
	}

	.chevron-expanded {
		transform: rotate(0deg);
	}

	.collapsible-title-group {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.collapsible-title {
		font: 500 var(--text-md)/1.3 var(--font-display);
		letter-spacing: -0.01em;
	}

	.collapsible-subtitle {
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.collapsible-body {
		max-height: 0;
		overflow: hidden;
		transition: max-height 0.3s var(--ease);
	}

	.collapsible-body-expanded {
		max-height: 2000px;
	}

	.collapsible-body-inner {
		padding: var(--sp-4) var(--sp-5) var(--sp-5);
		border-top: 1px solid var(--line);
	}
</style>
