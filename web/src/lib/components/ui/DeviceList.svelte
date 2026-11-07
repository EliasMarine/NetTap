<!--
  DeviceList.svelte: device rows with a tile, name and IP, and a value with a mini bar
  (nettap-design-system/components/DeviceList).
  - mode="link" (default): each row links to `href` (a row without one is not a link).
  - mode="select": each row is a <button aria-pressed> that calls `onselect`, as Live's top
    talkers filter the feed instead of navigating (PLAN.md §5.3).
  Bars scale to `max`, default the largest value. An item with `spark` shows it in place of
  the bar.
-->
<script module lang="ts">
	export interface DeviceListItem {
		key: string;
		name: string;
		ip: string;
		category?: string;
		/** NET-200: the owner's photo URL and picked icon, passed to the tile */
		picture?: string | null;
		icon?: string | null;
		value: number;
		/** The formatted value: "14.2 GB", "38.2 Mbps". */
		display: string;
		href?: string;
		spark?: number[];
	}
</script>

<script lang="ts">
	import DeviceTile from './DeviceTile.svelte';

	interface Props {
		items: DeviceListItem[];
		max?: number;
		mode?: 'link' | 'select';
		selectedKey?: string;
		onselect?: (item: DeviceListItem) => void;
	}

	let { items, max, mode = 'link', selectedKey, onselect }: Props = $props();

	const scale = $derived(max ?? Math.max(0, ...items.map((item) => item.value)));
	const width = (value: number) => (scale > 0 && value > 0 ? Math.min(100, (value / scale) * 100) : 0);

	// shortcut: straight segments, not the system's monotone curve; swap to ui/charts/Sparkline.svelte when it lands
	const SPARK_W = 72;
	const SPARK_H = 26;
	function sparkPoints(values: number[]): string {
		const lo = Math.min(...values);
		const span = Math.max(...values) - lo || 1;
		const x = (i: number) => 2 + ((SPARK_W - 4) * i) / (values.length - 1);
		const y = (v: number) => SPARK_H - 3 - ((SPARK_H - 6) * (v - lo)) / span;
		return values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
	}
</script>

{#snippet body(item: DeviceListItem)}
	<!-- OLD CODE: <DeviceTile category={item.category} /> (NET-200: the owner's picture) -->
	<DeviceTile category={item.category} picture={item.picture} icon={item.icon} />
	<span><span class="dev-name">{item.name}</span><span class="dev-ip mono">{item.ip}</span></span>
	<span class="dev-v"
		>{item.display}{#if item.spark && item.spark.length > 1}<svg
				class="spark"
				viewBox="0 0 {SPARK_W} {SPARK_H}"
				width={SPARK_W}
				height={SPARK_H}
				aria-hidden="true"><polyline class="line ln-spark" points={sparkPoints(item.spark)} /></svg
			>{:else}<span class="mini" aria-hidden="true"><span style:--w="{width(item.value).toFixed(1)}%"></span></span>{/if}</span
	>
{/snippet}

<ul class="dev-list">
	{#each items as item (item.key)}
		<li>
			{#if mode === 'select'}
				<button class="dev" type="button" aria-pressed={item.key === selectedKey} onclick={() => onselect?.(item)}
					>{@render body(item)}</button
				>
			{:else if item.href}
				<a class="dev" href={item.href}>{@render body(item)}</a>
			{:else}
				<div class="dev">{@render body(item)}</div>
			{/if}
		</li>
	{/each}
</ul>

<style>
	.spark { display: block; margin: var(--sp-1) 0 0 auto; }
</style>
