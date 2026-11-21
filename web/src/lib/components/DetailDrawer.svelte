<!--
  DetailDrawer.svelte — Unified slide-out side panel, styled as the system's AlertDrawer card.
  Shared across all pages. 480px wide, slides from right with backdrop.
  Renders configurable tabs (system pills), scrollable content area, and footer actions.

  NET-349: a native modal <dialog> (showModal), so the page behind is inert, even parts added
  while it is open; focus moves to Close on open, Tab wraps inside, and focus goes back to
  whatever opened it on close.
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

	// OLD CODE START — NET-349: Escape now comes as the dialog's cancel event, the backdrop as a click outside the panel
	// function handleKeydown(e: KeyboardEvent) {
	// 	if (e.key === 'Escape' && open) {
	// 		onclose();
	// 	}
	// }
	//
	// function handleBackdropClick() {
	// 	onclose();
	// }
	// OLD CODE END

	const uid = $props.id();
	const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
	/** A click this recent opened the drawer, so its element gets focus back on close. */
	const OPENER_CLICK_MS = 1000;

	let dialog = $state<HTMLDialogElement>();
	let panel = $state<HTMLElement>();
	let closeButton = $state<HTMLButtonElement>();

	// A clicked button isn't always focused (Safari; DataTable's forwarded row click), so the
	// element a click landed on is noted here, in the capture phase, before any page handler opens the drawer.
	let lastClick: { el: HTMLElement | null; at: number } | null = null;
	$effect(() => {
		const note = (e: MouseEvent) => {
			lastClick = { el: (e.target as Element | null)?.closest<HTMLElement>(FOCUSABLE) ?? null, at: performance.now() };
		};
		window.addEventListener('click', note, true);
		return () => window.removeEventListener('click', note, true);
	});

	function openerNow(): HTMLElement | null {
		if (lastClick?.el && performance.now() - lastClick.at < OPENER_CLICK_MS) return lastClick.el;
		const active = document.activeElement;
		return active instanceof HTMLElement && active !== document.body ? active : null;
	}

	$effect(() => {
		const d = dialog;
		if (!open || !d) return;
		const opener = openerNow();
		if (!d.open) d.showModal();
		closeButton?.focus();
		return () => {
			if (d.open) d.close();
			const back = opener?.isConnected ? opener : document.getElementById('main');
			back?.focus({ preventScroll: true });
		};
	});

	// Escape: the parent's `open` stays the one switch
	function oncancel(e: Event) {
		e.preventDefault();
		onclose();
	}

	// A close the parent didn't ask for (a second Escape the browser won't let us cancel); a late
	// event from an earlier close finds the dialog open again and is ignored
	function onnativeclose() {
		if (open && dialog && !dialog.open) onclose();
	}

	// Only a press and a release both outside the panel close it, so a drag that starts or ends inside doesn't
	let pressedOutside = false;
	function outsidePanel(e: MouseEvent): boolean {
		if (e.target !== dialog || !panel) return false;
		const r = panel.getBoundingClientRect();
		return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
	}
	function onpointerdown(e: PointerEvent) {
		pressedOutside = outsidePanel(e);
	}
	function onclick(e: MouseEvent) {
		if (pressedOutside && outsidePanel(e)) onclose();
		pressedOutside = false;
	}

	// Wrap Tab at both ends; the list is read now, since tabs and rows come and go
	function onkeydown(e: KeyboardEvent) {
		if (e.key !== 'Tab' || !panel) return;
		const items = [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.checkVisibility?.() ?? true);
		const first = items[0];
		const last = items[items.length - 1];
		if (e.shiftKey && document.activeElement === first) {
			e.preventDefault();
			last?.focus();
		} else if (!e.shiftKey && document.activeElement === last) {
			e.preventDefault();
			first?.focus();
		}
	}
</script>

<!-- OLD CODE START — NET-349: a native modal dialog replaces the backdrop button and the aside
<svelte:window onkeydown={handleKeydown} />
{#if open}
	<button class="drawer-backdrop" onclick={handleBackdropClick} aria-label="Close detail panel" tabindex="-1"></button>
{/if}
<aside class="detail-drawer" class:open aria-label="Detail panel">
OLD CODE END -->
<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
<dialog
	bind:this={dialog}
	class="detail-drawer"
	aria-labelledby="{uid}-title"
	{oncancel}
	onclose={onnativeclose}
	{onpointerdown}
	{onclick}
	{onkeydown}
>
	<div class="panel" bind:this={panel}>
	{#if open}
		<!-- Header -->
		<div class="drawer-header">
			<div class="drawer-header-text">
				<h3 class="drawer-title type-drawer-title" id="{uid}-title">{title}</h3>
				{#if subtitle}
					<p class="drawer-subtitle mono">{subtitle}</p>
				{/if}
			</div>
			<button class="icon-btn" type="button" bind:this={closeButton} onclick={onclose} aria-label="Close panel">
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
	</div>
</dialog>

<style>
	/* OLD CODE START — NET-349: the backdrop button and the transformed aside became a native dialog
	.drawer-backdrop { position: fixed; inset: 0; z-index: 998; background-color: var(--scrim); border: none; cursor: pointer; animation: backdropFadeIn 200ms ease-out; }
	.detail-drawer { position: fixed; top: 0; right: 0; bottom: 0; width: 480px; max-width: 100vw; z-index: 999; background: var(--surface-1); border-left: 1px solid var(--line); box-shadow: var(--sheen), var(--shadow-pop); display: flex; flex-direction: column; transform: translateX(100%); transition: transform 250ms var(--ease); }
	.detail-drawer.open { transform: translateX(0); }
	OLD CODE END */

	/* ----- The dialog: the browser's own sizing reset, docked to the right edge (top layer) ----- */
	.detail-drawer {
		position: fixed;
		inset: 0 0 0 auto;
		margin: 0;
		padding: 0;
		border: 0;
		width: 480px;
		max-width: 100vw;
		height: 100dvh;
		max-height: none;
		background: transparent;
		color: var(--text-1);
		overflow: visible;
	}

	/* Closed, it keeps the browser's display: none */
	.detail-drawer[open] {
		display: flex;
		animation: drawerIn 250ms var(--ease);
	}

	.detail-drawer::backdrop {
		background-color: var(--scrim);
		animation: backdropFadeIn 200ms ease-out;
	}

	@keyframes drawerIn {
		from { transform: translateX(100%); }
		to { transform: translateX(0); }
	}

	@keyframes backdropFadeIn {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	/* ----- Panel: a surface-1 card filling the dialog ----- */
	.panel {
		flex: 1;
		min-width: 0;
		background: var(--surface-1);
		border-left: 1px solid var(--line);
		box-shadow: var(--sheen), var(--shadow-pop);
		display: flex;
		flex-direction: column;
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
