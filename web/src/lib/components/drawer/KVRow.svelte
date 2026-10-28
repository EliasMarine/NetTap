<!--
  KVRow.svelte — Single key-value row for use inside DrawerSection.
  Handles monospace formatting for IPs/ports, copy-to-clipboard on value click.
-->
<script lang="ts">
	let {
		label,
		value = null,
		mono = false,
		copyable = false,
	}: {
		label: string;
		value: string | number | null | undefined;
		mono?: boolean;
		copyable?: boolean;
	} = $props();

	let copied = $state(false);

	function handleCopy() {
		if (!copyable || value == null) return;
		navigator.clipboard.writeText(String(value));
		copied = true;
		setTimeout(() => { copied = false; }, 1500);
	}
</script>

<div class="kv-row">
	<span class="kv-label" title={label}>{label}</span>
	{#if value == null || value === '' || value === undefined}
		<span class="kv-value kv-empty">--</span>
	{:else}
		<span
			class="kv-value"
			class:mono
			class:copyable
			role={copyable ? 'button' : undefined}
			tabindex={copyable ? 0 : undefined}
			onclick={handleCopy}
			onkeydown={(e) => { if (copyable && (e.key === 'Enter' || e.key === ' ')) handleCopy(); }}
			title={copyable ? (copied ? 'Copied!' : 'Click to copy') : undefined}
		>
			{value}
			{#if copied}
				<span class="copied-badge">Copied</span>
			{/if}
		</span>
	{/if}
</div>

<style>
	.kv-row {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		padding: var(--space-xs) 0;
		border-bottom: 1px solid var(--border-dim);
		font-size: var(--text-sm);
	}

	.kv-row:last-child {
		border-bottom: none;
	}

	.kv-label {
		flex-shrink: 0;
		width: 160px;
		min-width: 160px;
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding-top: 2px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.kv-value {
		flex: 1;
		color: var(--text-primary);
		word-break: break-all;
		line-height: 1.4;
	}

	.kv-value.mono {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}

	.kv-value.copyable {
		cursor: pointer;
		border-radius: var(--radius-sm);
		transition: background-color var(--transition-fast);
		padding: 1px 4px;
		margin: -1px -4px;
		position: relative;
	}

	.kv-value.copyable:hover {
		background-color: var(--bg-tertiary);
	}

	.kv-empty {
		color: var(--text-dim);
	}

	.copied-badge {
		display: inline-flex;
		align-items: center;
		margin-left: var(--space-xs);
		font-size: 10px;
		color: var(--green);
		font-weight: 600;
		letter-spacing: 0.02em;
	}
</style>
