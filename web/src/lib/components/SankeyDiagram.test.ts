import { describe, it, expect } from 'vitest';

/**
 * Tests for SankeyDiagram.svelte pure logic.
 * SVG rendering requires a real DOM; we test layout and formatting functions.
 */

// Reproduce constants and functions from the component
const MIN_NODE_H = 20;
const NODE_PAD = 8;

const PROTO_COLORS: Record<string, string> = {
	tcp: 'var(--cyan)',
	udp: 'var(--green)',
	icmp: 'var(--amber)',
	tls: 'var(--purple)',
	dns: 'var(--amber)',
	http: 'var(--blue)',
	ssh: 'var(--red)',
};

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

interface SankeyNode {
	id: string;
	label: string;
	value: number;
	country?: string;
}

interface LayoutNode {
	id: string; y: number; h: number; type: string;
}

function layoutNodes(nodes: SankeyNode[], chartH: number): LayoutNode[] {
	if (nodes.length === 0) return [];
	const totalValue = Math.max(1, nodes.reduce((s, n) => s + n.value, 0));
	const availH = chartH - (nodes.length - 1) * NODE_PAD - 40; // 2*PADDING
	let y = 20;
	return nodes.map((n) => {
		const h = Math.max(MIN_NODE_H, (n.value / totalValue) * availH);
		const node = { id: n.id, y, h, type: 'source' };
		y += h + NODE_PAD;
		return node;
	});
}

describe('SankeyDiagram logic', () => {
	describe('formatBytes', () => {
		it('formats bytes', () => expect(formatBytes(500)).toBe('500 B'));
		it('formats KB', () => expect(formatBytes(2048)).toBe('2.0 KB'));
		it('formats MB', () => expect(formatBytes(5 * 1048576)).toBe('5.0 MB'));
		it('formats GB', () => expect(formatBytes(2 * 1073741824)).toBe('2.0 GB'));
	});

	describe('truncateLabel', () => {
		it('returns short labels unchanged', () => expect(truncateLabel('TCP', 16)).toBe('TCP'));
		it('truncates long labels with ellipsis', () => {
			const result = truncateLabel('AS15169 Google LLC', 14);
			expect(result.length).toBe(14);
			expect(result.endsWith('\u2026')).toBe(true);
		});
	});

	describe('protocol colors', () => {
		it('has color for tcp', () => expect(PROTO_COLORS['tcp']).toBe('var(--cyan)'));
		it('has color for udp', () => expect(PROTO_COLORS['udp']).toBe('var(--green)'));
		it('has color for tls', () => expect(PROTO_COLORS['tls']).toBe('var(--purple)'));
		it('returns undefined for unknown protocols', () => expect(PROTO_COLORS['ftp']).toBeUndefined());
	});

	describe('layoutNodes', () => {
		it('returns empty for empty input', () => {
			expect(layoutNodes([], 400)).toEqual([]);
		});

		it('positions nodes with minimum height', () => {
			const nodes = [
				{ id: 'big', label: 'Big', value: 10000 },
				{ id: 'tiny', label: 'Tiny', value: 1 },
			];
			const result = layoutNodes(nodes, 400);
			expect(result).toHaveLength(2);
			expect(result[1].h).toBeGreaterThanOrEqual(MIN_NODE_H);
		});

		it('stacks nodes with padding', () => {
			const nodes = [
				{ id: 'a', label: 'A', value: 100 },
				{ id: 'b', label: 'B', value: 100 },
			];
			const result = layoutNodes(nodes, 400);
			expect(result[1].y).toBe(result[0].y + result[0].h + NODE_PAD);
		});
	});

	describe('link aggregation', () => {
		it('aggregates duplicate source→target links', () => {
			const links = [
				{ source: 'tcp', target: 'Google', value: 100 },
				{ source: 'tcp', target: 'Google', value: 200 },
				{ source: 'udp', target: 'Google', value: 50 },
			];
			const linkMap = new Map<string, { source: string; target: string; value: number }>();
			for (const link of links) {
				const key = `${link.source}→${link.target}`;
				if (linkMap.has(key)) {
					linkMap.get(key)!.value += link.value;
				} else {
					linkMap.set(key, { ...link });
				}
			}
			const aggregated = [...linkMap.values()];
			expect(aggregated).toHaveLength(2);
			const tcpGoogle = aggregated.find((l) => l.source === 'tcp');
			expect(tcpGoogle?.value).toBe(300);
		});
	});
});
