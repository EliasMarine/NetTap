/**
 * One packet in plain English (NET-188), from the fields TShark gave for its row.
 *
 * A sentence is written only when the row says exactly one thing: one IP layer, one DNS
 * message, one TLS handshake message, a protocol listed here, and nothing TShark flagged above
 * "chat". Anything else gets null, and the page shows TShark's own Info line alone.
 */
import type { PacketRow } from '$lib/api/packets';
import { fmt } from '$lib/utils/drilldown';

type Names = ReadonlyMap<string, string>;
type Fields = PacketRow['fields'];

/** TShark's expert severity "chat" (PI_CHAT); note, warn and error are above it. */
const CHAT = 2_097_152;
/** TCP flag bits */
const FIN = 0x01, SYN = 0x02, RST = 0x04, ACK = 0x10, URG = 0x20;

/** The field's single value, or null when it is absent or repeated. */
export function one(fields: Fields, name: string): string | null {
	const v = fields[name];
	return v?.length === 1 ? v[0] : null;
}

const count = (fields: Fields, name: string) => fields[name]?.length ?? 0;
/** "1 packet", "1,204 packets" */
export const plural = (n: number, word: string, many = `${word}s`): string => `${fmt(n)} ${n === 1 ? word : many}`;

/** "a, b and c", or the first three "and 2 more" */
function list(items: string[]): string {
	const shown = items.slice(0, 3);
	const rest = items.length - shown.length;
	if (rest > 0) return `${shown.join(', ')} and ${fmt(rest)} more`;
	return shown.length > 1 ? `${shown.slice(0, -1).join(', ')} and ${shown.at(-1)}` : (shown[0] ?? '');
}

function tcp(f: Fields, src: string, dst: string): string | null {
	const flagsText = one(f, 'tcp.flags');
	const lenText = one(f, 'tcp.len');
	if (flagsText === null || lenText === null) return null;
	const flags = parseInt(flagsText, 16);
	const len = Number(lenText);
	if (!Number.isFinite(flags) || !Number.isInteger(len) || flags & URG) return null;
	const core = flags & (FIN | SYN | RST | ACK);
	if (len > 0) return core === ACK ? `${src} sent ${plural(len, 'byte')} of data to ${dst}` : null;
	if (core === SYN) return `${src} asked ${dst} to connect on port ${one(f, 'tcp.dstport') ?? '?'}`;
	if (core === (SYN | ACK)) return `${src} agreed to connect`;
	if (core === RST || core === (RST | ACK)) return `${src} ended the connection abruptly`;
	if (core === FIN || core === (FIN | ACK)) return `${src} closed its side of the connection`;
	if (core === ACK) return `${src} acknowledged what ${dst} sent`;
	return null;
}

const RCODES: Record<string, string> = { '2': "couldn't answer for", '3': 'said there is no such name as', '5': 'refused to look up' };

function dns(f: Fields, src: string, dst: string): string | null {
	const response = one(f, 'dns.flags.response');
	const name = one(f, 'dns.qry.name');
	if (response === null || name === null) return null;
	if (response === '0') return `${src} asked ${dst} to look up ${name}`;
	const rcode = one(f, 'dns.flags.rcode');
	if (rcode !== '0') return rcode !== null && RCODES[rcode] ? `${src} ${RCODES[rcode]} ${name}` : null;
	const answersText = one(f, 'dns.count.answers');
	const answers = Number(answersText);
	if (answersText === null || !Number.isInteger(answers)) return null;
	if (answers === 0) return `${src} answered that ${name} has no records of that kind`;
	const addresses = [...(f['dns.a'] ?? []), ...(f['dns.aaaa'] ?? [])];
	const cnames = count(f, 'dns.cname');
	// Every answer is an address or another name: list them; otherwise only the count is certain
	if (addresses.length + cnames !== answers) return `${src} answered ${name} with ${plural(answers, 'answer')}`;
	const via = cnames ? `, by way of ${plural(cnames, 'other name')}` : '';
	const found = addresses.length ? `${plural(addresses.length, 'address', 'addresses')}: ${list(addresses)}` : 'no address';
	return `${src} answered ${name} with ${found}${via}`;
}

