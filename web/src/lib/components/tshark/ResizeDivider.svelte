<script lang="ts">
	interface Props {
		direction: 'horizontal' | 'vertical';
		ondrag?: (delta: number) => void;
	}

	let { direction, ondrag }: Props = $props();

	let dragging = $state(false);
	let startPos = 0;

	function handlePointerDown(e: PointerEvent) {
		e.preventDefault();
		dragging = true;
		startPos = direction === 'horizontal' ? e.clientY : e.clientX;
		(e.target as HTMLElement).setPointerCapture?.(e.pointerId);

		const onMove = (ev: PointerEvent) => {
			if (!dragging) return;
			const current = direction === 'horizontal' ? ev.clientY : ev.clientX;
			const delta = current - startPos;
			startPos = current;
			ondrag?.(delta);
		};

		const onUp = () => {
			dragging = false;
			document.removeEventListener('pointermove', onMove);
			document.removeEventListener('pointerup', onUp);
		};

		document.addEventListener('pointermove', onMove);
		document.addEventListener('pointerup', onUp);
	}
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="resize-divider {direction}"
	class:active={dragging}
	onpointerdown={handlePointerDown}
	role="separator"
	aria-orientation={direction}
></div>

<style>
	.resize-divider {
		flex-shrink: 0;
		background: var(--border-default);
		transition: background-color var(--transition-fast);
		touch-action: none;
		z-index: 2;
	}

	.resize-divider:hover,
	.resize-divider.active {
		background: var(--accent);
	}

	.horizontal {
		height: 4px;
		cursor: row-resize;
		width: 100%;
	}

	.vertical {
		width: 4px;
		cursor: col-resize;
		height: 100%;
	}
</style>
