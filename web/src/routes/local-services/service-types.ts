/**
 * Local services (NET-264): plain names for the DNS-SD service types devices announce over mDNS,
 * and the page's wording for a row. The raw type always shows beside the name, so an unknown type
 * reads as itself.
 */
import type { LocalServiceRow, ServiceSender } from '$lib/api/local-services';
// OLD CODE: import { MAX_WINDOW_SECONDS, packetsUrl, windowFor } from '$lib/utils/packet-query'; (review: around last_seen)
import { isIpAddress } from '$lib/stores/lan';
import { nsEpoch, packetsUrl } from '$lib/utils/packet-query';

const NAMES: Record<string, string> = {
	// Apple
	_airplay: 'AirPlay receiver',
	_raop: 'AirPlay speaker',
	'_companion-link': 'Apple device',
	'_device-info': 'Device information',
	'_sleep-proxy': 'Sleep proxy',
	_adisk: 'Time Machine',
	_rfb: 'Screen sharing',
	// Printers and scanners
	_ipp: 'Printer (AirPrint/IPP)',
	_ipps: 'Printer (AirPrint/IPP)',
	_printer: 'Printer (LPD)',
	'_pdl-datastream': 'Printer (raw)',
	_scanner: 'Scanner',
	_uscan: 'Scanner',
	// Media and smart home
	_googlecast: 'Google Cast',
	_googlezone: 'Google Home group',
	_hap: 'HomeKit accessory',
	'_spotify-connect': 'Spotify Connect',
	_hue: 'Philips Hue bridge',
	_matter: 'Matter device',
	_matterc: 'Matter device',
	_meshcop: 'Thread border router',
	_sonos: 'Sonos',
	'_amzn-wplay': 'Amazon Fire TV',
	_androidtvremote2: 'Android TV',
	// Network services
	_smb: 'File share (SMB)',
	_afpovertcp: 'File share (AFP)',
	_ssh: 'SSH',
	_http: 'Web interface',
};

export const SSDP_NAME = 'UPnP device (SSDP)';

/** "AirPlay receiver" for "_airplay._tcp"; the raw type when it isn't one we know. */
export function serviceName(protocol: 'mdns' | 'ssdp', serviceType: string): string {
	if (protocol === 'ssdp') return SSDP_NAME;
	const key = serviceType.split('.')[0];
	// own keys only: the type comes off the wire, and "__proto__" is not a name
	return Object.hasOwn(NAMES, key) ? NAMES[key] : serviceType;
}

/** The VLAN column: the tag, "untagged", or "not yet known" while the flow's conn record isn't written. */
export function vlanWords(sender: ServiceSender): string {
	if (sender.vlan_state === 'unknown') return 'not yet known';
	return sender.vlan_state === 'untagged' ? 'untagged' : (sender.vlan ?? 'untagged');
}

export const protocolWord = (row: LocalServiceRow): string => (row.protocol === 'ssdp' ? 'SSDP' : 'mDNS');

/** The search box: a case-blind match on any column's text. */
export function rowMatches(row: LocalServiceRow, query: string): boolean {
	const q = query.trim().toLowerCase();
	if (!q) return true;
	const { sender } = row;
	return [serviceName(row.protocol, row.service_type ?? ''), row.service_type, row.instance, sender.name, sender.ip, sender.mac, protocolWord(row), vlanWords(sender)].some(
		(text) => text?.toLowerCase().includes(q),
	);
}

// OLD CODE START — NET-264 review: the 30 minutes before the page loaded, not the row's own time
// /** Packet analysis for an SSDP sender's own announcements over the last 30 minutes. */
// export function ssdpPacketsHref(ip: string, nowMs: number): string {
// 	const filter = `ssdp && ${ip.includes(':') ? 'ipv6' : 'ip'}.src == ${ip}`;
// 	return packetsUrl({ filter, ...windowFor({ kind: 'last', seconds: MAX_WINDOW_SECONDS }, nowMs), limit: 100, device: null, conn: null });
// }
// OLD CODE END
/** Seconds of capture around an SSDP row's last announcement: a minute before, five after (within MAX_WINDOW_SECONDS). */
const SSDP_BEFORE_S = 60;
const SSDP_AFTER_S = 300;

/** Packet analysis for an SSDP sender's announcements around its last one; null when either can't be read. */
export function ssdpPacketsHref(ip: string, lastSeen: string): string | null {
	const at = Date.parse(lastSeen);
	// the IP goes into a filter: only an address's characters may reach it
	if (!isIpAddress(ip) || Number.isNaN(at)) return null;
	const epoch = (ms: number) => nsEpoch(BigInt(ms) * 1_000_000n);
	const filter = `ssdp && ${ip.includes(':') ? 'ipv6' : 'ip'}.src == ${ip}`;
	return packetsUrl({ filter, from: epoch(at - SSDP_BEFORE_S * 1000), to: epoch(at + SSDP_AFTER_S * 1000), limit: 100, device: null, conn: null });
}

/** fe80::/10: a link-local address repeats on every VLAN, so it never stands for one device. */
export const isLinkLocal6 = (ip: string): boolean => /^fe[89ab][0-9a-f]:/i.test(ip);