function tls(row: PacketRow, src: string, dst: string): string | null {
	const f = row.fields;
	if (count(f, 'tls.alert_message.desc') > 0) return null;
	const types = f['tls.handshake.type'] ?? [];
	if (types.length === 0) return row.info === 'Application Data' ? `${src} sent encrypted data` : null;
	if (types.length > 1) return null;
	if (types[0] === '1') {
		const sni = one(f, 'tls.handshake.extensions_server_name');
		return `${src} asked ${sni ?? dst} to start encryption`;
	}
	return types[0] === '2' ? `${src} agreed to start encryption` : null;
}

function http(f: Fields, src: string, dst: string): string | null {
	const method = one(f, 'http.request.method');
	const code = one(f, 'http.response.code');
	if ((method === null) === (code === null)) return null;
	if (method !== null) {
		const uri = one(f, 'http.request.uri');
		if (uri === null) return null;
		return `${src} sent an unencrypted ${method} request for ${one(f, 'http.host') ?? dst}${uri}`;
	}
	const phrase = one(f, 'http.response.phrase');
	return `${src} answered “${phrase ? `${code} ${phrase}` : code}” without encryption`;
}

function icmp(f: Fields, src: string, dst: string, field: 'icmp.type' | 'icmpv6.type'): string | null {
	const type = one(f, field);
	const [request, reply] = field === 'icmp.type' ? ['8', '0'] : ['128', '129'];
	if (type === request) return `${src} pinged ${dst}`;
	return type === reply ? `${src} answered a ping from ${dst}` : null;
}

function arp(f: Fields, names: Names): string | null {
	const op = one(f, 'arp.opcode');
	const ip = one(f, 'arp.src.proto_ipv4');
	const target = one(f, 'arp.dst.proto_ipv4');
	const mac = one(f, 'arp.src.hw_mac');
	if (ip === null || mac === null) return null;
	const sender = names.get(ip) ?? mac;
	// A device asking about its own address is a probe or an announcement, not a question
	if (op === '1' && target !== null && target !== ip) return `${sender} asked which device has ${target}`;
	return op === '2' ? `${sender} answered that it has ${ip}` : null;
}

function dhcp(f: Fields, src: string): string | null {
	const client = one(f, 'dhcp.option.hostname') ?? one(f, 'dhcp.hw.mac_addr');
	const your = one(f, 'dhcp.ip.your');
	const requested = one(f, 'dhcp.option.requested_ip_address');
	if (client === null) return null;
	switch (one(f, 'dhcp.option.dhcp')) {
		case '1':
			return `${client} asked for an address`;
		case '2':
			return your ? `${src} offered ${your} to ${client}` : null;
		case '3':
			return requested ? `${client} asked to use ${requested}` : null;
		case '5':
			return your ? `${src} gave ${your} to ${client}` : null;
		case '6':
			return `${src} refused ${client}'s request`;
		case '7':
			return `${client} gave its address back`;
		default:
			return null;
	}
}

/**
 * A plain-English sentence for the row, or null when the case isn't unambiguous (several IP
 * layers, several TLS messages, an unknown protocol…): the page then shows TShark's Info alone.
 * names: IP → device name.
 */
export function describePacket(row: PacketRow, names: ReadonlyMap<string, string>): string | null {
	const f = row.fields;
	if (count(f, 'ip.src') + count(f, 'ipv6.src') > 1) return null;
	if ((f['_ws.expert.severity'] ?? []).some((s) => !(Number(s) <= CHAT))) return null;
	const srcIp = one(f, 'ip.src') ?? one(f, 'ipv6.src');
	const dstIp = one(f, 'ip.dst') ?? one(f, 'ipv6.dst');
	const who = (ip: string) => names.get(ip) ?? ip;
	if (row.protocol === 'ARP') return arp(f, names);
	if (srcIp === null || dstIp === null) return null;
	const [src, dst] = [who(srcIp), who(dstIp)];
	switch (row.protocol) {
		case 'TCP':
			return tcp(f, src, dst);
		case 'DNS':
			return dns(f, src, dst);
		case 'HTTP':
			return http(f, src, dst);
		case 'ICMP':
			return icmp(f, src, dst, 'icmp.type');
		case 'ICMPv6':
			return icmp(f, src, dst, 'icmpv6.type');
		case 'DHCP':
			return dhcp(f, src);
		default:
			return /^(TLS|SSL)/.test(row.protocol) ? tls(row, src, dst) : null;
	}
}
