<!--
  DetailDrawer.svelte — Unified slide-out side panel, styled as the system's AlertDrawer card.
  Shared across all pages. 480px wide, slides from right with backdrop.
  Renders configurable tabs (system pills), scrollable content area, and footer actions.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from '$lib/components/ui/Icon.svelte';

	export interface DrawerTab {
		id: string;
		label: string;
		badge?: string | number;
	}

	let {
		open = false,
		title = '',
		subtitle = '',
		tabs = [],
		activeTab = '',
		onclose = () => {},
		ontabchange = (_tabId: string) => {},
		children,
		actions,
	}: {
		open: boolean;
		title: string;
		subtitle?: string;
		tabs: DrawerTab[];
		activeTab: string;
		onclose: () => void;
		ontabchange: (tabId: string) => void;
		children: Snippet;
		actions?: Snippet;
	} = $props();

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape' && open) {
			onclose();
		}
	}

	function handleBackdropClick() {
		onclose();
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- Backdrop -->
{#if open}
	<button
		class="drawer-backdrop"
		onclick={handleBackdropClick}
		aria-label="Close detail panel"
		tabindex="-1"
	></button>
{/if}

<!-- Panel -->
<aside class="detail-drawer" class:open aria-label="Detail panel">
	{#if open}
		<!-- Header -->
		<div class="drawer-header">
			<div class="drawer-header-text">
				<h3 class="drawer-title type-drawer-title">{title}</h3>
				{#if subtitle}
					<p class="drawer-subtitle mono">{subtitle}</p>
				{/if}
			</div>
			<button class="icon-btn" type="button" onclick={onclose} aria-label="Close panel">
				<Icon name="close" />
			</button>
		</div>

		<!-- Tab bar -->
		{#if tabs.length > 1}
			<div class="drawer-tabs">
				<div class="pills">
					{#each tabs as tab}
						<button
							class="pill"
							type="button"
							aria-pressed={activeTab === tab.id}
							onclick={() => ontabchange(tab.id)}
						>
							{tab.label}
							{#if tab.badge != null}
								<span class="tab-badge num">{tab.badge}</span>
							{/if}
						</button>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Scrollable content -->
		<div class="drawer-body">
			{@render children()}
		</div>

		<!-- Footer actions -->
		{#if actions}
			<div class="drawer-footer">
				{@render actions()}
			</div>
		{/if}
	{/if}
</aside>

<style>
	/* ----- Backdrop ----- */
	.drawer-backdrop {
		position: fixed;
		inset: 0;
		z-index: 998;
		background-color: var(--scrim);
		border: none;
		cursor: pointer;
		animation: backdropFadeIn 200ms ease-out;
	}

	@keyframes backdropFadeIn {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	/* ----- Panel: a surface-1 card docked to the right edge ----- */
	.detail-drawer {
		position: fixed;
		top: 0;
		right: 0;
		bottom: 0;
		width: 480px;
		max-width: 100vw;
		z-index: 999;
		background: var(--surface-1);
		border-left: 1px solid var(--line);
		box-shadow: var(--sheen), var(--shadow-pop);
		display: flex;
		flex-direction: column;
		transform: translateX(100%);
		transition: transform 250ms var(--ease);
	}

	.detail-drawer.open {
		transform: translateX(0);
	}

	/* ----- Header ----- */
	.drawer-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--sp-3);
		padding: var(--sp-5) var(--sp-5) var(--sp-4);
		flex-shrink: 0;
	}

	.drawer-header-text {
		flex: 1;
		min-width: 0;
	}

	.drawer-title {
		color: var(--text-1);
		overflow-wrap: anywhere;
	}

	.drawer-subtitle {
		margin-top: var(--sp-1);
		font-size: var(--text-xs);
		color: var(--text-3);
		overflow-wrap: anywhere;
	}

	/* ----- Tabs (system pills) ----- */
	.drawer-tabs {
		padding: 0 var(--sp-5) var(--sp-4);
		flex-shrink: 0;
		overflow-x: auto;
	}

	.tab-badge {
		display: inline-grid;
		place-items: center;
		min-width: 18px;
		height: 18px;
		margin-left: var(--sp-1);
		padding: 0 5px;
		border-radius: var(--r-pill);
		font-size: var(--text-micro);
		font-weight: 700;
		background: var(--surface-3);
		color: var(--text-2);
	}

	.pill[aria-pressed='true'] .tab-badge {
		background: color-mix(in srgb, var(--on-light) 12%, transparent);
		color: var(--on-light);
	}

	/* ----- Body ----- */
	.drawer-body {
		flex: 1;
		overflow-y: auto;
		padding: var(--sp-5);
		border-top: 1px solid var(--line);
	}

	/* ----- Footer ----- */
	.drawer-footer {
		padding: var(--sp-4) var(--sp-5);
		border-top: 1px solid var(--line);
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}

	/* ----- Responsive ----- */
	@media (max-width: 640px) {
		.detail-drawer {
			width: 100vw;
		}
	}
</style>
