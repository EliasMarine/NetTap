<!--
  TopTalkersChart.svelte — Thin wrapper around HorizontalBarList for
  displaying top talker devices ranked by bytes transferred.

  Used in the Live Network Monitor to show which IPs generate the most traffic.
-->
<script lang="ts">
	import HorizontalBarList from '$components/HorizontalBarList.svelte';
	import type { BarItem } from '$components/HorizontalBarList.svelte';
	import type { TopTalker } from '$lib/api/live';

	interface Props {
		talkers: TopTalker[];
		activeDevice: string | null;
		onclick: (ip: string) => void;
	}

	let { talkers, activeDevice, onclick }: Props = $props();

	/**
	 * Format byte counts into human-readable strings.
	 * Uses binary units (KiB, MiB, GiB) for precision.
	 */
	function formatBytes(bytes: number): string {
		if (bytes === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const k = 1024;
		const i = Math.floor(Math.log(bytes) / Math.log(k));
		const idx = Math.min(i, units.length - 1);
		const value = bytes / Math.pow(k, idx);
		return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[idx]}`;
	}

	// Transform TopTalker[] into BarItem[] for HorizontalBarList
	let items: BarItem[] = $derived(
		talkers.map((t) => ({
			key: t.ip,
			label: t.ip,
			value: t.bytes,
			formattedValue: formatBytes(t.bytes),
			secondaryValue: `${t.connections} conn`,
			color: 'var(--cyan)',
			mono: true,
			isIp: true,
		}))
	);

	function handleClick(item: BarItem, _index: number) {
		onclick(item.key);
	}
</script>

<HorizontalBarList
	{items}
	showRank={true}
	labelWidth={150}
	activeKey={activeDevice ?? undefined}
	onclick={handleClick}
/>
