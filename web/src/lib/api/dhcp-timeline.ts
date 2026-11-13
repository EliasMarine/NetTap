/**
 * One device's DHCP transactions (NET-263): GET /api/dhcp/timeline (daemon/api/dhcp_timeline.py),
 * from Zeek's dhcp.log. Zeek records the message types of a transaction with no order and no
 * server per message; the server endpoints come from the transaction's connections.
 */
import { getJson, isNumber, isObject, isString } from './drilldown';

export const DHCP_OUTCOMES = [
	'mixed',
	'ack',
	'nak',
	'offer_no_reply',
	'discover_no_offer',
	'request_no_reply',
	'release',
	'decline',
	'inform',
	'other',
] as const;
export type DhcpOutcome = (typeof DHCP_OUTCOMES)[number];

export interface DhcpTransaction {
	ts: string;
	/** Seconds from the first message to the last; Zeek can record a small negative one */
	duration: number | null;
	/** Message type → how many were seen; NOT an order */
	messages: Record<string, number>;
	requested_ip: string | null;
	assigned_ip: string | null;
	/** The address the client sent from (its own when renewing), not 0.0.0.0 */
	client_ip: string | null;
	lease_time: number | null;
	host_name: string | null;
	client_software: string | null;
	/** What Zeek recorded as the server; not used to name a sender */
	zeek_server: string | null;
	/** The port 67 sides of the transaction's connections, sorted */
	server_endpoints: string[];
	/** False when one of its connections has no record yet */
	endpoints_complete: boolean;
	server_message: string | null;
	outcome: DhcpOutcome;
}

export interface DhcpTimeline {
	/** The MAC as stored: six lowercase colon-separated octets */
	mac: string;
	from: string;
	to: string;
	/** More transactions than the newest 200 the reply holds */
	truncated: boolean;
	transactions: DhcpTransaction[];
}

const isNullable = (v: unknown, test: (x: unknown) => boolean) => v === null || test(v);

const isTransaction = (t: unknown) =>
	isObject(t) &&
	isString(t.ts) &&
	isNullable(t.duration, isNumber) &&
	isObject(t.messages) &&
	Object.values(t.messages).every(isNumber) &&
	[t.requested_ip, t.assigned_ip, t.client_ip, t.host_name, t.client_software, t.zeek_server, t.server_message].every((v) => isNullable(v, isString)) &&
	isNullable(t.lease_time, isNumber) &&
	Array.isArray(t.server_endpoints) &&
	t.server_endpoints.every(isString) &&
	typeof t.endpoints_complete === 'boolean' &&
	(DHCP_OUTCOMES as readonly unknown[]).includes(t.outcome);

/** Throws the daemon's own reason (a bad MAC, busy, too slow) and on a malformed reply. */
export async function getDhcpTimeline(opts: { mac: string; from: string; to: string }): Promise<DhcpTimeline> {
	const q = new URLSearchParams(opts);
	const body = await getJson(`/api/dhcp/timeline?${q.toString()}`, 'DHCP timeline');
	const ok =
		isObject(body) &&
		isString(body.mac) &&
		isString(body.from) &&
		isString(body.to) &&
		typeof body.truncated === 'boolean' &&
		Array.isArray(body.transactions) &&
		body.transactions.every(isTransaction);
	if (!ok) throw new Error('DHCP timeline failed: the reply was malformed');
	return body as unknown as DhcpTimeline;
}
