<!-- StatStrip.svelte: figures separated by hairlines across a hero card (StatStrip README: .stats). -->
<script module lang="ts">
	export interface Stat {
		key: string;
		label: string;
		value: string;
	}
</script>

<script lang="ts">
	let { stats }: { stats: Stat[] } = $props();
</script>

<div class="stats">
	{#each stats as stat (stat.key)}
		<div class="stat">
			<div class="stat-k">{stat.label}</div>
			<div class="stat-v">{stat.value}</div>
		</div>
	{/each}
</div>
