/** Fixtures for /api/moment/devices (daemon/api/moment.py, NET-249), from the shared fixture world. */
import type { MomentDevice, MomentDevicesResponse } from '../../../src/lib/api/moment.ts';
import type { FixtureRoute } from './types.ts';
import { LAN_DEVICES, PEERS, WINDOW } from './net-world.ts';

const device = (d: (typeof LAN_DEVICES)[number], k: number): MomentDevice => ({
	ip: d.ip,
	name: d.hostname,
	mac: d.mac,
	total_bytes: d.origBytes + d.respBytes,
	upload_bytes: d.origBytes,
	download_bytes: d.respBytes,
	connection_count: d.connections,
	// one device shows the IPv6 note (NET-226)
	ipv6_left_out: k === 1 ? 14 : 0,
	ipv6_left_out_reason: k === 1 ? 'no_gateway' : null,
	destinations: PEERS.slice(k, k + 3).map((p) => ({ ip: p.ip, bytes: Math.round(p.bytes / 4), connections: Math.round(p.connections / 4) })),
	domains: PEERS.slice(k, k + 3).map((p, i) => ({ domain: p.host, count: 120 - i * 30 })),
	apps: d.protocols.slice(0, 3).map((protocol, i) => ({ protocol, bytes: Math.round(d.respBytes / (i + 2)), connections: Math.round(d.connections / (i + 2)) })),
});

const RANKED = [...LAN_DEVICES].sort((a, b) => b.origBytes + b.respBytes - (a.origBytes + a.respBytes));

export const MOMENT_DEVICES = {
	...WINDOW,
	total_devices: RANKED.length,
	// the last is an answer-only device: it started no connections, so its lists are empty
	devices: RANKED.map((d, k) => (k === RANKED.length - 1 ? { ...device(d, k), destinations: [], domains: [], apps: [] } : device(d, k))),
} satisfies MomentDevicesResponse;

export const MOMENT_DEVICES_EMPTY = { ...WINDOW, total_devices: 0, devices: [] } satisfies MomentDevicesResponse;

export const MOMENT_ROUTES: FixtureRoute[] = [{ path: '/api/moment/devices', empty: MOMENT_DEVICES_EMPTY, populated: MOMENT_DEVICES }];
