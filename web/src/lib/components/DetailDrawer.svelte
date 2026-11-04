<!--
  DetailDrawer.svelte — Unified slide-out side panel (UniFi-style).
  Shared across all pages. 480px wide, slides from right with backdrop.
  Renders configurable tabs, scrollable content area, and footer actions.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

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
				<h3 class="drawer-title">{title}</h3>
				{#if subtitle}
					<p class="drawer-subtitle mono">{subtitle}</p>
				{/if}
			</div>
			<button class="drawer-close-btn" onclick={onclose} aria-label="Close panel">
				<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
				</svg>
			</button>
		</div>

		<!-- Tab bar -->
		{#if tabs.length > 1}
			<div class="drawer-tabs">
				{#each tabs as tab}
					<button
						class="drawer-tab"
						class:active={activeTab === tab.id}
						onclick={() => ontabchange(tab.id)}
					>
						{tab.label}
						{#if tab.badge != null}
							<span class="tab-badge">{tab.badge}</span>
						{/if}
					</button>
				{/each}
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

	/* ----- Panel ----- */
	.detail-drawer {
		position: fixed;
		top: 0;
		right: 0;
		bottom: 0;
		width: 480px;
		max-width: 100vw;
		z-index: 999;
		background-color: var(--bg);
		border-left: 1px solid var(--line);
		display: flex;
		flex-direction: column;
		transform: translateX(100%);
		transition: transform 250ms var(--ease);
		box-shadow: -4px 0 24px color-mix(in srgb, var(--bg) 40%, transparent);
	}

	.detail-drawer.open {
		transform: translateX(0);
	}

	/* ----- Header ----- */
	.drawer-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		padding: var(--sp-4) var(--sp-6);
		border-bottom: 1px solid var(--line);
		background-color: var(--surface-1);
		flex-shrink: 0;
		gap: var(--sp-2);
	}

	.drawer-header-text {
		flex: 1;
		min-width: 0;
	}

	.drawer-title {
		font-size: var(--text-lg);
		font-weight: 700;
		color: var(--text-1);
		line-height: 1.3;
		word-break: break-word;
	}

	.drawer-subtitle {
		font-size: var(--text-xs);
		color: var(--text-3);
		margin-top: 2px;
	}

	.drawer-close-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		background: none;
		border: none;
		border-radius: var(--r-sm);
		color: var(--text-2);
		cursor: pointer;
		transition: all var(--dur-fast);
		flex-shrink: 0;
	}

	.drawer-close-btn:hover {
		background-color: var(--surface-2);
		color: var(--text-1);
	}

	/* ----- Tabs ----- */
	.drawer-tabs {
		display: flex;
		border-bottom: 1px solid var(--line);
		background-color: var(--surface-1);
		flex-shrink: 0;
		padding: 0 var(--sp-6);
		gap: 0;
	}

	.drawer-tab {
		position: relative;
		padding: var(--sp-2) var(--sp-4);
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-3);
		background: none;
		border: none;
		cursor: pointer;
		transition: color var(--dur-fast);
		white-space: nowrap;
		display: flex;
		align-items: center;
		gap: var(--sp-1);
	}

	.drawer-tab:hover {
		color: var(--text-1);
	}

	.drawer-tab.active {
		color: var(--accent);
	}

	.drawer-tab.active::after {
		content: '';
		position: absolute;
		bottom: -1px;
		left: var(--sp-4);
		right: var(--sp-4);
		height: 2px;
		background-color: var(--accent);
		border-radius: 1px;
	}

	.tab-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 18px;
		height: 18px;
		padding: 0 5px;
		font-size: 10px;
		font-weight: 600;
		border-radius: var(--r-pill);
		background-color: var(--surface-2);
		color: var(--text-2);
	}

	.drawer-tab.active .tab-badge {
		background-color: color-mix(in srgb, var(--accent) 12%, transparent);
		color: var(--accent);
	}

	/* ----- Body ----- */
	.drawer-body {
		flex: 1;
		overflow-y: auto;
		padding: var(--sp-6);
	}

	/* ----- Footer ----- */
	.drawer-footer {
		padding: var(--sp-4) var(--sp-6);
		border-top: 1px solid var(--line);
		background-color: var(--surface-1);
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
