/**
 * The IPv6 ranges the IPv6 toolkit names (NET-218): every row of the IANA IPv6
 * Special-Purpose Address Registry as of 2026-11-08 (its CSV is checked in next to the
 * tests as iana-ipv6-special-registry.csv, and a test keeps the two in step), plus
 * multicast, the deprecated site-local block and global unicast.
 *
 * `block` is the prefix length assumed when none is typed (null: no block to show).
 * `iid` says whether the last 64 bits name a device (an interface ID).
 * `globallyReachable` is the registry's column; null where it says N/A or the range isn't in it.
 */
export interface RangeDef {
	key: string;
	net: string;
	len: number;
	label: string;
	reach: string;
	text: string;
	block: number | null;
	iid: boolean;
	globallyReachable: boolean | null;
	/** Shown with the amber chip: worth a look if seen in real traffic */
	caution?: boolean;
}

const DOC_TEXT = 'Reserved for examples, in manuals and on this page. It is never routed, so seeing it in real traffic means something is misconfigured.';

export const RANGES: RangeDef[] = [
	{ key: 'loopback', net: '::1', len: 128, label: 'Loopback', reach: 'This device only', block: null, iid: false, globallyReachable: false,
		text: 'This device talking to itself, like 127.0.0.1 in IPv4. It never leaves the device.' },
	{ key: 'unspecified', net: '::', len: 128, label: 'Unspecified', reach: 'Nowhere', block: null, iid: false, globallyReachable: false,
		text: 'The all-zero address. A device uses it as its source before it has an address, and a server listening on it means "every address on this device".' },
	{ key: 'mapped', net: '::ffff:0:0', len: 96, label: 'IPv4-mapped', reach: 'Inside this device', block: null, iid: false, globallyReachable: false,
		text: 'An IPv4 address written in IPv6 form. Dual-stack software uses it internally; it is never sent on the network.' },
	{ key: 'nat64', net: '64:ff9b::', len: 96, label: 'NAT64', reach: 'The internet, through a NAT64 gateway', block: 96, iid: false, globallyReachable: true,
		text: 'An IPv4 server reached through your provider\'s NAT64 gateway, so IPv6-only devices can still reach IPv4 sites.' },
	{ key: 'nat64-local', net: '64:ff9b:1::', len: 48, label: 'Local IPv4/IPv6 translation', reach: 'Your network only', block: 48, iid: false, globallyReachable: false,
		text: 'An IPv4 address reached through a translator your own network runs. It can\'t be reached from the internet.' },
	{ key: 'discard', net: '100::', len: 64, label: 'Discard-only', reach: 'Nowhere: dropped on purpose', block: 64, iid: false, globallyReachable: false, caution: true,
		text: 'Routers send traffic for this block into a black hole, usually to soak up an attack.' },
	{ key: 'dummy', net: '100:0:0:1::', len: 64, label: 'Dummy prefix', reach: 'Nowhere: never forwarded', block: 64, iid: false, globallyReachable: false, caution: true,
		text: 'A placeholder source address for a device with no real IPv6 address. Nothing is ever sent to it.' },
	{ key: 'ietf', net: '2001::', len: 23, label: 'IETF protocol assignment', reach: 'Depends on the protocol', block: null, iid: false, globallyReachable: false, caution: true,
		text: 'Set aside for specific internet protocols, not handed out to networks. An address here with no listed use should not appear in normal traffic.' },
	{ key: 'teredo', net: '2001::', len: 32, label: 'Teredo tunnel', reach: 'The internet, tunnelled over IPv4', block: null, iid: false, globallyReachable: null, caution: true,
		text: 'IPv6 carried inside IPv4 UDP, an old Windows fallback. Rare today; on a home network it can slip past IPv4 firewall rules.' },
	{ key: 'pcp-anycast', net: '2001:1::1', len: 128, label: 'Port Control Protocol anycast', reach: 'The whole internet', block: null, iid: false, globallyReachable: true,
		text: 'The address devices use to ask the nearest router to open a port for them.' },
	{ key: 'turn-anycast', net: '2001:1::2', len: 128, label: 'TURN anycast', reach: 'The whole internet', block: null, iid: false, globallyReachable: true,
		text: 'The address of the nearest TURN relay, which carries calls and video through NAT.' },
	{ key: 'srp-anycast', net: '2001:1::3', len: 128, label: 'DNS-SD registration anycast', reach: 'The whole internet', block: null, iid: false, globallyReachable: true,
		text: 'The address devices use to register the services they offer, so others can discover them.' },
	{ key: 'benchmarking', net: '2001:2::', len: 48, label: 'Benchmarking', reach: 'Nowhere: test labs only', block: 64, iid: true, globallyReachable: false, caution: true,
		text: 'Reserved for testing network equipment in labs. It should never appear on a live network.' },
	{ key: 'amt', net: '2001:3::', len: 32, label: 'AMT relay', reach: 'The whole internet', block: null, iid: false, globallyReachable: true,
		text: 'Automatic Multicast Tunneling relays, which carry multicast across the unicast internet.' },
	{ key: 'as112', net: '2001:4:112::', len: 48, label: 'AS112 DNS sink', reach: 'The whole internet', block: 48, iid: false, globallyReachable: true,
		text: 'Servers that soak up stray reverse-DNS look-ups for private addresses, so they don\'t burden the real DNS.' },
	{ key: 'orchid', net: '2001:10::', len: 28, label: 'ORCHID (deprecated)', reach: 'Nowhere: retired', block: null, iid: false, globallyReachable: null, caution: true,
		text: 'Retired in 2014 and replaced by ORCHIDv2. It should not appear in traffic.' },
	{ key: 'orchid2', net: '2001:20::', len: 28, label: 'ORCHIDv2 identifier', reach: 'The whole internet, as an identifier', block: null, iid: false, globallyReachable: true,
		text: 'A cryptographic identifier used by protocols such as HIP, not an ordinary device address.' },
	{ key: 'drone-det', net: '2001:30::', len: 28, label: 'Drone Remote ID tag', reach: 'The whole internet, as an identifier', block: null, iid: false, globallyReachable: true,
		text: 'Identifies a drone in the Remote ID system, not an ordinary device address.' },
	{ key: 'documentation', net: '2001:db8::', len: 32, label: 'Documentation', reach: 'Nowhere: never routed', block: 64, iid: true, globallyReachable: false, caution: true,
		text: DOC_TEXT },
	{ key: '6to4', net: '2002::', len: 16, label: '6to4 tunnel', reach: 'The internet, tunnelled over IPv4', block: 48, iid: true, globallyReachable: null, caution: true,
		text: 'An old way to carry IPv6 over IPv4, with the IPv4 address built in. It is deprecated, and most networks no longer use it.' },
	{ key: 'as112-direct', net: '2620:4f:8000::', len: 48, label: 'AS112 direct delegation', reach: 'The whole internet', block: 48, iid: false, globallyReachable: true,
		text: 'Servers that answer reverse-DNS for zones delegated straight to the AS112 service.' },
	{ key: 'documentation-2', net: '3fff::', len: 20, label: 'Documentation', reach: 'Nowhere: never routed', block: 64, iid: true, globallyReachable: false, caution: true,
		text: DOC_TEXT },
	{ key: 'srv6', net: '5f00::', len: 16, label: 'SRv6 segment ID', reach: 'A provider\'s network only', block: null, iid: false, globallyReachable: false,
		text: 'Used inside a provider\'s network to steer traffic along a chosen path. It should not reach home devices.' },
	{ key: 'ula', net: 'fc00::', len: 7, label: 'Unique local (ULA)', reach: 'Your network only', block: 64, iid: true, globallyReachable: false,
		text: 'A private address for use inside your network, like 192.168.x.x in IPv4. It can\'t be reached from the internet.' },
	{ key: 'linklocal', net: 'fe80::', len: 10, label: 'Link-local', reach: 'This network segment only', block: 64, iid: true, globallyReachable: false,
		text: 'Works only on this network segment: routers never forward it. Every IPv6 device makes one for itself, so seeing it is normal.' },
	// Not in the special-purpose registry
	{ key: 'multicast', net: 'ff00::', len: 8, label: 'Multicast', reach: '', block: null, iid: false, globallyReachable: null,
		text: 'Sent to a group of devices, not to one.' },
	{ key: 'sitelocal', net: 'fec0::', len: 10, label: 'Site-local (deprecated)', reach: 'Your site', block: 64, iid: true, globallyReachable: null, caution: true,
		text: 'An old private range, replaced by unique local addresses in 2004. Modern devices should not use it.' },
	{ key: 'global', net: '2000::', len: 3, label: 'Global unicast', reach: 'The whole internet', block: 64, iid: true, globallyReachable: null,
		text: 'A public internet address. Your provider assigns the first part, the prefix. It can be reached from anywhere unless a firewall stops it.' },
];

