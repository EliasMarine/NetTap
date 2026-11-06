import { describe, it, expect } from 'vitest';
import { flowData } from '../../../src/lib/components/ui/charts/flow.ts';
import { LAN_DEVICES } from './net-world.ts';
import { TRAFFIC_ROUTES, UNNAMED_SOURCES, networkFlow } from './traffic.ts';

describe('Network flow fixture', () => {
	const flow = networkFlow();
	const values = flow.nodes.sources.map((s) => s.value);
	const total = values.reduce((a, v) => a + v, 0);

	it('is what the sankey route serves', () => {
		expect(TRAFFIC_ROUTES.find((r) => r.path === '/api/traffic/connections/sankey')?.populated).toEqual(flow);
	});

	it('is crowded: 10 sources and 10 destinations, one dominant source and some slivers', () => {
		expect(flow.nodes.sources).toHaveLength(10);
		expect(flow.nodes.destinations).toHaveLength(10);
		expect(Math.max(...values) / total).toBeGreaterThan(0.55);
		expect(values.filter((v) => v / total < 0.005).length).toBeGreaterThanOrEqual(2);
		expect(flow.nodes.destinations.filter((d) => d.label.length > 50)).toHaveLength(2);
		expect(flow.nodes.protocols.map((p) => p.id).sort()).toEqual(['icmp', 'tcp', 'udp']);
	});

	it('mixes devices the registry names with addresses it does not know', () => {
		const known = new Set(LAN_DEVICES.map((d) => d.ip));
		const ips = flow.nodes.sources.map((s) => s.id);
		expect(ips.filter((ip) => known.has(ip))).toHaveLength(6);
		expect(ips.filter((ip) => !known.has(ip)).sort()).toEqual([...UNNAMED_SOURCES].sort());
	});

	it('adds up, with about a fifth of the bytes left for Other destinations', () => {
		const data = flowData({ ...flow.nodes, links: flow.links });
		expect(data.consistent).toBe(true);
		const other = data.destinations.find((d) => d.other);
		expect(other!.value / total).toBeGreaterThan(0.1);
		expect(other!.value / total).toBeLessThan(0.3);
	});
});
