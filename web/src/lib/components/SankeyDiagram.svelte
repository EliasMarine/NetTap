<!--
  SankeyDiagram.svelte — Pure-SVG Sankey flow diagram.

  Renders Source IPs → Protocols → Destination Orgs with cubic bezier links.
  Hover highlights connected paths, click filters the parent sessions table.
-->
<script lang="ts">
	import type { SankeyNode, SankeyLink } from '$api/traffic';

	// ---------------------------------------------------------------------------
	// Props
	// ---------------------------------------------------------------------------

	let {
		sources = [],
		protocols = [],
		destinations = [],
		links = [],
		onNodeClick,
	}: {
		sources: SankeyNode[];
		protocols: SankeyNode[];
		destinations: SankeyNode[];
		links: SankeyLink[];
		onNodeClick?: (type: 'source' | 'protocol' | 'destination', id: string) => void;
	} = $props();

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	const PADDING = 20;
	const COL_WIDTH = 120;
	const NODE_PAD = 8;
	const MIN_NODE_H = 20;
	const MIN_LINK_W = 2;
	const BASE_CHART_H = 400;

	const PROTO_COLORS: Record<string, string> = {
		tcp: 'var(--cyan)',
		udp: 'var(--green)',
		icmp: 'var(--amber)',
		tls: 'var(--purple)',
		dns: 'var(--amber)',
		http: 'var(--blue)',
		ssh: 'var(--red)',
	};

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let chartWidth = $state(800);
	let hoveredNode = $state<string | null>(null);

	// ---------------------------------------------------------------------------
	// Layout
	// ---------------------------------------------------------------------------

	interface LayoutNode {
		id: string;
		label: string;
		x: number;
		y: number;
		w: number;
		h: number;
		value: number;
		color: string;
		type: 'source' | 'protocol' | 'destination';
		country?: string;
	}

	interface LayoutLink {
		source: string;
		target: string;
		value: number;
		sy: number;  // source y center
		ty: number;  // target y center
		thickness: number; // visual stroke width
		highlighted: boolean;
	}

	function layoutNodes(nodes: SankeyNode[], colX: number, type: 'source' | 'protocol' | 'destination'): LayoutNode[] {
		if (nodes.length === 0) return [];
		const totalValue = Math.max(1, nodes.reduce((s, n) => s + n.value, 0));
		const availH = BASE_CHART_H - (nodes.length - 1) * NODE_PAD - PADDING * 2;
		let y = PADDING;

		return nodes.map((n) => {
			const h = Math.max(MIN_NODE_H, (n.value / totalValue) * availH);
			const node: LayoutNode = {
				id: n.id,
				label: n.label,
				x: colX,
				y,
				w: COL_WIDTH,
				h,
				value: n.value,
				color: type === 'protocol'
					? (PROTO_COLORS[n.id.toLowerCase()] || 'var(--accent)')
					: type === 'source'
						? 'var(--cyan)'
						: 'var(--teal, var(--green))',
				type,
				country: n.country,
			};
			y += h + NODE_PAD;
			return node;
		});
	}

	let layout = $derived.by(() => {
		const w = chartWidth;
		const col1 = PADDING;
		const col2 = w / 2 - COL_WIDTH / 2;
		const col3 = w - COL_WIDTH - PADDING;

		const srcNodes = layoutNodes(sources, col1, 'source');
		const protoNodes = layoutNodes(protocols, col2, 'protocol');
		const destNodes = layoutNodes(destinations, col3, 'destination');

		const allNodes = [...srcNodes, ...protoNodes, ...destNodes];

		// Compute actual height from the bottom-most node + padding
		const maxBottom = allNodes.length > 0
			? Math.max(...allNodes.map((n) => n.y + n.h))
			: BASE_CHART_H;
		const computedH = Math.max(BASE_CHART_H, maxBottom + PADDING);
		const nodeMap = new Map<string, LayoutNode>();
		allNodes.forEach((n) => nodeMap.set(n.id, n));

		// Compute actual link-value totals per node (for proportional stacking)
		const srcLinkTotals = new Map<string, number>();
		const tgtLinkTotals = new Map<string, number>();
		for (const link of links) {
			srcLinkTotals.set(link.source, (srcLinkTotals.get(link.source) || 0) + link.value);
			tgtLinkTotals.set(link.target, (tgtLinkTotals.get(link.target) || 0) + link.value);
		}

		// Track y offsets per node for stacking links
		const srcOffsets = new Map<string, number>();
		const tgtOffsets = new Map<string, number>();

		const layoutLinks: LayoutLink[] = [];
		// Sort links by value descending for better visual stacking
		const sortedLinks = [...links].sort((a, b) => b.value - a.value);

		for (const link of sortedLinks) {
			const srcNode = nodeMap.get(link.source);
			const tgtNode = nodeMap.get(link.target);
			if (!srcNode || !tgtNode) continue;

			// Proportional thickness based on actual link totals through this node
			const srcTotal = Math.max(1, srcLinkTotals.get(link.source) || 1);
			const tgtTotal = Math.max(1, tgtLinkTotals.get(link.target) || 1);
			const srcBand = (link.value / srcTotal) * srcNode.h;
			const tgtBand = (link.value / tgtTotal) * tgtNode.h;
			const thickness = Math.max(MIN_LINK_W, (srcBand + tgtBand) / 2);

			const sOff = srcOffsets.get(link.source) || 0;
			const tOff = tgtOffsets.get(link.target) || 0;

			layoutLinks.push({
				source: link.source,
				target: link.target,
				value: link.value,
				sy: srcNode.y + sOff + srcBand / 2,
				ty: tgtNode.y + tOff + tgtBand / 2,
				thickness,
				highlighted: false,
			});

			srcOffsets.set(link.source, sOff + srcBand);
			tgtOffsets.set(link.target, tOff + tgtBand);
		}

		return { nodes: allNodes, links: layoutLinks, nodeMap, height: computedH };
	});

	// ---------------------------------------------------------------------------
	// Link path
	// ---------------------------------------------------------------------------

	function linkPath(link: LayoutLink): string {
		const srcNode = layout.nodeMap.get(link.source);
		const tgtNode = layout.nodeMap.get(link.target);
		if (!srcNode || !tgtNode) return '';

		const x0 = srcNode.x + srcNode.w;
		const y0 = link.sy;  // already centered
		const x1 = tgtNode.x;
		const y1 = link.ty;  // already centered
		const cx = (x0 + x1) / 2;

		return `M${x0},${y0} C${cx},${y0} ${cx},${y1} ${x1},${y1}`;
	}

	function linkWidth(link: LayoutLink): number {
		return link.thickness;
	}

	function isLinkConnected(link: LayoutLink, nodeId: string): boolean {
		return link.source === nodeId || link.target === nodeId;
	}

	function linkColor(link: LayoutLink): string {
		const protoNode = layout.nodeMap.get(link.source);
		if (protoNode?.type === 'protocol') return protoNode.color;
		const tgtProto = layout.nodeMap.get(link.target);
		if (tgtProto?.type === 'protocol') return tgtProto.color;
		return 'var(--accent)';
	}

	// ---------------------------------------------------------------------------
	// Formatting
	// ---------------------------------------------------------------------------

	function formatBytes(b: number): string {
		if (b >= 1_073_741_824) return `${(b / 1_073_741_824).toFixed(1)} GB`;
		if (b >= 1_048_576) return `${(b / 1_048_576).toFixed(1)} MB`;
		if (b >= 1024) return `${(b / 1024).toFixed(1)} KB`;
		return `${b} B`;
	}

	function truncateLabel(label: string, maxLen: number = 16): string {
		if (label.length <= maxLen) return label;
		return label.slice(0, maxLen - 1) + '\u2026';
	}
