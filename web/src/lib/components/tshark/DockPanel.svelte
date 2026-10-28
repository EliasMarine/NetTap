<script lang="ts">
	import type { Snippet } from 'svelte';

	type PanelMode = 'docked' | 'minimized' | 'maximized' | 'floating';

	interface Props {
		title: string;
		panelId: string;
		mode?: PanelMode;
		onaction?: (panelId: string, action: 'minimize' | 'maximize' | 'popout') => void;
		children?: Snippet;
	}

	let { title, panelId, mode = 'docked', onaction, children }: Props = $props();
</script>

<div class="dock-panel" class:minimized={mode === 'minimized'} class:maximized={mode === 'maximized'}>
	<div class="dock-panel-header">
		<span class="dock-panel-title">{title}</span>
		<div class="dock-panel-actions">
			<button
				class="panel-action-btn"
				title="Minimize"
				onclick={() => onaction?.(panelId, 'minimize')}
			>
				<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor">
					<path d="M2 7.75h12a.75.75 0 010 1.5H2a.75.75 0 010-1.5z" />
				</svg>
			</button>
			<button
				class="panel-action-btn"
				title="Maximize"
				onclick={() => onaction?.(panelId, 'maximize')}
			>
				<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor">
					<path d="M3.5 3.5v9h9v-9h-9zM2 3a1 1 0 011-1h10a1 1 0 011 1v10a1 1 0 01-1 1H3a1 1 0 01-1-1V3z" />
				</svg>
			</button>
			<button
				class="panel-action-btn"
				title="Pop out"
				onclick={() => onaction?.(panelId, 'popout')}
			>
				<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor">
					<path d="M10 1h5v5h-1.5V3.56L8.78 8.28a.75.75 0 01-1.06-1.06L12.44 2.5H10V1zM3.5 3.5H7V2H3a1 1 0 00-1 1v10a1 1 0 001 1h10a1 1 0 001-1V9h-1.5v4.5h-9v-10z" />
				</svg>
			</button>
		</div>
	</div>
	{#if mode !== 'minimized'}
		<div class="dock-panel-content">
			{#if children}
				{@render children()}
			{/if}
		</div>
	{/if}
</div>

<style>
	.dock-panel {
		display: flex;
		flex-direction: column;
		min-height: 0;
		height: 100%;
		overflow: hidden;
	}

	.dock-panel.minimized {
		height: auto;
		flex: 0 0 auto;
	}

	.dock-panel.maximized {
		position: absolute;
		inset: 0;
		z-index: 20;
		background: var(--bg-primary);
	}

	.dock-panel-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 4px 8px;
		background: var(--bg-tertiary);
		border-bottom: 1px solid var(--border-default);
		flex-shrink: 0;
		user-select: none;
	}

	.dock-panel-title {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.dock-panel-actions {
		display: flex;
		gap: 2px;
	}

	.panel-action-btn {
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
		transition: all var(--transition-fast);
	}

	.panel-action-btn:hover {
		background: var(--bg-secondary);
		color: var(--text-primary);
	}

	.dock-panel-content {
		flex: 1;
		min-height: 0;
		overflow: auto;
	}
</style>
