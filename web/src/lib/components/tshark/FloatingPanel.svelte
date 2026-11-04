<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from '$lib/components/ui/Icon.svelte';

	interface Props {
		title: string;
		panelId: string;
		x?: number;
		y?: number;
		width?: number;
		height?: number;
		onclose?: (panelId: string) => void;
		onfocus?: (panelId: string) => void;
		children?: Snippet;
	}

	let {
		title,
		panelId,
		x = $bindable(100),
		y = $bindable(100),
		width = 600,
		height = 400,
		onclose,
		onfocus,
		children,
	}: Props = $props();

	let dragging = $state(false);
	let dragOffsetX = 0;
	let dragOffsetY = 0;

	function handleHeaderPointerDown(e: PointerEvent) {
		if ((e.target as HTMLElement).closest('button')) return;
		e.preventDefault();
		dragging = true;
		dragOffsetX = e.clientX - x;
		dragOffsetY = e.clientY - y;

		const onMove = (ev: PointerEvent) => {
			if (!dragging) return;
			x = Math.max(0, ev.clientX - dragOffsetX);
			y = Math.max(0, ev.clientY - dragOffsetY);
		};

		const onUp = () => {
			dragging = false;
			document.removeEventListener('pointermove', onMove);
			document.removeEventListener('pointerup', onUp);
		};

		document.addEventListener('pointermove', onMove);
		document.addEventListener('pointerup', onUp);
	}

	function handlePanelClick() {
		onfocus?.(panelId);
	}
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
	class="floating-panel"
	style="left: {x}px; top: {y}px; width: {width}px; height: {height}px;"
	onclick={handlePanelClick}
>
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="floating-header" onpointerdown={handleHeaderPointerDown}>
		<span class="floating-title eyebrow">{title}</span>
		<button class="floating-close" title="Dock panel" onclick={() => onclose?.(panelId)}>
			<Icon name="close" />
		</button>
	</div>
	<div class="floating-content">
		{#if children}
			{@render children()}
		{/if}
	</div>
</div>

<style>
	.floating-panel {
		position: absolute;
		display: flex;
		flex-direction: column;
		background: var(--surface-1);
		border: 1px solid var(--line-strong);
		border-radius: var(--r-md);
		box-shadow: var(--shadow-pop);
		z-index: 50;
		overflow: hidden;
	}

	.floating-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--sp-1) var(--sp-1) var(--sp-1) var(--sp-3);
		background: var(--surface-2);
		border-bottom: 1px solid var(--line);
		cursor: grab;
		user-select: none;
		touch-action: none;
	}

	.floating-header:active {
		cursor: grabbing;
	}

	/* Compact icon button, matching DockPanel's header actions */
	.floating-close {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		padding: 0;
		background: none;
		border: none;
		border-radius: var(--r-pill);
		color: var(--text-3);
		cursor: pointer;
	}

	.floating-close :global(.ic) {
		width: 14px;
		height: 14px;
	}

	.floating-close:hover {
		background: var(--surface-3);
		color: var(--text-1);
	}

	.floating-content {
		flex: 1;
		min-height: 0;
		overflow: auto;
	}
</style>
