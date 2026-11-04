<!-- LiveChip.svelte: the Live / Paused chip with its pulsing dot (Chip README: .live-chip). -->
<script lang="ts">
	let { paused }: { paused: boolean } = $props();
</script>

<span class={['chip', 'live-chip', paused && 'is-paused']}
	><span class="live-dot" aria-hidden="true"></span>{paused ? 'Paused' : 'Live'}</span
>
