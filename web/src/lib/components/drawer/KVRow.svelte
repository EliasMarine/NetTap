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
		gap: var(--sp-2);
		padding: var(--sp-1) 0;
		border-bottom: 1px solid var(--line);
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
		color: var(--text-3);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding-top: 2px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.kv-value {
		flex: 1;
		color: var(--text-1);
		word-break: break-all;
		line-height: 1.4;
	}

	.kv-value.mono {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}

	.kv-value.copyable {
		cursor: pointer;
		border-radius: var(--r-sm);
		transition: background-color var(--dur-fast);
		padding: 1px 4px;
		margin: -1px -4px;
		position: relative;
	}

	.kv-value.copyable:hover {
		background-color: var(--surface-2);
	}

	.kv-empty {
		color: var(--text-3);
	}

	.copied-badge {
		display: inline-flex;
		align-items: center;
		margin-left: var(--sp-1);
		font-size: 10px;
		color: var(--ok);
		font-weight: 600;
		letter-spacing: 0.02em;
	}
</style>