export const RESERVED: RangeDef = {
	key: 'reserved', net: '::', len: 0, label: 'Reserved', reach: 'Not assigned', block: null, iid: false, globallyReachable: null, caution: true,
	text: 'In a range the IETF has not assigned for general use. Real devices should not use it.',
};

/** Multicast scope (the fourth hex digit) in plain words */
export const MULTICAST_SCOPES: Record<number, string> = {
	1: 'This interface only', 2: 'This network segment', 3: 'Realm', 4: 'Admin-defined area',
	5: 'Your site', 8: 'Your organisation', 14: 'The whole internet',
};

export const KNOWN_MULTICAST: [string, string][] = [
	['ff02::1', 'All devices on this network segment'],
	['ff02::2', 'All routers on this network segment'],
	['ff02::c', 'SSDP: UPnP device discovery'],
	['ff02::16', 'MLDv2: devices reporting which groups they listen to'],
	['ff02::fb', 'mDNS: Bonjour, AirPlay and Chromecast discovery'],
	['ff02::1:2', 'DHCPv6 servers and relays'],
	['ff02::1:3', 'LLMNR: Windows name look-ups'],
	['ff05::1:3', 'DHCPv6 servers across your site'],
];

export const SIZE_NOTES: Record<number, string> = {
	32: 'What a provider gets from its registry.',
	48: 'A typical site or business delegation: 65,536 networks of /64.',
	56: 'What most home internet providers give you: 256 networks of /64.',
	60: 'A small home delegation: 16 networks of /64.',
	64: 'One network segment. SLAAC, the way most devices pick an address, needs exactly /64.',
	96: 'The block NAT64 and IPv4-mapped addresses use: the last 32 bits hold the IPv4 address.',
	127: 'A point-to-point link between two routers.',
	128: 'A single address.',
};
