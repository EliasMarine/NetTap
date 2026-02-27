<!--
  IPAddress.svelte — Clickable IP address with right-click context menu.

  Renders a monospaced IP address that shows a context menu on right-click
  (or long-press on mobile) with options to copy, navigate to device details,
  GeoIP lookup, and filter connections.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import ContextMenu from '$components/ContextMenu.svelte';
	import type { ContextMenuItem } from '$components/ContextMenu.svelte';

	// ---------------------------------------------------------------------------
	// Props
	// ---------------------------------------------------------------------------

	let {
		ip,
		showMenu = true,
	}: {
		ip: string;
		showMenu?: boolean;
	} = $props();

	// ---------------------------------------------------------------------------
	// Context menu state
	// ---------------------------------------------------------------------------

	let menuVisible = $state(false);
	let menuX = $state(0);
	let menuY = $state(0);

	// ---------------------------------------------------------------------------
	// Long-press support for mobile
	// ---------------------------------------------------------------------------

	let longPressTimer: ReturnType<typeof setTimeout> | null = null;

	function handleTouchStart(e: TouchEvent) {
		if (!showMenu) return;
		const touch = e.touches[0];
		longPressTimer = setTimeout(() => {
			e.preventDefault();
			menuX = touch.clientX;
			menuY = touch.clientY;
			menuVisible = true;
		}, 500);
	}

	function handleTouchEnd() {
		if (longPressTimer) {
			clearTimeout(longPressTimer);
			longPressTimer = null;
		}
	}

	function handleTouchMove() {
		if (longPressTimer) {
			clearTimeout(longPressTimer);
			longPressTimer = null;
		}
	}

	// ---------------------------------------------------------------------------
	// Context menu items
	// ---------------------------------------------------------------------------

	let menuItems: ContextMenuItem[] = $derived([
		{
			label: 'Copy IP',
			icon: 'copy',
			action: () => {
				navigator.clipboard.writeText(ip).catch(() => {
					// Fallback: create a temporary textarea
					const ta = document.createElement('textarea');
					ta.value = ip;
					ta.style.position = 'fixed';
					ta.style.opacity = '0';
					document.body.appendChild(ta);
					ta.select();
					document.execCommand('copy');
					document.body.removeChild(ta);
				});
			},
		},
		{
			label: 'View device details',
			icon: 'device',
			separator: true,
			action: () => {
				goto(`/devices/${encodeURIComponent(ip)}`);
			},
		},
		{
			label: 'GeoIP lookup',
			icon: 'geoip',
			action: () => {
				// Open GeoIP lookup in a new tab (using an external service as fallback)
				window.open(`https://ipinfo.io/${encodeURIComponent(ip)}`, '_blank', 'noopener');
			},
		},
		{
			label: 'Filter connections from this IP',
			icon: 'search',
			separator: true,
			action: () => {
				goto(`/connections?filter=ip.src==${encodeURIComponent(ip)}`);
			},
		},
		{
			label: 'Filter connections to this IP',
			icon: 'search',
			action: () => {
				goto(`/connections?filter=ip.dst==${encodeURIComponent(ip)}`);
			},
		},
	]);

	// ---------------------------------------------------------------------------
	// Event handlers
	// ---------------------------------------------------------------------------

	function handleContextMenu(e: MouseEvent) {
		if (!showMenu) return;
		e.preventDefault();
		e.stopPropagation();
		menuX = e.clientX;
		menuY = e.clientY;
		menuVisible = true;
	}

	function closeMenu() {
		menuVisible = false;
	}
</script>

<span
	class="ip-address mono"
	role="button"
	tabindex="0"
	oncontextmenu={handleContextMenu}
	ontouchstart={handleTouchStart}
	ontouchend={handleTouchEnd}
	ontouchmove={handleTouchMove}
	title="Right-click for options"
>
	{ip}
</span>

<ContextMenu
	items={menuItems}
	x={menuX}
	y={menuY}
	visible={menuVisible}
	onclose={closeMenu}
/>

<style>
	.ip-address {
		color: var(--accent);
		font-size: var(--text-sm);
		cursor: context-menu;
		user-select: text;
		border-bottom: 1px dashed var(--border-default);
		transition: border-color var(--transition-fast), color var(--transition-fast);
		display: inline;
		line-height: 1.4;
	}

	.ip-address:hover {
		border-color: var(--accent);
		color: var(--accent-hover);
	}

	.ip-address:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
		border-radius: var(--radius-sm);
	}
</style>
