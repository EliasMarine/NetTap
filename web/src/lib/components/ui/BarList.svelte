<!--
  BarList.svelte: ranked horizontal bars scaled to the largest item
  (nettap-design-system/components/BarList). Never aggregates (PLAN.md §4.1): every item keeps
  its own row and its link or action. One colour (data-1) unless the page sets `colour`.
-->
<script module lang="ts">
	export interface BarItem {
		key: string;
		label: string;
		value: number;
		/** The figure, in text-1: "21.4 GB". */
		display: string;
		/** Text after the figure: "44%" reads "21.4 GB · 44%". */
		detail?: string;
		href?: string;
		onclick?: () => void;
		colour?: 1 | 2 | 3 | 4 | 5 | 6;
	}
</script>

<script lang="ts">
	let { items }: { items: BarItem[] } = $props();

	const max = $derived(Math.max(0, ...items.map((item) => (Number.isFinite(item.value) ? item.value : 0))));
	const width = (value: number) => (max > 0 && value > 0 ? (value / max) * 100 : 0);
</script>

<ul class="bars">
	{#each items as item (item.key)}
		<li class="bar-row">
			{#if item.href}
				<a class="bar-label" href={item.href}>{item.label}</a>
			{:else if item.onclick}
				<button class="bar-label" type="button" onclick={item.onclick}>{item.label}</button>
			{:else}
				<span>{item.label}</span>
			{/if}
			<span class="v"><b>{item.display}</b>{#if item.detail}{` · ${item.detail}`}{/if}</span>
			<span class="bar-track" aria-hidden="true"
				><span class="bar-fill c-d{item.colour ?? 1}" style:--w="{width(item.value).toFixed(1)}%"></span></span
			>
		</li>
	{/each}
</ul>

<style>
	/* Layout glue: a linked or clickable label looks like the plain label */
	.bar-label { all: unset; cursor: pointer; overflow-wrap: anywhere; }
	.bar-label:hover { text-decoration: underline; }
	.bar-label:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
</style>
