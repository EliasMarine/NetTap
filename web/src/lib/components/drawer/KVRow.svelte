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
			title={copyable ? (copied ? 'Copied' : 'Click to copy') : undefined}
		>
			{value}
			{#if copied}
				<span class="copied-badge">Copied</span>
			{/if}
		</span>
	{/if}
</div>

<style>
	/* One row of the system's .facts list: key in text-3, value right-aligned in text-1. */
	.kv-row {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--sp-4);
		padding: var(--sp-1) 0;
		font-size: var(--text-sm);
	}

	.kv-label {
		flex: 0 0 auto;
		max-width: 45%;
		color: var(--text-3);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.kv-value {
		flex: 1;
		min-width: 0;
		text-align: right;
		color: var(--text-1);
		overflow-wrap: anywhere;
		line-height: 1.4;
	}

	.kv-value.copyable {
		cursor: pointer;
		border-radius: var(--r-xs);
		transition: background-color var(--dur-fast);
		padding: 1px var(--sp-1);
		margin: -1px calc(var(--sp-1) * -1);
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
		font-size: var(--text-micro);
		color: var(--ok);
		font-weight: 600;
	}
</style>
