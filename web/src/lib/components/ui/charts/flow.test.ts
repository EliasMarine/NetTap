import { describe, it, expect } from 'vitest';
import { flowData, flowLayout, dodgeLabels, share, splitText, OTHER_ID, type FlowInput, type PlacedNode } from './flow';

const MB = 1_048_576;
const node = (id: string, value = 0, label = id) => ({ id, label, value });
const link = (source: string, target: string, value: number) => ({ source, target, value });

/** Two devices, TCP and UDP, two destinations that cover 80 MB of the 100 MB sent. */
const INPUT: FlowInput = {
	sources: [node('192.168.1.10', 60 * MB), node('192.168.1.20', 40 * MB)],
	protocols: [node('tcp', 70 * MB, 'TCP'), node('udp', 30 * MB, 'UDP')],
	destinations: [{ ...node('AS714 Apple Inc.', 50 * MB, 'Apple Inc.'), country: 'US' }, node('Unknown', 30 * MB)],
	links: [
		link('192.168.1.10', 'tcp', 40 * MB),
		link('192.168.1.10', 'udp', 20 * MB),
		link('192.168.1.20', 'tcp', 30 * MB),
		link('192.168.1.20', 'udp', 10 * MB),
		link('tcp', 'AS714 Apple Inc.', 40 * MB),
		link('udp', 'AS714 Apple Inc.', 10 * MB),
		link('tcp', 'Unknown', 20 * MB),
		link('udp', 'Unknown', 10 * MB),
	],
};

const sum = (nodes: { value: number }[]) => nodes.reduce((a, n) => a + n.value, 0);
const close = (a: number, b: number) => expect(Math.abs(a - b)).toBeLessThan(1e-6);

/** n sources: one dominant, the rest tiny, all over TCP to one destination plus Other. */
function skewed(n: number): FlowInput {
	const ips = Array.from({ length: n }, (_, i) => `10.0.0.${i + 1}`);
	const values = ips.map((_, i) => (i === 0 ? 1000 * MB : 0.01 * MB));
	const total = values.reduce((a, v) => a + v, 0);
	return {
		sources: ips.map((ip, i) => node(ip, values[i])),
		protocols: [node('tcp', total, 'TCP')],
		destinations: [node('Google LLC', total * 0.5)],
		links: [...ips.map((ip, i) => link(ip, 'tcp', values[i])), link('tcp', 'Google LLC', total * 0.5)],
	};
}

describe('flowData', () => {
	it('adds an Other destinations node so every column sums to the same total', () => {
		const data = flowData(INPUT);
		expect(data.consistent).toBe(true);
		const other = data.destinations.at(-1)!;
		expect(other).toMatchObject({ id: OTHER_ID, label: 'Other destinations', other: true, value: 20 * MB });
		expect(other.split).toHaveLength(2);
		expect(other.split).toEqual(expect.arrayContaining([{ protocol: 'udp', value: 10 * MB }, { protocol: 'tcp', value: 10 * MB }]));
		expect(sum(data.sources)).toBe(100 * MB);
		expect(sum(data.protocols)).toBe(100 * MB);
		expect(sum(data.destinations)).toBe(100 * MB);
	});

	it('adds no Other when the destinations cover everything', () => {
		const data = flowData({ ...INPUT, links: [...INPUT.links, link('tcp', 'Unknown', 10 * MB), link('udp', 'Unknown', 10 * MB)] });
		expect(data.consistent).toBe(true);
		expect(data.destinations.some((d) => d.other)).toBe(false);
	});

	it('forgives a rounding error between the two searches', () => {
		const data = flowData({ ...INPUT, links: [...INPUT.links, link('tcp', 'Unknown', 10 * MB + 0.5), link('udp', 'Unknown', 10 * MB)] });
		expect(data.consistent).toBe(true);
	});

	it.each([
		['1 %', 0.7 * MB],
		['20 %', 14 * MB],
	])('keeps the reported values and draws no Other when the protocol column is %s short', (_, extra) => {
		const data = flowData({ ...INPUT, links: [...INPUT.links, link('tcp', 'Unknown', 10 * MB + extra)] });
		expect(data.consistent).toBe(false);
		expect(data.destinations.map((d) => d.value)).toEqual([50 * MB, 30 * MB]);
		expect(data.sources.map((d) => d.value)).toEqual([60 * MB, 40 * MB]);
		expect(data.protocols.map((d) => d.value)).toEqual([70 * MB, 30 * MB]);
	});

	it('drops links to unknown nodes, bad values and empty nodes', () => {
		const data = flowData({
			...INPUT,
			sources: [...INPUT.sources, node('192.168.1.99', 5 * MB)],
			links: [...INPUT.links, link('10.9.9.9', 'tcp', 99 * MB), link('tcp', 'Nowhere', 99 * MB), link('192.168.1.10', 'tcp', Number.NaN), link('192.168.1.20', 'udp', -5)],
		});
		expect(data.consistent).toBe(true);
		expect(data.sources.map((s) => s.id)).toEqual(['192.168.1.10', '192.168.1.20']);
		expect(sum(data.protocols)).toBe(100 * MB);
	});

	it('keeps TCP, UDP and ICMP on fixed colours whatever the order', () => {
		const protocols = ['udp', 'tcp', 'icmp', 'gre'];
		const a = flowData({
			sources: [node('a', 4)],
			protocols: protocols.map((p) => node(p, 1, p.toUpperCase())),
			destinations: [],
			links: protocols.map((p) => link('a', p, 1)),
		});
		expect([...a.colours.entries()].sort()).toEqual([['gre', 3], ['icmp', 5], ['tcp', 1], ['udp', 2]]);
	});

	it('handles no data at all', () => {
		const data = flowData({ sources: [], protocols: [], destinations: [], links: [] });
		expect(data).toMatchObject({ consistent: true, sources: [], protocols: [], destinations: [] });
		const layout = flowLayout(data, 1000);
		expect(layout.ribbons).toEqual([]);
		expect(JSON.stringify(layout)).not.toMatch(/NaN|Infinity/);
	});
});

