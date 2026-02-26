<script lang="ts">
	/**
	 * SankeyDiagram — Pure SVG Sankey diagram for traffic flow visualization.
	 *
	 * Renders a 3-column layout: Sources (left) -> Protocols (center) -> Destinations (right).
	 * Node heights are proportional to total bytes. Links are cubic Bezier paths
	 * with widths proportional to the link value.
	 *
	 * Props:
	 *   nodes       — Array of SankeyNode entries (id, label, group, value)
	 *   links       — Array of SankeyLink entries (source id, target id, value)
	 *   width       — SVG width in pixels (default 800)
	 *   height      — SVG height in pixels (default 400)
	 *   formatValue — Value formatter function
	 */

	interface SankeyNode {
		id: string;
		label: string;
		group: 'source' | 'protocol' | 'destination';
		value: number;
	}

	interface SankeyLink {
		source: string;
		target: string;
		value: number;
	}

	interface Props {
		nodes: SankeyNode[];
		links: SankeyLink[];
		width?: number;
		height?: number;
		formatValue?: (v: number) => string;
	}

	let {
		nodes = [],
		links = [],
		width = 800,
		height = 400,
		formatValue = (v: number) => v.toLocaleString(),
	}: Props = $props();

	// Layout constants
	const NODE_WIDTH = 20;
	const NODE_RADIUS = 4;
	const NODE_PADDING = 8;
	const COLUMN_LABEL_PADDING = 60;
	const MIN_NODE_HEIGHT = 4;

	// Colors by group
	const GROUP_COLORS: Record<string, string> = {
		source: '#58a6ff',
		protocol: '#3fb950',
		destination: '#d29922',
	};

	// Hover state
	let hoveredNodeId = $state<string | null>(null);
	let hoveredLinkIdx = $state<number | null>(null);
	let tooltipText = $state('');
	let tooltipX = $state(0);
	let tooltipY = $state(0);
	let showTooltip = $state(false);

	// Usable drawing area
	let drawLeft = $derived(COLUMN_LABEL_PADDING);
	let drawRight = $derived(width - COLUMN_LABEL_PADDING);
	let drawWidth = $derived(drawRight - drawLeft);

	// Column x-positions (center of node rectangle)
	let columnX = $derived<Record<string, number>>({
		source: drawLeft,
		protocol: drawLeft + drawWidth / 2 - NODE_WIDTH / 2,
		destination: drawRight - NODE_WIDTH,
	});

	// Split nodes into columns sorted by value descending
	let sourceNodes = $derived(
		nodes
			.filter((n) => n.group === 'source')
			.slice()
			.sort((a, b) => b.value - a.value)
	);
	let protocolNodes = $derived(
		nodes
			.filter((n) => n.group === 'protocol')
			.slice()
			.sort((a, b) => b.value - a.value)
	);
	let destinationNodes = $derived(
		nodes
			.filter((n) => n.group === 'destination')
			.slice()
			.sort((a, b) => b.value - a.value)
	);

	// Compute positioned nodes for a single column
	function layoutColumn(
		columnNodes: SankeyNode[],
		xPos: number,
		availableHeight: number
	): PositionedNode[] {
		if (columnNodes.length === 0) return [];

		const totalValue = columnNodes.reduce((sum, n) => sum + n.value, 0);
		if (totalValue === 0) return [];

		// Total space reserved for padding
		const totalPadding = (columnNodes.length - 1) * NODE_PADDING;
		const usableHeight = availableHeight - totalPadding;

		// Compute raw heights
		const rawHeights = columnNodes.map((n) => (n.value / totalValue) * usableHeight);

		// Enforce minimum node heights and compute scale correction
		let minHeightCount = 0;
		let minHeightTotal = 0;
		for (const h of rawHeights) {
			if (h < MIN_NODE_HEIGHT) {
				minHeightCount++;
				minHeightTotal += MIN_NODE_HEIGHT - h;
			}
		}

		// Redistribute space: shrink large nodes to make room for minimum-height nodes
		const scaleFactor =
			minHeightCount > 0 ? (usableHeight - minHeightCount * MIN_NODE_HEIGHT) / (usableHeight - minHeightTotal) : 1;

		const heights = rawHeights.map((h) => (h < MIN_NODE_HEIGHT ? MIN_NODE_HEIGHT : h * scaleFactor));

		// Stack nodes vertically
		let yOffset = 0;
		return columnNodes.map((node, i) => {
			const nodeHeight = heights[i];
			const y = yOffset;
			yOffset += nodeHeight + NODE_PADDING;
			return {
				...node,
				x: xPos,
				y,
				w: NODE_WIDTH,
				h: nodeHeight,
				color: GROUP_COLORS[node.group] || '#8b949e',
			};
		});
	}

	interface PositionedNode extends SankeyNode {
		x: number;
		y: number;
		w: number;
		h: number;
		color: string;
	}

	// Layout all columns
	let positionedSources = $derived(layoutColumn(sourceNodes, columnX.source, height));
	let positionedProtocols = $derived(layoutColumn(protocolNodes, columnX.protocol, height));
	let positionedDestinations = $derived(layoutColumn(destinationNodes, columnX.destination, height));

	// Node position lookup by ID
	let nodeMap = $derived.by(() => {
		const map = new Map<string, PositionedNode>();
		for (const n of positionedSources) map.set(n.id, n);
		for (const n of positionedProtocols) map.set(n.id, n);
		for (const n of positionedDestinations) map.set(n.id, n);
		return map;
	});

	// Build link port offsets: track cumulative offset on each side of each node
	interface ComputedLink {
		sourceNode: PositionedNode;
		targetNode: PositionedNode;
		value: number;
		sourceY: number;
		targetY: number;
		linkHeight: number;
		path: string;
		color: string;
	}

	let computedLinks = $derived.by(() => {
		if (links.length === 0 || nodeMap.size === 0) return [];

		// Track the cumulative y-offset on the right side of source nodes
		// and the left side of target nodes
		const sourceRightOffset = new Map<string, number>();
		const targetLeftOffset = new Map<string, number>();

		// Initialize offsets to node top
		for (const [id, node] of nodeMap) {
			sourceRightOffset.set(id, node.y);
			targetLeftOffset.set(id, node.y);
		}

		// Sort links by value descending for consistent ordering
		const sortedLinks = links.slice().sort((a, b) => b.value - a.value);

		const result: ComputedLink[] = [];

		for (const link of sortedLinks) {
			const srcNode = nodeMap.get(link.source);
			const tgtNode = nodeMap.get(link.target);
			if (!srcNode || !tgtNode) continue;

			// Compute link height proportional to node height
			const linkHeight = srcNode.value > 0 ? (link.value / srcNode.value) * srcNode.h : 0;
			if (linkHeight <= 0) continue;

			const sourceY = sourceRightOffset.get(link.source) ?? srcNode.y;
			const targetY = targetLeftOffset.get(link.target) ?? tgtNode.y;

			// Update offsets
			sourceRightOffset.set(link.source, sourceY + linkHeight);
			targetLeftOffset.set(link.target, targetY + linkHeight);

			// Build cubic Bezier path
			const x0 = srcNode.x + srcNode.w;
			const y0 = sourceY;
			const x1 = tgtNode.x;
			const y1 = targetY;
			const cpx = (x0 + x1) / 2;

			const path = [
				`M ${x0} ${y0}`,
				`C ${cpx} ${y0}, ${cpx} ${y1}, ${x1} ${y1}`,
				`L ${x1} ${y1 + linkHeight}`,
				`C ${cpx} ${y1 + linkHeight}, ${cpx} ${y0 + linkHeight}, ${x0} ${y0 + linkHeight}`,
				'Z',
			].join(' ');

			result.push({
				sourceNode: srcNode,
				targetNode: tgtNode,
				value: link.value,
				sourceY,
				targetY,
				linkHeight,
				path,
				color: srcNode.color,
			});
		}

		return result;
	});

	// Determine if a node is connected to the hovered element
	function isNodeHighlighted(nodeId: string): boolean {
		if (hoveredNodeId === nodeId) return true;
		if (hoveredLinkIdx !== null) {
			const link = computedLinks[hoveredLinkIdx];
			if (link) {
				return link.sourceNode.id === nodeId || link.targetNode.id === nodeId;
			}
		}
		if (hoveredNodeId !== null) {
			// Highlight nodes connected to hovered node via links
			for (const link of computedLinks) {
				if (link.sourceNode.id === hoveredNodeId && link.targetNode.id === nodeId) return true;
				if (link.targetNode.id === hoveredNodeId && link.sourceNode.id === nodeId) return true;
			}
		}
		return false;
	}

	// Determine if a link is connected to the hovered node
	function isLinkHighlighted(linkIndex: number): boolean {
		if (hoveredLinkIdx === linkIndex) return true;
		if (hoveredNodeId !== null) {
			const link = computedLinks[linkIndex];
			if (link) {
				return link.sourceNode.id === hoveredNodeId || link.targetNode.id === hoveredNodeId;
			}
		}
		return false;
	}

	// Label text truncation
	function truncateLabel(text: string, maxLen: number): string {
		if (text.length <= maxLen) return text;
		return text.slice(0, maxLen - 1) + '\u2026';
	}

	// Maximum label characters based on available space
	let maxLabelChars = $derived(Math.max(6, Math.floor(COLUMN_LABEL_PADDING / 7)));

	// Event handlers
	function handleNodeHover(node: PositionedNode, event: MouseEvent) {
		hoveredNodeId = node.id;
		hoveredLinkIdx = null;
		tooltipText = `${node.label}: ${formatValue(node.value)}`;
		updateTooltipPosition(event);
		showTooltip = true;
	}

	function handleLinkHover(linkIndex: number, event: MouseEvent) {
		hoveredLinkIdx = linkIndex;
		hoveredNodeId = null;
		const link = computedLinks[linkIndex];
		if (link) {
			tooltipText = `${link.sourceNode.label} \u2192 ${link.targetNode.label}: ${formatValue(link.value)}`;
		}
		updateTooltipPosition(event);
		showTooltip = true;
	}

	function handleMouseLeave() {
		hoveredNodeId = null;
		hoveredLinkIdx = null;
		showTooltip = false;
	}

	function updateTooltipPosition(event: MouseEvent) {
		const target = event.currentTarget as SVGElement;
		const svgEl = target.closest('svg');
		if (!svgEl) return;
		const rect = svgEl.getBoundingClientRect();
		tooltipX = event.clientX - rect.left;
		tooltipY = event.clientY - rect.top;
	}

	function handleMouseMoveOnNode(event: MouseEvent) {
		updateTooltipPosition(event);
	}

	function handleMouseMoveOnLink(event: MouseEvent) {
		updateTooltipPosition(event);
	}

	// Compute whether we have any data
	let hasData = $derived(nodes.length > 0 && links.length > 0);
