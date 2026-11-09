<!--
  CopyButton.svelte: a small icon button that copies one value (IPv6 toolkit, NET-218).
  A check for 1.5 s after a copy; "Couldn't copy" when the browser refuses (no secure
  context, or permission denied). Local to this page until a second page needs it.
-->
<script lang="ts">
	import Icon from '$lib/components/ui/Icon.svelte';

	let { value, what }: { value: string; what: string } = $props();

	const RESET_MS = 1500;
	let status = $state<'idle' | 'copied' | 'failed'>('idle');
	let timer: ReturnType<typeof setTimeout> | undefined;

	async function copy() {
		clearTimeout(timer);
		try {
			await navigator.clipboard.writeText(value);
			status = 'copied';
		} catch {
			// navigator.clipboard is missing outside a secure context, or the write was refused
			status = 'failed';
		}
		timer = setTimeout(() => (status = 'idle'), RESET_MS);
	}

	$effect(() => () => clearTimeout(timer));
</script>

<button class="copy" class:done={status === 'copied'} type="button" aria-label="Copy {what}" title="Copy" onclick={copy}>
	<Icon name={status === 'copied' ? 'check' : 'copy'} />
</button>
{#if status === 'failed'}<span class="copy-fail">Couldn't copy</span>{/if}
<span class="sr-only" role="status">{status === 'copied' ? `Copied ${what}` : status === 'failed' ? `Couldn't copy ${what}` : ''}</span>

<style>
	.copy {
		display: inline-grid; place-items: center; width: 26px; height: 26px; margin-left: var(--sp-1); vertical-align: middle;
		border: 1px solid transparent; border-radius: var(--r-sm); background: transparent; color: var(--text-3); cursor: pointer;
		transition: color var(--dur-fast), border-color var(--dur-fast);
	}
	.copy:hover { color: var(--text-1); border-color: var(--line); }
	.copy.done { color: var(--ok); }
	.copy :global(.ic) { width: 15px; height: 15px; }
	.copy-fail { margin-left: var(--sp-1); font-size: var(--text-xs); color: var(--sev-critical); }
</style>
