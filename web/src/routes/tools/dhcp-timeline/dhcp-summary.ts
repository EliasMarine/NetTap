/**
 * Wording for the DHCP lease timeline (NET-263). Every line says what NetTap observed, never an
 * order of events: Zeek records which message types a transaction held, not their order, and
 * no server per message. A server is named for a message only when the transaction's
 * connections show exactly one server endpoint and all of them have a record (`soleServer`).
 */
import type { DhcpOutcome, DhcpTransaction } from '$lib/api/dhcp-timeline';
import type { RegistryDevice } from '$lib/api/devices-registry';
import { MAX_WINDOW_SECONDS, nsEpoch, packetsUrl } from '$lib/utils/packet-query';

export interface OutcomeLook {
	label: string;
	/** The chip's colour (with an icon), or null for a plain chip */
	tone: 'ok' | 'bad' | 'caution' | null;
}

export const OUTCOME: Record<DhcpOutcome, OutcomeLook> = {
	mixed: { label: 'ACK and NAK', tone: 'caution' },
	ack: { label: 'ACK', tone: 'ok' },
	nak: { label: 'NAK', tone: 'bad' },
	// OLD CODE: 'No ACK or NAK', 'No OFFER', 'No reply' (PR #263 review: what was seen, not what happened)
	offer_no_reply: { label: 'No ACK or NAK seen', tone: 'caution' },
	discover_no_offer: { label: 'No OFFER seen', tone: 'caution' },
	request_no_reply: { label: 'No reply seen', tone: 'caution' },
	release: { label: 'RELEASE', tone: null },
	decline: { label: 'DECLINE', tone: null },
	inform: { label: 'INFORM', tone: null },
	other: { label: 'Other', tone: null },
};

const PACKET_MARGIN_MS = 5_000;

const list = (items: readonly string[]): string => (items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items.at(-1)}`);
const forIp = (ip: string | null): string => (ip ? ` for ${ip}` : '');

/** The server that sent every server message in `t`, or null when its connections can't say. */
export function soleServer(t: DhcpTransaction): string | null {
	return t.endpoints_complete && t.server_endpoints.length === 1 ? t.server_endpoints[0] : null;
}

/** "ACK, OFFER ×2, REQUEST": the multiset, in the daemon's (alphabetical) key order. */
export function messagesText(t: DhcpTransaction): string {
	return Object.entries(t.messages)
		.map(([m, n]) => (n > 1 ? `${m} ×${n}` : m))
		.join(', ');
}

/** The observed-facts line for one outcome; `from` is " from <server>" or "". */
function outcomeLine(t: DhcpTransaction, from: string): string {
	const asked = t.requested_ip ?? t.client_ip;
	switch (t.outcome) {
		case 'ack':
			return `ACK observed${from}${forIp(t.assigned_ip)}.${t.messages.OFFER ? ' OFFER also observed.' : ''}`;
		case 'nak':
			return `NAK observed${from}${forIp(asked)}.`;
		case 'mixed':
			return 'Both an ACK and a NAK were observed in this transaction.';
		case 'offer_no_reply':
			return `OFFER${t.assigned_ip ? ` of ${t.assigned_ip}` : ''} observed${from}. No ACK or NAK observed.`;
		case 'discover_no_offer':
			return 'DISCOVER observed. No OFFER observed.';
		case 'request_no_reply':
			return `REQUEST${forIp(asked)} observed. No reply observed.`;
		case 'release':
			return `RELEASE observed${forIp(t.client_ip)}.`;
		case 'decline':
			return `DECLINE observed${forIp(t.requested_ip)}.`;
		case 'inform':
			return `INFORM observed${t.client_ip ? ` from ${t.client_ip}` : ''}.`;
		default:
			return messagesText(t) ? `Messages observed: ${messagesText(t)}.` : 'No message types were recorded.';
	}
}

/** The plain-English line for a transaction; a field that is missing is left out, never "undefined". */
export function summary(t: DhcpTransaction): string {
	const server = soleServer(t);
	// only these outcomes name a server message's sender in their own words
	const named = server !== null && (t.outcome === 'ack' || t.outcome === 'nak' || t.outcome === 'offer_no_reply');
	const parts = [outcomeLine(t, named ? ` from ${server}` : '')];
	if (!named && t.server_endpoints.length > 0) {
		const noun = t.server_endpoints.length === 1 ? 'Server endpoint' : 'Server endpoints';
		parts.push(`${noun} in this transaction: ${list(t.server_endpoints)}.`);
	}
	if (!t.endpoints_complete) parts.push('Not every connection in this transaction has been recorded yet.');
	if (t.server_message) parts.push(`Server message: “${t.server_message}”.`);
	return parts.join(' ');
}

/**
 * Packet analysis for this device's DHCP packets around the transaction. Every row has it: with
 * one server named it still shows who really sent a reply (a spoofed NAK, say).
 */
export function packetsHref(t: DhcpTransaction, mac: string): string | null {
	const start = Date.parse(t.ts);
	// OLD CODE: if ((t.server_endpoints.length < 2 && t.endpoints_complete) || !Number.isFinite(start)) return null; (PR #263 review: every row)
	if (!Number.isFinite(start)) return null;
	const from = start - PACKET_MARGIN_MS;
	// Zeek can record a small negative duration; the packets page takes at most 30 minutes
	const to = Math.min(start + Math.max(0, t.duration ?? 0) * 1000 + PACKET_MARGIN_MS, from + MAX_WINDOW_SECONDS * 1000);
	const epoch = (ms: number) => nsEpoch(BigInt(Math.round(ms)) * 1_000_000n);
	return packetsUrl({ filter: `dhcp && dhcp.hw.mac_addr == ${mac}`, from: epoch(from), to: epoch(to), limit: 100, device: null, conn: null });
}

/** A lease length as written in the Assigned column: "24 h", "30 min", else seconds. */
export function leaseWords(seconds: number): string {
	if (seconds >= 3600 && seconds % 3600 === 0) return `${seconds / 3600} h`;
	if (seconds >= 60 && seconds % 60 === 0) return `${seconds / 60} min`;
	return `${seconds} s`;
}

/** What the picker's text names: a registry device's MAC by its name or IP, else the text as typed. */
export function pickedMac(text: string, devices: readonly RegistryDevice[]): string {
	const typed = text.trim();
	const wanted = typed.toLowerCase();
	const found = devices.find((d) => d.display_name.toLowerCase() === wanted || d.ips.includes(typed));
	return found ? found.mac.toLowerCase() : typed;
}

/** The registry's name, then the newest DHCP host name, then the MAC. */
export function deviceName(mac: string, devices: readonly RegistryDevice[], transactions: readonly DhcpTransaction[]): string {
	const registered = devices.find((d) => d.mac.toLowerCase() === mac)?.display_name;
	return registered || transactions.find((t) => t.host_name)?.host_name || mac;
}
