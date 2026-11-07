import { describe, it, expect } from 'vitest';
import { connectionRef, packetsHrefFor } from './connection-ref';
import { readUrlState } from './packet-query';

const record = (over: Record<string, unknown> = {}) => ({
	'@timestamp': '2026-11-06T14:32:07.412Z',
	source: { ip: '192.168.1.42', port: 51834 },
	destination: { ip: '203.0.113.45', port: 443 },
	network: { transport: 'TCP' },
	event: { start: '1794061927412' },
	length: 34_250,
	...over,
});

describe('connectionRef', () => {
	it('maps a Zeek connection record field for field, keeping the start exact', () => {
		expect(connectionRef(record())).toEqual({
			proto: 'tcp',
			srcIp: '192.168.1.42',
			srcPort: 51834,
			dstIp: '203.0.113.45',
			dstPort: 443,
			start: '1794061927.412',
			duration: 34.25,
		});
	});

	it('falls back to @timestamp when event.start is missing', () => {
		const ref = connectionRef(record({ event: {} }));
		expect(ref?.start).toBe('1793975527.412');
		// Whole milliseconds, written exactly and as short as they go
		expect(connectionRef(record({ event: { start: '1794061927400' } }))?.start).toBe('1794061927.4');
	});

	it('leaves a missing or malformed port null rather than inventing one', () => {
		const ref = connectionRef(record({ source: { ip: '192.168.1.42' }, destination: { ip: '203.0.113.45', port: 'https' } }));
		expect(ref?.srcPort).toBeNull();
		expect(ref?.dstPort).toBeNull();
	});

	it('reads ports given as text or one-item arrays', () => {
		const ref = connectionRef(record({ source: { ip: ['192.168.1.42'], port: ['51834'] }, destination: { ip: '203.0.113.45', port: '443' } }));
		expect(ref).toMatchObject({ srcIp: '192.168.1.42', srcPort: 51834, dstPort: 443 });
	});

	it('leaves the duration null when the record has none', () => {
		const { length: _, ...rest } = record();
		expect(connectionRef(rest)?.duration).toBeNull();
	});

	it('gives nothing without both addresses and a start', () => {
		expect(connectionRef(record({ destination: {} }))).toBeNull();
		expect(connectionRef(record({ event: {}, '@timestamp': undefined }))).toBeNull();
	});
});

describe('packetsHrefFor', () => {
	const lan = { version: 1, subnets: ['192.168.1.0/24'] } as unknown as Parameters<typeof packetsHrefFor>[1];

	it('opens the exact connection over its padded window, anchored on the LAN side', () => {
		const href = packetsHrefFor(record(), lan)!;
		const state = readUrlState(new URL(href, 'http://x').searchParams)!;
		expect(state.filter).toContain('tcp.srcport == 51834');
		expect(state.filter).toContain('tcp.dstport == 443');
		expect(state).toMatchObject({ from: '1794061926.412', to: '1794061962.662', limit: 1000, device: '192.168.1.42' });
		expect(state.conn).toEqual({ start: '1794061927.412', duration: 34.25, segment: 0, exact: true });
	});

	it('gives no link for a record it cannot read', () => {
		expect(packetsHrefFor(record({ source: {} }), lan)).toBeNull();
		expect(packetsHrefFor(record({ source: { ip: 'not-an-ip', port: 1 } }), lan)).toBeNull();
	});
});
