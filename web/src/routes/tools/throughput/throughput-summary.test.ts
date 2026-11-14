import { describe, it, expect } from 'vitest';
import type { ThroughputResult } from '$api/tools';
import { mirrorNote, pathLine, rate, retransmitsText } from './throughput-summary';

const G11: ThroughputResult = {
	peer: '192.168.1.20',
	resolved_ip: '192.168.1.20',
	port: 5201,
	direction: 'upload',
	duration: 10,
	bits_per_second: 941_000_000,
	retransmits: 0,
	path: { interface: 'eno1', source_ip: '192.168.1.199', wifi: false, speed_mbps: 1000, mtu: 1500 },
	capture: { mode: 'mirror', interface: 'enp4s0', has_ip: false },
	error: null,
};

describe('throughput wording (NET-266)', () => {
	it('names the interface, its address, wired or Wi-Fi, and the link speed', () => {
		expect(pathLine(G11)).toBe('This test runs over eno1 (192.168.1.199, wired, 1 Gbit/s).');
		const wifi = { ...G11, path: { ...G11.path!, interface: 'wlp2s0', wifi: true, speed_mbps: 2500 } };
		expect(pathLine(wifi)).toBe('This test runs over wlp2s0 (192.168.1.199, Wi-Fi, 2.5 Gbit/s).');
	});

	it('leaves out what is unknown, and says nothing without a path', () => {
		// OLD CODE: expect(…source_ip: null, speed_mbps: null…).toBe('This test runs over eno1 (wired).'); (review of #266)
		expect(pathLine({ ...G11, path: { ...G11.path!, source_ip: null } })).toBe('This test runs over eno1 (wired, 1 Gbit/s).');
		// a tunnel has no link speed: neither wired nor Wi-Fi
		const tunnel = { ...G11, path: { ...G11.path!, interface: 'tailscale0', source_ip: '100.64.0.2', speed_mbps: null } };
		expect(pathLine(tunnel)).toBe('This test runs over tailscale0 (100.64.0.2).');
		expect(pathLine({ ...G11, path: { ...G11.path!, wifi: true, speed_mbps: null } })).toBe('This test runs over eno1 (192.168.1.199, Wi-Fi).');
		expect(pathLine({ ...G11, path: null })).toBeNull();
	});

	it('explains the mirror port only in mirror mode, when the port has no address', () => {
		// OLD CODE: expect(mirrorNote(G11)).toBe('The capture port enp4s0 has no IP address, so this measures the management path, not the mirror port.');
		expect(mirrorNote(G11)).toBe("Normal in mirror mode: the capture port enp4s0 only listens, so it has no IP address and can't carry a test. This measures eno1, not the mirror port.");
		expect(mirrorNote({ ...G11, path: null })).toMatch(/This measures the management connection, not the mirror port\.$/);
		expect(mirrorNote({ ...G11, capture: { mode: 'bridge', interface: 'br0', has_ip: true } })).toBeNull();
		expect(mirrorNote({ ...G11, capture: { mode: 'mirror', interface: 'enp4s0', has_ip: true } })).toBeNull();
		expect(mirrorNote({ ...G11, capture: { mode: 'mirror', interface: 'enp4s0', has_ip: null } })).toBeNull();
		expect(mirrorNote({ ...G11, capture: { mode: null, interface: null, has_ip: null } })).toBeNull();
	});

	it('writes a rate in decimal units, or a dash for a failed run', () => {
		expect(rate(941_000_000)).toBe('941 Mbit/s');
		expect(rate(null)).toBe('—');
	});

	it('counts retransmits in words', () => {
		expect([0, 1, 12, null].map(retransmitsText)).toEqual(['0 retransmits', '1 retransmit', '12 retransmits', '—']);
	});
});
