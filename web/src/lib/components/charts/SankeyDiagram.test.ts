import { describe, it, expect } from 'vitest';

/**
 * Tests for SankeyDiagram logic.
 *
 * The SankeyDiagram.svelte component uses Svelte 5 runes ($derived, $state)
 * and SVG rendering that is difficult to fully render in a jsdom test
 * environment.  Instead we extract and test the pure logic that lives inside
 * the component: column layout, node positioning, link path generation,
 * value formatting, color assignment, sort ordering, and label truncation.
 */

// ---------------------------------------------------------------------------
// Reproduced types and constants from SankeyDiagram.svelte
// ---------------------------------------------------------------------------

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

interface PositionedNode extends SankeyNode {
	x: number;
	y: number;
	w: number;
	h: number;
	color: string;
}

const NODE_WIDTH = 20;
const NODE_PADDING = 8;
const MIN_NODE_HEIGHT = 4;
const COLUMN_LABEL_PADDING = 60;

const GROUP_COLORS: Record<string, string> = {
	source: '#58a6ff',
	protocol: '#3fb950',
	destination: '#d29922',
};

// ---------------------------------------------------------------------------
// Reproduced pure logic from SankeyDiagram.svelte
// ---------------------------------------------------------------------------

/** Compute positioned nodes for a single column — mirrors layoutColumn() */
function layoutColumn(
	columnNodes: SankeyNode[],
	xPos: number,
	availableHeight: number
): PositionedNode[] {
	if (columnNodes.length === 0) return [];

	const totalValue = columnNodes.reduce((sum, n) => sum + n.value, 0);
	if (totalValue === 0) return [];

	const totalPadding = (columnNodes.length - 1) * NODE_PADDING;
	const usableHeight = availableHeight - totalPadding;

	const rawHeights = columnNodes.map((n) => (n.value / totalValue) * usableHeight);

	let minHeightCount = 0;
	let minHeightTotal = 0;
	for (const h of rawHeights) {
		if (h < MIN_NODE_HEIGHT) {
			minHeightCount++;
			minHeightTotal += MIN_NODE_HEIGHT - h;
		}
	}

	const scaleFactor =
		minHeightCount > 0
			? (usableHeight - minHeightCount * MIN_NODE_HEIGHT) / (usableHeight - minHeightTotal)
			: 1;

	const heights = rawHeights.map((h) =>
		h < MIN_NODE_HEIGHT ? MIN_NODE_HEIGHT : h * scaleFactor
	);

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

/** Sort nodes by value descending — mirrors the $derived sort logic */
function sortByValueDesc(nodes: SankeyNode[]): SankeyNode[] {
	return nodes.slice().sort((a, b) => b.value - a.value);
}

/** Truncate label text — mirrors truncateLabel() */
function truncateLabel(text: string, maxLen: number): string {
	if (text.length <= maxLen) return text;
	return text.slice(0, maxLen - 1) + '\u2026';
}

/** Compute maximum label characters — mirrors the $derived calculation */
function maxLabelChars(): number {
	return Math.max(6, Math.floor(COLUMN_LABEL_PADDING / 7));
}

/** Build a cubic Bezier link path — mirrors the path construction in computedLinks */
function buildLinkPath(
	srcX: number,
	srcW: number,
	srcY: number,
	tgtX: number,
	tgtY: number,
	linkHeight: number
): string {
	const x0 = srcX + srcW;
	const y0 = srcY;
	const x1 = tgtX;
	const y1 = tgtY;
	const cpx = (x0 + x1) / 2;

	return [
		`M ${x0} ${y0}`,
		`C ${cpx} ${y0}, ${cpx} ${y1}, ${x1} ${y1}`,
		`L ${x1} ${y1 + linkHeight}`,
		`C ${cpx} ${y1 + linkHeight}, ${cpx} ${y0 + linkHeight}, ${x0} ${y0 + linkHeight}`,
		'Z',
	].join(' ');
}

/** Get color for a group — mirrors GROUP_COLORS lookup */
function groupColor(group: string): string {
	return GROUP_COLORS[group] || '#8b949e';
}

/** Format value — mirrors the default formatValue prop */
function formatValue(v: number): string {
	return v.toLocaleString();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('SankeyDiagram logic', () => {
	// -- layoutColumn ---------------------------------------------------------

	describe('layoutColumn', () => {
		it('returns empty array for empty node list', () => {
			expect(layoutColumn([], 0, 400)).toEqual([]);
		});

		it('returns empty array when all node values are zero', () => {
			const nodes: SankeyNode[] = [
				{ id: 'a', label: 'A', group: 'source', value: 0 },
				{ id: 'b', label: 'B', group: 'source', value: 0 },
			];
			expect(layoutColumn(nodes, 0, 400)).toEqual([]);
		});

		it('positions a single node to fill the full height', () => {
			const nodes: SankeyNode[] = [
				{ id: 'a', label: 'A', group: 'source', value: 100 },
			];
			const result = layoutColumn(nodes, 50, 400);

			expect(result).toHaveLength(1);
			expect(result[0].y).toBe(0);
			// Single node with no padding deducted (0 gaps): h = 400
			expect(result[0].h).toBe(400);
			expect(result[0].x).toBe(50);
			expect(result[0].w).toBe(NODE_WIDTH);
		});

		it('distributes heights proportional to value with two nodes', () => {
			const nodes: SankeyNode[] = [
				{ id: 'a', label: 'A', group: 'source', value: 300 },
				{ id: 'b', label: 'B', group: 'source', value: 100 },
			];
			const result = layoutColumn(nodes, 0, 400);

			expect(result).toHaveLength(2);
			// usableHeight = 400 - 8 = 392; A gets 75% = 294, B gets 25% = 98
			expect(result[0].h).toBeCloseTo(294, 0);
			expect(result[1].h).toBeCloseTo(98, 0);
		});

		it('enforces MIN_NODE_HEIGHT for very small nodes', () => {
			const nodes: SankeyNode[] = [
				{ id: 'big', label: 'Big', group: 'source', value: 10000 },
				{ id: 'tiny', label: 'Tiny', group: 'source', value: 1 },
			];
			const result = layoutColumn(nodes, 0, 400);

			// The tiny node should have at least MIN_NODE_HEIGHT
			const tinyNode = result.find((n) => n.id === 'tiny');
			expect(tinyNode).toBeDefined();
			expect(tinyNode!.h).toBeGreaterThanOrEqual(MIN_NODE_HEIGHT);
		});

		it('stacks nodes vertically with correct padding between them', () => {
			const nodes: SankeyNode[] = [
				{ id: 'a', label: 'A', group: 'source', value: 50 },
				{ id: 'b', label: 'B', group: 'source', value: 50 },
			];
			const result = layoutColumn(nodes, 0, 400);

			// Second node should start at first node's bottom + NODE_PADDING
			expect(result[1].y).toBeCloseTo(result[0].h + NODE_PADDING, 0);
		});

		it('assigns correct color based on group', () => {
			const nodes: SankeyNode[] = [
				{ id: 'a', label: 'A', group: 'protocol', value: 100 },
			];
			const result = layoutColumn(nodes, 0, 200);
			expect(result[0].color).toBe('#3fb950');
		});

		it('assigns fallback color for unknown group', () => {
			const nodes: SankeyNode[] = [
				{ id: 'a', label: 'A', group: 'unknown' as SankeyNode['group'], value: 100 },
			];
			const result = layoutColumn(nodes, 0, 200);
			expect(result[0].color).toBe('#8b949e');
		});

		it('handles three nodes with varying sizes', () => {
			const nodes: SankeyNode[] = [
				{ id: 'a', label: 'A', group: 'source', value: 500 },
				{ id: 'b', label: 'B', group: 'source', value: 300 },
				{ id: 'c', label: 'C', group: 'source', value: 200 },
			];
			const result = layoutColumn(nodes, 10, 400);

			expect(result).toHaveLength(3);
			// All nodes should be positioned at x = 10
			for (const n of result) {
				expect(n.x).toBe(10);
			}
			// Heights should sum to availableHeight minus padding
			const totalH = result.reduce((s, n) => s + n.h, 0);
			const totalPad = (result.length - 1) * NODE_PADDING;
			expect(totalH + totalPad).toBeCloseTo(400, 0);
		});
	});

	// -- sortByValueDesc ------------------------------------------------------

	describe('sortByValueDesc', () => {
		it('sorts nodes in descending order by value', () => {
			const nodes: SankeyNode[] = [
				{ id: 'a', label: 'A', group: 'source', value: 10 },
				{ id: 'b', label: 'B', group: 'source', value: 50 },
				{ id: 'c', label: 'C', group: 'source', value: 30 },
			];
			const sorted = sortByValueDesc(nodes);
			expect(sorted[0].id).toBe('b');
			expect(sorted[1].id).toBe('c');
			expect(sorted[2].id).toBe('a');
		});

		it('does not mutate the original array', () => {
			const nodes: SankeyNode[] = [
				{ id: 'a', label: 'A', group: 'source', value: 10 },
				{ id: 'b', label: 'B', group: 'source', value: 50 },
			];
			const sorted = sortByValueDesc(nodes);
			expect(nodes[0].id).toBe('a');
			expect(sorted[0].id).toBe('b');
		});

		it('returns empty array for empty input', () => {
			expect(sortByValueDesc([])).toEqual([]);
		});
	});

	// -- truncateLabel --------------------------------------------------------

	describe('truncateLabel', () => {
		it('returns text unchanged when shorter than maxLen', () => {
			expect(truncateLabel('Hello', 10)).toBe('Hello');
		});

		it('returns text unchanged when equal to maxLen', () => {
			expect(truncateLabel('Hello', 5)).toBe('Hello');
		});

		it('truncates and appends ellipsis when text exceeds maxLen', () => {
			expect(truncateLabel('192.168.1.100', 8)).toBe('192.168\u2026');
		});

		it('handles empty string', () => {
			expect(truncateLabel('', 10)).toBe('');
		});

		it('truncates to single char plus ellipsis for maxLen of 2', () => {
			expect(truncateLabel('Hello', 2)).toBe('H\u2026');
		});
	});

	// -- maxLabelChars --------------------------------------------------------

	describe('maxLabelChars', () => {
		it('computes correct max chars for default COLUMN_LABEL_PADDING', () => {
			// COLUMN_LABEL_PADDING = 60; Math.max(6, Math.floor(60 / 7)) = Math.max(6, 8) = 8
			expect(maxLabelChars()).toBe(8);
		});
	});

	// -- groupColor -----------------------------------------------------------

	describe('groupColor', () => {
		it('returns blue for source group', () => {
			expect(groupColor('source')).toBe('#58a6ff');
		});

		it('returns green for protocol group', () => {
			expect(groupColor('protocol')).toBe('#3fb950');
		});

		it('returns yellow for destination group', () => {
			expect(groupColor('destination')).toBe('#d29922');
		});

		it('returns fallback gray for unknown group', () => {
			expect(groupColor('other')).toBe('#8b949e');
		});

		it('returns fallback gray for empty string group', () => {
			expect(groupColor('')).toBe('#8b949e');
		});
	});

	// -- buildLinkPath --------------------------------------------------------

	describe('buildLinkPath', () => {
		it('generates a valid SVG path string', () => {
			const path = buildLinkPath(100, 20, 50, 300, 80, 30);
			expect(path).toContain('M 120 50');
			expect(path).toContain('C');
			expect(path).toContain('L 300 110');
			expect(path).toContain('Z');
		});

		it('control point x is midpoint between source right and target left', () => {
			const path = buildLinkPath(100, 20, 0, 300, 0, 10);
			// x0 = 120, x1 = 300, cpx = (120+300)/2 = 210
			expect(path).toContain('210');
		});

		it('handles zero link height producing a collapsed path', () => {
			const path = buildLinkPath(0, 20, 0, 200, 0, 0);
			// y0 = 0, linkHeight = 0, so top and bottom edges have same y
			expect(path).toContain('M 20 0');
			expect(path).toContain('L 200 0');
		});
	});

	// -- formatValue ----------------------------------------------------------

	describe('formatValue', () => {
		it('formats integers with locale separators', () => {
			const result = formatValue(1000);
			// toLocaleString output is locale-dependent, but should not be empty
			expect(result).toBeTruthy();
			expect(result.length).toBeGreaterThan(0);
		});

		it('formats zero as "0"', () => {
			expect(formatValue(0)).toBe('0');
		});

		it('formats negative numbers', () => {
			const result = formatValue(-500);
			expect(result).toContain('500');
		});
	});
});
