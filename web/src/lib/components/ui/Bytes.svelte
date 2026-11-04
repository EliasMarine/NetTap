<!-- Bytes.svelte: a data-volume cell, the formatted value over a log-scale mini bar (.bytes). -->
<script lang="ts">
	/** `display` is the formatted value ("2.41 GB"); `max` is the table's largest value. */
	let { value, max, display }: { value: number; max: number; display: string } = $props();

	// Log scale, so a 60 B probe still shows a bar beside a 2 GB stream
	const width = $derived(value > 0 && max > 0 ? Math.min(100, (Math.log10(value + 1) / Math.log10(max + 1)) * 100) : 0);
</script>

<span class="bytes">
	<span>{display}</span>
	<span class="mini" aria-hidden="true"><span style:--w="{width.toFixed(1)}%"></span></span>
</span>
