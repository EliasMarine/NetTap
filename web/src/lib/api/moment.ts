/**
 * The moment page's device breakdown (NET-249): GET /api/moment/devices (daemon/api/moment.py).
 * The busiest LAN devices in a window, ranked exactly as /api/devices ranks them, each with the
 * destinations, names and apps of the connections it started there.
 */
import { getJson, isNumber, isObject, isString } from './drilldown';
import type { Ipv6LeftOutReason } from '$lib/utils/ipv6-coverage';

export interface MomentDestination {
	ip: string;
	bytes: number;
	connections: number;
}

export interface MomentDomain {
	domain: string;
	count: number;
}

export interface MomentApp {
	protocol: string;
	bytes: number;
	connections: number;
}

export interface MomentDevice {
	ip: string;
	name: string | null;
	mac: string | null;
	/** upload + download; IPv6 credited by MAC is in it, but not in the lists below */
	total_bytes: number;
	upload_bytes: number;
	download_bytes: number;
	connection_count: number;
	/** IPv6 connections left out of the totals, and why (NET-226) */
	ipv6_left_out: number;
	ipv6_left_out_reason: Ipv6LeftOutReason | null;
	/** Top 5 rankings of the connections it started, not counts that add up */
	destinations: MomentDestination[];
	domains: MomentDomain[];
	apps: MomentApp[];
}

export interface MomentDevicesResponse {
	from: string;
	to: string;
	/** Ranked LAN devices in the window, before `limit` */
	total_devices: number;
	devices: MomentDevice[];
}

const isNullableString = (v: unknown) => v === null || isString(v);
const listOf = (v: unknown, ok: (x: Record<string, unknown>) => boolean) => Array.isArray(v) && v.every((x) => isObject(x) && ok(x));

const isDevice = (d: Record<string, unknown>) =>
	isString(d.ip) &&
	isNullableString(d.name) &&
	isNullableString(d.mac) &&
	[d.total_bytes, d.upload_bytes, d.download_bytes, d.connection_count, d.ipv6_left_out].every(isNumber) &&
	(d.ipv6_left_out_reason === null || d.ipv6_left_out_reason === 'router' || d.ipv6_left_out_reason === 'no_gateway') &&
	listOf(d.destinations, (x) => isString(x.ip) && isNumber(x.bytes) && isNumber(x.connections)) &&
	listOf(d.domains, (x) => isString(x.domain) && isNumber(x.count)) &&
	listOf(d.apps, (x) => isString(x.protocol) && isNumber(x.bytes) && isNumber(x.connections));

/**
 * The top `limit` devices in the window. Throws the daemon's own reason (busy, too slow, couldn't
 * read) on an error, and on a malformed reply, so a card never shows a blank as "no devices".
 */
export async function getMomentDevices(opts: { from: string; to: string; limit?: number }): Promise<MomentDevicesResponse> {
	// the daemon takes 1–25 and answers 400 outside it
	const q = new URLSearchParams({ from: opts.from, to: opts.to, limit: String(opts.limit ?? 10) });
	const body = await getJson(`/api/moment/devices?${q.toString()}`, 'Moment devices');
	const ok = isObject(body) && isString(body.from) && isString(body.to) && isNumber(body.total_devices) && listOf(body.devices, isDevice);
	if (!ok) throw new Error('Moment devices failed: the reply was malformed');
	return body as unknown as MomentDevicesResponse;
}
