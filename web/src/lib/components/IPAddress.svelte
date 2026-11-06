<!--
  IPAddress.svelte — an IP address that links to where it drills down (NET-160): its device
  page on the LAN, the address page otherwise ($ipHref). Right-click (or long-press) opens a
  menu of lookups. The link and the menu are siblings, so the menu's buttons never sit inside
  the link. `linked={false}` renders plain text (no link, role, tabindex or menu), for the
  places where the address already sits inside a link or button.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import ContextMenu from '$components/ContextMenu.svelte';
	import type { ContextMenuItem } from '$components/ContextMenu.svelte';
	import { ipHref, isLan } from '$lib/stores/lan';

	// ---------------------------------------------------------------------------
	// Props
	// ---------------------------------------------------------------------------

	let {
		ip,
		showMenu = true,
		linked = true,
	}: {
		ip: string;
		showMenu?: boolean;
		/** False inside another link or button: plain text, no menu. */
		linked?: boolean;
	} = $props();

	const href = $derived($ipHref(ip));
	const onLan = $derived($isLan(ip) === true);

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
		// OLD CODE START — NET-160: the device page for every address, internet ones included
		// {
		// 	label: 'View device details',
		// 	icon: 'device',
		// 	separator: true,
		// 	action: () => {
		// 		goto(`/devices/${encodeURIComponent(ip)}`);
		// 	},
		// },
		// OLD CODE END
		{
			label: onLan ? 'Open device page' : 'Open address page',
			icon: 'device',
			separator: true,
			action: () => {
				goto(href);
			},
		},
		{
			label: 'GeoIP lookup',
			icon: 'geoip',
			action: () => {
				goto(`/geoip/${encodeURIComponent(ip)}`);
			},
		},
		{
			label: 'WHOIS lookup',
			icon: 'whois',
			action: () => {
				goto(`/lookup/whois/${encodeURIComponent(ip)}`);
			},
		},
		{
			label: 'DNS lookup',
			icon: 'dns',
			action: () => {
				goto(`/lookup/dns/${encodeURIComponent(ip)}`);
			},
		},
		{
			label: 'Ping this IP',
			icon: 'ping',
			action: () => {
				goto(`/tools/ping?target=${encodeURIComponent(ip)}`);
			},
		},
		{
			label: 'Traceroute to this IP',
			icon: 'ping',
			action: () => {
				goto(`/tools/ping?target=${encodeURIComponent(ip)}&tab=traceroute`);
			},
		},
		{
			label: 'SSL certificate check',
			icon: 'ssl',
			separator: true,
			action: () => {
				goto(`/tools/ssl-cert?host=${encodeURIComponent(ip)}`);
			},
		},
		{
			label: 'View alerts for this IP',
			icon: 'alert',
			separator: true,
			action: () => {
				goto(`/alerts?ip=${encodeURIComponent(ip)}`);
			},
		},
		// OLD CODE START — NET-160: Connections ignored ?src_ip= and ?dst_ip=; its filter is ?ip=, either side
		// {
		// 	label: 'Filter connections from this IP',
		// 	icon: 'search',
		// 	separator: true,
		// 	action: () => {
		// 		goto(`/connections?src_ip=${encodeURIComponent(ip)}`);
		// 	},
		// },
		// {
		// 	label: 'Filter connections to this IP',
		// 	icon: 'search',
		// 	action: () => {
		// 		goto(`/connections?dst_ip=${encodeURIComponent(ip)}`);
		// 	},
		// },
		// OLD CODE END
		{
			label: 'Connections with this address',
			icon: 'search',
			separator: true,
			action: () => {
				goto(`/connections?ip=${encodeURIComponent(ip)}`);
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

<!-- OLD CODE START — NET-160: a span role=button with tabindex, so inside a link or a row button it
nested interactive elements, and the menu's buttons rendered beside it with no link to follow
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
OLD CODE END -->
{#if linked}
	<span class="ip">
		<a
			class="ip-address mono"
			{href}
			oncontextmenu={handleContextMenu}
			ontouchstart={handleTouchStart}
			ontouchend={handleTouchEnd}
			ontouchmove={handleTouchMove}
			title={showMenu ? 'Right-click for options' : undefined}>{ip}</a
		>{#if showMenu}<ContextMenu items={menuItems} x={menuX} y={menuY} visible={menuVisible} onclose={closeMenu} />{/if}
	</span>
{:else}
	<span class="ip-address mono plain">{ip}</span>
{/if}

<style>
	/* .mono (system.css) sets the family and the 0.92em size. */
	.ip-address {
		color: var(--accent-strong);
		/* OLD CODE START — NET-160: the address is a link now
		cursor: context-menu;
		OLD CODE END */
		text-decoration: none;
		user-select: text;
		border-bottom: 1px dashed var(--line-strong);
		transition: border-color var(--dur-fast);
		display: inline;
		line-height: 1.4;
	}

	.ip-address:hover {
		border-color: var(--accent-strong);
	}

	.ip-address:focus-visible {
		border-radius: var(--r-xs);
	}

	/* Inside another link or button: the address reads as that control's text */
	.plain {
		color: inherit;
		border-bottom: 0;
	}
</style>
