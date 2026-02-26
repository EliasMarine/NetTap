<!--
  ContextMenu.svelte — Floating right-click context menu.

  Appears at mouse coordinates, adjusts to stay within the viewport,
  and closes on click-outside, Escape, or scroll.
-->
<script lang="ts">
	import { onMount } from 'svelte';

	// ---------------------------------------------------------------------------
	// Types
	// ---------------------------------------------------------------------------

	export interface ContextMenuItem {
		label: string;
		icon?: string; // 'search' | 'device' | 'geoip' | 'copy' | 'external'
		action: () => void;
		separator?: boolean;
	}

	// ---------------------------------------------------------------------------
	// Props
	// ---------------------------------------------------------------------------

	let {
		items = [],
		x = 0,
		y = 0,
		visible = false,
		onclose = () => {},
	}: {
		items: ContextMenuItem[];
		x: number;
		y: number;
		visible: boolean;
		onclose: () => void;
	} = $props();

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let menuEl: HTMLDivElement | undefined = $state(undefined);
	let adjustedX = $state(0);
	let adjustedY = $state(0);

	// ---------------------------------------------------------------------------
	// Viewport adjustment — keep the menu fully visible
	// ---------------------------------------------------------------------------

	$effect(() => {
		if (!visible || !menuEl) {
			adjustedX = x;
			adjustedY = y;
			return;
		}

		const rect = menuEl.getBoundingClientRect();
		const pad = 8;

		let newX = x;
		let newY = y;

		// Adjust horizontally
		if (newX + rect.width + pad > window.innerWidth) {
			newX = window.innerWidth - rect.width - pad;
		}
		if (newX < pad) {
			newX = pad;
		}

		// Adjust vertically
		if (newY + rect.height + pad > window.innerHeight) {
			newY = window.innerHeight - rect.height - pad;
		}
		if (newY < pad) {
			newY = pad;
		}

		adjustedX = newX;
		adjustedY = newY;
	});

	// ---------------------------------------------------------------------------
	// Global listeners — close on outside click, Escape, scroll
	// ---------------------------------------------------------------------------

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape' && visible) {
			e.preventDefault();
			onclose();
		}
	}

	function handleClickOutside(e: MouseEvent) {
		if (!visible) return;
		if (menuEl && !menuEl.contains(e.target as Node)) {
			onclose();
		}
	}

	function handleScroll() {
		if (visible) {
			onclose();
		}
	}

	onMount(() => {
		document.addEventListener('keydown', handleKeydown, true);
		document.addEventListener('click', handleClickOutside, true);
		document.addEventListener('scroll', handleScroll, true);

		return () => {
			document.removeEventListener('keydown', handleKeydown, true);
			document.removeEventListener('click', handleClickOutside, true);
			document.removeEventListener('scroll', handleScroll, true);
		};
	});

	// ---------------------------------------------------------------------------
	// Icon rendering helper
	// ---------------------------------------------------------------------------

	function iconPath(icon: string | undefined): string {
		switch (icon) {
			case 'search':
				return 'M11 17.25a6.25 6.25 0 110-12.5 6.25 6.25 0 010 12.5zM16 16l4.5 4.5';
			case 'device':
				return 'M2 3h20v14H2zM8 21h8M12 17v4';
			case 'geoip':
				return 'M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zM2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10A15.3 15.3 0 0112 2z';
			case 'copy':
				return 'M8 4H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2v-2M16 4h2a2 2 0 012 2v4M8 4a2 2 0 012-2h4a2 2 0 012 2v0a2 2 0 01-2 2h-4a2 2 0 01-2-2z';
			case 'external':
				return 'M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L20.5 3.5';
			default:
				// Generic circle dot
				return 'M12 12m-1 0a1 1 0 102 0 1 1 0 10-2 0';
		}
	}

	// ---------------------------------------------------------------------------
	// Item click handler
	// ---------------------------------------------------------------------------

	function handleItemClick(item: ContextMenuItem) {
		item.action();
		onclose();
	}
</script>

{#if visible}
	<div
		class="context-menu"
		bind:this={menuEl}
		style="left: {adjustedX}px; top: {adjustedY}px;"
		role="menu"
		tabindex="-1"
	>
		{#each items as item, i}
			{#if item.separator && i > 0}
				<div class="context-menu-separator" role="separator"></div>
			{/if}
			<button
				class="context-menu-item"
				role="menuitem"
				onclick={() => handleItemClick(item)}
			>
				<svg
					class="context-menu-icon"
					viewBox="0 0 24 24"
					width="14"
					height="14"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
				>
					<path d={iconPath(item.icon)} />
				</svg>
				<span class="context-menu-label">{item.label}</span>
			</button>
		{/each}
	</div>
{/if}

<style>
	.context-menu {
		position: fixed;
		z-index: 9999;
		min-width: 200px;
		max-width: 320px;
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-lg);
		padding: var(--space-xs);
		animation: contextMenuFadeIn 120ms ease-out;
	}

	@keyframes contextMenuFadeIn {
		from {
			opacity: 0;
			transform: scale(0.96);
		}
		to {
			opacity: 1;
			transform: scale(1);
		}
	}

	.context-menu-item {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		width: 100%;
		padding: var(--space-sm) var(--space-md);
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-primary);
		background: none;
		border: none;
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition: background-color var(--transition-fast);
		text-align: left;
		white-space: nowrap;
	}

	.context-menu-item:hover {
		background-color: var(--accent-muted);
		color: var(--accent);
	}

	.context-menu-icon {
		flex-shrink: 0;
		opacity: 0.7;
	}

	.context-menu-item:hover .context-menu-icon {
		opacity: 1;
	}

	.context-menu-label {
		flex: 1;
	}

	.context-menu-separator {
		height: 1px;
		background-color: var(--border-default);
		margin: var(--space-xs) var(--space-sm);
	}
</style>
