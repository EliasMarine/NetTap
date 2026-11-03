<!--
  ProtocolDonut.svelte — Thin wrapper that transforms protocol distribution
  data into DonutChart segments with protocol-specific colors.

  Used in the Live Network Monitor to visualize TCP/UDP/ICMP/other breakdown.
-->
<script lang="ts">
	import DonutChart from '$components/charts/DonutChart.svelte';
	import type { Segment } from '$components/charts/DonutChart.svelte';

	interface Props {
		protocols: Record<string, number>;
		activeProtocol: string | null;
		onclick: (protocol: string) => void;
		/** Connections behind the percentages, shown in the centre as the total */
		connections?: number | null;
	}

	let { protocols, activeProtocol, onclick, connections = null }: Props = $props();

	// Protocol → chart color mapping
	const PROTOCOL_COLORS: Record<string, string> = {
		tcp: 'var(--chart-1)',
		udp: 'var(--chart-5)',
		icmp: 'var(--chart-3)',
		other: 'var(--text-dim)',
	};

	function colorFor(proto: string): string {
		return PROTOCOL_COLORS[proto.toLowerCase()] ?? 'var(--text-dim)';
	}

	// Transform protocol Record into Segment[] for DonutChart
	let segments: Segment[] = $derived(
		Object.entries(protocols)
			.filter(([, value]) => value > 0)
			.map(([label, value]) => ({
				label: label.toUpperCase(),
				value,
				color: colorFor(label),
			}))
	);

	// Compute activeIndex from activeProtocol
	let activeIndex: number | null = $derived(
		activeProtocol != null
			? segments.findIndex((s) => s.label === activeProtocol.toUpperCase())
			: null
	);

	// Ensure -1 (not found) becomes null
	let resolvedActiveIndex: number | null = $derived(
		activeIndex != null && activeIndex >= 0 ? activeIndex : null
	);

	// OLD CODE START — 2026-11-02: the number of protocols, under a "total" label ("3 total")
	// // Format center value: show count of active protocols (keys with value > 0)
	// function formatValue(total: number): string {
	// 	const activeCount = Object.values(protocols).filter((v) => v > 0).length;
	// 	return `${activeCount}`;
	// }
	// OLD CODE END
	// The centre reads "<n> total": the connections the percentages are taken from
	function formatValue(): string {
		return connections != null ? connections.toLocaleString() : '—';
	}

	// Click handler: extract the protocol name from the segment and call parent
	function handleSegmentClick(segment: Segment, _index: number) {
		onclick(segment.label.toLowerCase());
	}
</script>

<DonutChart
	{segments}
	formatValue={formatValue}
	onclick={handleSegmentClick}
	activeIndex={resolvedActiveIndex}
/>
