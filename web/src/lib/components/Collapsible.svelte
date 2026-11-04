<script lang="ts">
	import type { Snippet } from 'svelte';

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
			<svg
				class="collapsible-chevron"
				class:chevron-expanded={isExpanded}
				viewBox="0 0 24 24"
				width="16"
				height="16"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
			>
				<polyline points="9 18 15 12 9 6" />
			</svg>
			<div class="collapsible-title-group">
				<span class="collapsible-title">{title}</span>
				{#if subtitle}
					<span class="collapsible-subtitle">{subtitle}</span>
				{/if}
			</div>
		</div>
		<div class="collapsible-header-right">
			{#if badge}
				<span class="badge">{badge}</span>
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
		background-color: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--r-lg);
		overflow: hidden;
		transition: border-color var(--dur-fast);
	}

	.collapsible:hover {
		border-color: var(--accent);
	}

	.collapsible-expanded {
		border-color: var(--accent);
	}

	.collapsible-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: var(--sp-4) var(--sp-6);
		background: none;
		border: none;
		cursor: pointer;
		font-family: var(--font-body);
		text-align: left;
		color: var(--text-1);
		transition: background-color var(--dur-fast);
	}

	.collapsible-header:hover {
		background-color: var(--surface-2);
	}

	.collapsible-header-left {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		min-width: 0;
	}

	.collapsible-header-right {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		flex-shrink: 0;
	}

	.collapsible-chevron {
		flex-shrink: 0;
		color: var(--text-3);
		transition: transform 250ms var(--ease);
	}

	.chevron-expanded {
		transform: rotate(90deg);
	}

	.collapsible-title-group {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.collapsible-title {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-1);
	}

	.collapsible-subtitle {
		font-size: var(--text-xs);
		color: var(--text-2);
	}

	.collapsible-body {
		max-height: 0;
		overflow: hidden;
		transition: max-height 0.3s ease;
	}

	.collapsible-body-expanded {
		max-height: 2000px;
	}

	.collapsible-body-inner {
		padding: 0 var(--sp-6) var(--sp-6) var(--sp-6);
		border-top: 1px solid var(--line);
	}
</style>
