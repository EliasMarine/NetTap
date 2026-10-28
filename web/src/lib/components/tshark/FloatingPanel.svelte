<script lang="ts">
	import type { Snippet } from 'svelte';

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
		<span class="floating-title">{title}</span>
		<button class="floating-close" title="Dock panel" onclick={() => onclose?.(panelId)}>
			<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor">
				<path d="M3.72 3.72a.75.75 0 011.06 0L8 6.94l3.22-3.22a.75.75 0 111.06 1.06L9.06 8l3.22 3.22a.75.75 0 11-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 01-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 010-1.06z" />
			</svg>
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
		background: var(--bg-primary);
		border: 1px solid var(--accent);
		border-radius: var(--radius-md);
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
		z-index: 50;
		overflow: hidden;
	}

	.floating-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px 10px;
		background: var(--bg-tertiary);
		border-bottom: 1px solid var(--border-default);
		cursor: grab;
		user-select: none;
		touch-action: none;
	}

	.floating-header:active {
		cursor: grabbing;
	}

	.floating-title {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.floating-close {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		padding: 0;
		background: none;
		border: none;
		border-radius: var(--radius-sm);
		color: var(--text-muted);
		cursor: pointer;
	}

	.floating-close:hover {
		background: var(--bg-secondary);
		color: var(--text-primary);
	}

	.floating-content {
		flex: 1;
		min-height: 0;
		overflow: auto;
	}
</style>
