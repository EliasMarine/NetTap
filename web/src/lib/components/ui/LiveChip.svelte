<!-- LiveChip.svelte: the Live / Paused chip with its pulsing dot (Chip README: .live-chip). -->
<script lang="ts">
	import Icon from './Icon.svelte';

	// NET-237 (audit HON-17): `stalled` while every poll fails, so frozen data never reads "Live"
	let { paused, stalled = false }: { paused: boolean; stalled?: boolean } = $props();
</script>

<!-- OLD CODE START — NET-237: Live or Paused only, so a feed whose every request failed still read "Live"
<span class={['chip', 'live-chip', paused && 'is-paused']}
	><span class="live-dot" aria-hidden="true"></span>{paused ? 'Paused' : 'Live'}</span
>
OLD CODE END -->
{#if stalled && !paused}
	<span class="chip is-warn"><Icon name="warn" />Not updating</span>
{:else}
	<span class={['chip', 'live-chip', paused && 'is-paused']}
		><span class="live-dot" aria-hidden="true"></span>{paused ? 'Paused' : 'Live'}</span
	>
{/if}