describe('dodgeLabels', () => {
	const boxes = (ys: number[], hs: number[]) => ys.map((y, i) => [y - hs[i] / 2, y + hs[i] / 2]);
	const noOverlap = (ys: number[], hs: number[], height: number) => {
		const b = boxes(ys, hs);
		b.forEach(([top, bottom], i) => {
			expect(top).toBeGreaterThanOrEqual(-1e-9);
			expect(bottom).toBeLessThanOrEqual(height + 1e-9);
			if (i > 0) expect(top).toBeGreaterThanOrEqual(b[i - 1][1] + 4 - 1e-9);
		});
	};

	it('leaves well-spaced labels on their targets', () => {
		expect(dodgeLabels([20, 80, 140], [16, 16, 16], 200)).toEqual([20, 80, 140]);
	});

	it('spreads crowded labels of mixed heights without overlap, inside the chart', () => {
		const hs = [16, 24, 16, 24, 20, 30];
		const ys = dodgeLabels([5, 6, 7, 8, 9, 10], hs, 200);
		noOverlap(ys, hs, 200);
	});

	it('pushes labels at the bottom edge back inside', () => {
		const hs = [16, 16, 16];
		const ys = dodgeLabels([198, 199, 200], hs, 200);
		noOverlap(ys, hs, 200);
		expect(ys[2]).toBe(192);
	});
});

