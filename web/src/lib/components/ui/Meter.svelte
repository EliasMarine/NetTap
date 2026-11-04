<!-- Meter.svelte: the 6 px accent bar for one share (BarList README: .meter), 0 to 100. -->
<script lang="ts">
	let { value, label }: { value: number; label: string } = $props();

	const pct = $derived(Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : 0);
</script>

<div class="meter" role="meter" aria-label={label} aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
	<span style:width="{pct}%"></span>
</div>