</script>

<div class="sankey-diagram" role="img" aria-label="Traffic flow Sankey diagram">
	{#if !hasData}
		<div class="chart-empty" style:width="{width}px" style:height="{height}px">
			<p>No flow data</p>
		</div>
	{:else}
		<div class="chart-container" style:position="relative">
			<svg {width} {height} viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet">
				<!-- Links layer (behind nodes) -->
				<g class="sankey-links">
					{#each computedLinks as link, i}
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<path
							d={link.path}
							fill={link.color}
							opacity={isLinkHighlighted(i) ? 0.5 : 0.25}
							class="sankey-link"
							onmouseenter={(e) => handleLinkHover(i, e)}
							onmousemove={handleMouseMoveOnLink}
							onmouseleave={handleMouseLeave}
						/>
					{/each}
				</g>

				<!-- Nodes layer -->
				<g class="sankey-nodes">
					<!-- Source nodes -->
					{#each positionedSources as node}
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<g
							class="sankey-node"
							class:dimmed={hoveredNodeId !== null && !isNodeHighlighted(node.id)}
							onmouseenter={(e) => handleNodeHover(node, e)}
							onmousemove={handleMouseMoveOnNode}
							onmouseleave={handleMouseLeave}
						>
							<rect
								x={node.x}
								y={node.y}
								width={node.w}
								height={node.h}
								rx={NODE_RADIUS}
								ry={NODE_RADIUS}
								fill={node.color}
							/>
							<text
								x={node.x + node.w + 6}
								y={node.y + node.h / 2}
								text-anchor="start"
								dominant-baseline="middle"
								class="node-label source-label"
							>
								{truncateLabel(node.label, maxLabelChars)}
							</text>
						</g>
					{/each}

					<!-- Protocol nodes -->
					{#each positionedProtocols as node}
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<g
							class="sankey-node"
							class:dimmed={hoveredNodeId !== null && !isNodeHighlighted(node.id)}
							onmouseenter={(e) => handleNodeHover(node, e)}
							onmousemove={handleMouseMoveOnNode}
							onmouseleave={handleMouseLeave}
						>
							<rect
								x={node.x}
								y={node.y}
								width={node.w}
								height={node.h}
								rx={NODE_RADIUS}
								ry={NODE_RADIUS}
								fill={node.color}
							/>
							<text
								x={node.x + node.w / 2}
								y={node.y + node.h / 2}
								text-anchor="middle"
								dominant-baseline="middle"
								class="node-label protocol-label"
							>
								{truncateLabel(node.label, maxLabelChars)}
							</text>
						</g>
					{/each}

					<!-- Destination nodes -->
					{#each positionedDestinations as node}
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<g
							class="sankey-node"
							class:dimmed={hoveredNodeId !== null && !isNodeHighlighted(node.id)}
							onmouseenter={(e) => handleNodeHover(node, e)}
							onmousemove={handleMouseMoveOnNode}
							onmouseleave={handleMouseLeave}
						>
							<rect
								x={node.x}
								y={node.y}
								width={node.w}
								height={node.h}
								rx={NODE_RADIUS}
								ry={NODE_RADIUS}
								fill={node.color}
							/>
							<text
								x={node.x - 6}
								y={node.y + node.h / 2}
								text-anchor="end"
								dominant-baseline="middle"
								class="node-label destination-label"
							>
								{truncateLabel(node.label, maxLabelChars)}
							</text>
						</g>
					{/each}
				</g>

				<!-- Column headers -->
				<text x={columnX.source + NODE_WIDTH / 2} y={-8} text-anchor="middle" class="column-header">
					Sources
				</text>
				<text x={columnX.protocol + NODE_WIDTH / 2} y={-8} text-anchor="middle" class="column-header">
					Protocols
				</text>
				<text x={columnX.destination + NODE_WIDTH / 2} y={-8} text-anchor="middle" class="column-header">
					Destinations
				</text>
			</svg>

			<!-- Tooltip overlay -->
			{#if showTooltip}
				<div
					class="sankey-tooltip"
					style:left="{tooltipX}px"
					style:top="{tooltipY - 36}px"
				>
					{tooltipText}
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.sankey-diagram {
		display: flex;
		flex-direction: column;
		align-items: center;
	}

	.chart-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-md);
		color: var(--text-muted);
		font-size: var(--text-sm);
	}

	.chart-container {
		position: relative;
	}

	svg {
		display: block;
		overflow: visible;
	}

	.sankey-link {
		cursor: pointer;
		transition: opacity 0.15s ease;
	}

	.sankey-node {
		cursor: pointer;
		transition: opacity 0.15s ease;
	}

	.sankey-node.dimmed {
		opacity: 0.35;
	}

	.sankey-node rect {
		stroke: var(--bg-primary);
		stroke-width: 1;
	}

	.node-label {
		fill: var(--text-secondary);
		font-size: 11px;
		font-family: var(--font-mono);
		pointer-events: none;
	}

	.protocol-label {
		fill: var(--text-primary);
		font-size: 10px;
		font-weight: 600;
	}

	.column-header {
		fill: var(--text-muted);
		font-size: 11px;
		font-family: var(--font-sans);
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.sankey-tooltip {
		position: absolute;
		transform: translateX(-50%);
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		padding: 4px 10px;
		pointer-events: none;
		font-size: var(--text-xs);
		font-family: var(--font-mono);
		color: var(--text-primary);
		white-space: nowrap;
		z-index: 10;
	}
</style>