</script>

{#if sources.length === 0 && protocols.length === 0 && destinations.length === 0}
	<div class="sankey-empty">
		<p class="text-muted">No flow data available for this time range</p>
	</div>
{:else}
	<div class="sankey-wrap" bind:clientWidth={chartWidth}>
		<!-- Column headers -->
		<div class="sankey-headers" style="--col1-x: {PADDING}px; --col2-x: {chartWidth / 2 - COL_WIDTH / 2}px; --col3-x: {chartWidth - COL_WIDTH - PADDING}px;">
			<span class="sankey-col-title" style="left: {PADDING}px;">Sources</span>
			<span class="sankey-col-title" style="left: {chartWidth / 2 - COL_WIDTH / 2}px;">Protocols</span>
			<span class="sankey-col-title" style="left: {chartWidth - COL_WIDTH - PADDING}px;">Destinations</span>
		</div>

		<svg viewBox="0 0 {chartWidth} {layout.height}" width="100%" height={layout.height}>
			<!-- Links -->
			{#each layout.links as link}
				{@const connected = hoveredNode ? isLinkConnected(link, hoveredNode) : true}
				<path
					d={linkPath(link)}
					fill="none"
					stroke={linkColor(link)}
					stroke-width={linkWidth(link)}
					opacity={hoveredNode ? (connected ? 0.6 : 0.08) : 0.3}
					style="transition: opacity 0.2s;"
				/>
			{/each}

			<!-- Nodes -->
			{#each layout.nodes as node}
				{@const isHovered = hoveredNode === node.id}
				{@const isConnected = hoveredNode ? layout.links.some((l) => isLinkConnected(l, hoveredNode!) && isLinkConnected(l, node.id)) || hoveredNode === node.id : true}
				<g
					role="button"
					tabindex="0"
					style="cursor: {node.type === 'source' ? 'alias' : 'pointer'};"
					onmouseenter={() => (hoveredNode = node.id)}
					onmouseleave={() => (hoveredNode = null)}
					onclick={() => onNodeClick?.(node.type, node.id)}
					onkeydown={(e) => { if (e.key === 'Enter') onNodeClick?.(node.type, node.id); }}
				>
					<rect
						x={node.x}
						y={node.y}
						width={node.w}
						height={node.h}
						rx="4"
						fill={node.color}
						opacity={hoveredNode ? (isConnected ? 1 : 0.2) : 0.85}
						stroke={isHovered ? 'var(--text-primary)' : 'none'}
						stroke-width="1.5"
						style="transition: opacity 0.2s;"
					/>
					<!-- Label -->
					{#if node.h >= 16}
						<text
							x={node.x + node.w / 2}
							y={node.y + node.h / 2 + 4}
							text-anchor="middle"
							fill="#fff"
							font-size="12"
							font-weight="600"
							opacity={hoveredNode ? (isConnected ? 1 : 0.3) : 1}
							style="pointer-events: none;"
						>
							{truncateLabel(node.label, 14)}
						</text>
					{/if}
				</g>
			{/each}
		</svg>

		<!-- Hover tooltip -->
		{#if hoveredNode}
			{@const node = layout.nodeMap.get(hoveredNode)}
			{#if node}
				<div
					class="sankey-tooltip"
					style="left: {node.x + node.w / 2}px; top: {Math.max(0, node.y - 8)}px;"
				>
					<div class="tooltip-label">{node.label}</div>
					<div class="tooltip-value">{formatBytes(node.value)}</div>
					{#if node.country}
						<div class="tooltip-country">{node.country}</div>
					{/if}
				</div>
			{/if}
		{/if}
	</div>
{/if}

<style>
	.sankey-wrap {
		position: relative;
		width: 100%;
	}

	.sankey-headers {
		position: relative;
		height: 24px;
		margin-bottom: var(--space-xs);
	}

	.sankey-col-title {
		position: absolute;
		top: 0;
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.sankey-empty {
		padding: var(--space-xl);
		text-align: center;
	}

	.sankey-tooltip {
		position: absolute;
		transform: translate(-50%, -100%);
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-xs) var(--space-sm);
		pointer-events: none;
		z-index: 10;
		white-space: nowrap;
	}

	.tooltip-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-primary);
	}

	.tooltip-value {
		font-size: var(--text-xs);
		color: var(--text-secondary);
		font-family: var(--font-mono);
	}

	.tooltip-country {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}
</style>
