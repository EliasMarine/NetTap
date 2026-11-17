<script lang="ts">
	/**
	 * NET-316: a device's MAC with a "Private" tag when the device made it up, and a copy button.
	 * Used in the Devices table and on both device pages; callers show "—" for a missing MAC.
	 */
	import { onDestroy } from 'svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { isPrivateMac } from '$lib/utils/mac';

	let { mac }: { mac: string } = $props();

	const FEEDBACK_MS = 1500;
	const LABELS = { idle: 'Copy MAC address', copied: 'Copied', failed: 'Copy failed' } as const;
	let copyState = $state<keyof typeof LABELS>('idle');
	let timer: ReturnType<typeof setTimeout> | undefined;

	/** The hidden-textarea copy for browsers without the Clipboard API, as IPAddress does. */
	function fallbackCopy(text: string): boolean {
		const area = document.createElement('textarea');
		area.value = text;
		area.setAttribute('readonly', '');
		area.style.position = 'fixed';
		area.style.opacity = '0';
		document.body.appendChild(area);
		area.select();
		try {
			return document.execCommand('copy');
		} catch {
			return false;
		} finally {
			area.remove();
		}
	}

	async function copy(event: MouseEvent) {
		// a row's click opens the device; copying must not
		event.stopPropagation();
		let copied = false;
		try {
			if (navigator.clipboard?.writeText) {
				await navigator.clipboard.writeText(mac);
				copied = true;
			}
		} catch {
			// denied or unavailable: the fallback below decides
		}
		if (!copied) copied = fallbackCopy(mac);
		copyState = copied ? 'copied' : 'failed';
		clearTimeout(timer);
		timer = setTimeout(() => (copyState = 'idle'), FEEDBACK_MS);
	}

	onDestroy(() => clearTimeout(timer));
</script>

<span class="mac">
	<span class="mono">{mac}</span>
	{#if isPrivateMac(mac)}
		<span class="tag" title="This device made up this address for privacy, so it can change over time">Private</span>
	{/if}
	<button
		type="button"
		class={['icon-btn', 'ghost', 'copy', copyState !== 'idle' && `is-${copyState}`]}
		aria-label={LABELS[copyState]}
		title={LABELS[copyState]}
		onclick={copy}
	>
		<Icon name={copyState === 'copied' ? 'check' : copyState === 'failed' ? 'warn' : 'copy'} />
	</button>
	{#if copyState !== 'idle'}<span class="sr-only" role="status">{LABELS[copyState]}</span>{/if}
</span>

<style>
	/* OLD CODE: .mac { display: inline-flex; flex-wrap: wrap; align-items: center; gap: var(--sp-1); max-width: 100%; } (NET-318: a squeezed table column wrapped Copy under the MAC) */
	.mac { display: inline-flex; align-items: center; gap: var(--sp-1); max-width: 100%; }
	/* a device page's narrow identity column on a phone breaks the line, not the page */
	:global(.meta-v) .mac { flex-wrap: wrap; }
	/* NET-318: in a narrowed table column the address and tag ellipsise first, so Copy stays whole */
	.mac > .mono, .mac > .tag { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
	/* a table row's size, not the 36px toolbar button; 24px is still a full touch target (WCAG 2.5.8) */
	/* in a device page's identity list .meta-v sets the size, as it did for the plain MAC */
	:global(.meta-v) .mono { font-size: inherit; }
	.copy { flex: none; width: var(--sp-6); height: var(--sp-6); color: var(--text-3); }
	.copy:hover, .copy:focus-visible { color: var(--text-1); }
	.copy.is-copied { color: var(--ok); }
	.copy.is-failed { color: var(--sev-high); }
	.copy :global(.ic) { width: 14px; height: 14px; }
</style>