describe('flowLayout', () => {
	const bars = (nodes: PlacedNode[]) => nodes.reduce((a, n) => a + n.h, 0);

	it('draws all three columns on one scale', () => {
		const layout = flowLayout(flowData(INPUT), 1200);
		close(bars(layout.sources), bars(layout.protocols));
		close(bars(layout.protocols), bars(layout.destinations));
		const scale = layout.sources[0].h / layout.sources[0].value;
		[...layout.protocols, ...layout.destinations].forEach((n) => close(n.h / n.value, scale));
	});

	it("fits every column inside the chart, with each column's real gaps", () => {
		const three = flowData({
			sources: [node('a', 10), node('b', 10), node('c', 10)],
			protocols: [node('tcp', 10), node('udp', 10), node('icmp', 10)],
			destinations: [node('x', 10), node('y', 10), node('z', 10)],
			links: [link('a', 'tcp', 10), link('b', 'udp', 10), link('c', 'icmp', 10), link('tcp', 'x', 10), link('udp', 'y', 10), link('icmp', 'z', 10)],
		});
		for (const data of [three, flowData(skewed(10))]) {
			const layout = flowLayout(data, 1000);
			for (const col of [layout.sources, layout.protocols, layout.destinations]) {
				expect(col[0].y).toBeGreaterThanOrEqual(-1e-9);
				const last = col.at(-1)!;
				expect(last.y + last.h).toBeLessThanOrEqual(layout.height + 1e-9);
				col.slice(1).forEach((n, i) => expect(n.y).toBeGreaterThanOrEqual(col[i].y + col[i].h + 14 - 1e-9));
			}
		}
	});

	it("stacks ribbons flush: at every node they add up to its bar, in the far column's order", () => {
		const layout = flowLayout(flowData(INPUT), 1200);
		const scale = layout.sources[0].h / layout.sources[0].value;
		for (const n of [...layout.sources, ...layout.protocols, ...layout.destinations]) {
			const out = layout.ribbons.filter((r) => r.from === n.key);
			const into = layout.ribbons.filter((r) => r.to === n.key);
			if (out.length) close(out.reduce((a, r) => a + r.value * scale, 0), n.h);
			if (into.length) close(into.reduce((a, r) => a + r.value * scale, 0), n.h);
		}
		// The first device's ribbons leave in protocol order: TCP (largest) on top
		const first = layout.ribbons.filter((r) => r.from === layout.sources[0].key);
		expect(first.map((r) => r.to)).toEqual(['p:tcp', 'p:udp']);
		const tcpTop = Number(first[0].d.match(/^M[\d.]+,([\d.]+)/)![1]);
		const udpTop = Number(first[1].d.match(/^M[\d.]+,([\d.]+)/)![1]);
		expect(tcpTop).toBeLessThan(udpTop);
		close(tcpTop, layout.sources[0].y);
	});

	it('moves crowded labels apart and marks them for a connector, growing the chart when labels need it', () => {
		const data = flowData(skewed(10));
		for (const sizes of [{ labelH: 16, chipH: 24 }, { labelH: 20, chipH: 30 }, { labelH: 60, chipH: 30 }]) {
			const layout = flowLayout(data, 1000, sizes);
			const ys = layout.sources.map((n) => n.labelY);
			ys.forEach((y, i) => {
				expect(y - sizes.labelH / 2).toBeGreaterThanOrEqual(-1e-9);
				expect(y + sizes.labelH / 2).toBeLessThanOrEqual(layout.height + 1e-9);
				if (i > 0) expect(y - ys[i - 1]).toBeGreaterThanOrEqual(sizes.labelH + 4 - 1e-9);
			});
			expect(layout.height).toBeGreaterThanOrEqual(10 * sizes.labelH + 9 * 4);
			expect(layout.sources.some((n) => n.moved)).toBe(true);
			layout.sources.forEach((n) => expect(n.moved).toBe(Math.abs(n.labelY - (n.y + n.h / 2)) > 3));
		}
	});

	it('produces no NaN for a single node per column', () => {
		const data = flowData({ sources: [node('a', 5)], protocols: [node('tcp', 5)], destinations: [node('x', 5)], links: [link('a', 'tcp', 5), link('tcp', 'x', 5)] });
		expect(JSON.stringify(flowLayout(data, 640))).not.toMatch(/NaN|Infinity/);
	});
});

describe('share and splitText', () => {
	it('rounds shares and keeps slivers visible', () => {
		expect(share(37, 100)).toBe('37%');
		expect(share(0.4, 100)).toBe('<1%');
		expect(share(0, 100)).toBe('0%');
		expect(share(5, 0)).toBe('0%');
	});

	it('names each protocol with its share of the entry, largest first', () => {
		const data = flowData(INPUT);
		expect(splitText(data.sources[0], data.protocols)).toBe('TCP 67%, UDP 33%');
		expect(splitText(data.protocols[1], data.protocols)).toBe('UDP 100%');
	});
});

describe('flowLayout geometry', () => {
	it('keeps the chip room and both label areas apart at the narrowest chart', () => {
		const layout = flowLayout(flowData(INPUT), 640);
		expect(layout.chipMaxW).toBeGreaterThan(100);
		expect(layout.chipX + layout.chipMaxW).toBeLessThan(layout.dstLabelX);
		expect(layout.srcLabelW).toBeLessThan(layout.sources[0].x);
		expect(layout.dstLabelX + layout.dstLabelW).toBeLessThanOrEqual(640);
	});
});
