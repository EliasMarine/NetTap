/**
 * DHCP gateway subnet validation for the setup wizard.
 *
 * Mirrors the daemon's checks on `/api/setup/configure` (private range,
 * prefix 16-28, network address) so the user gets plain-English feedback
 * before anything is saved. The daemon still validates and also checks
 * every host network for overlap, so this is a convenience, not the gate.
 */

export const DEFAULT_DHCP_SUBNET = '10.77.0.0/24';

export interface SubnetValidation {
	valid: boolean;
	error: string;
}

// Dotted quad with no leading zeros (the daemon's `ipaddress` rejects them).
const OCTET = '(25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)';
const IPV4_RE = new RegExp(`^${OCTET}\\.${OCTET}\\.${OCTET}\\.${OCTET}$`);
const CIDR_RE = new RegExp(`^(${OCTET}\\.${OCTET}\\.${OCTET}\\.${OCTET})/(\\d{1,2})$`);

const MIN_PREFIX = 16;
const MAX_PREFIX = 28;

/** RFC 1918 ranges as [first address, prefix]. */
const PRIVATE_RANGES: Array<[string, number]> = [
	['10.0.0.0', 8],
	['172.16.0.0', 12],
	['192.168.0.0', 16],
];

/** IPv4 dotted quad to an unsigned number, or null if it isn't one. */
function toNumber(ip: string): number | null {
	if (!IPV4_RE.test(ip)) return null;
	return ip.split('.').reduce((acc, octet) => acc * 256 + Number(octet), 0);
}

function toDotted(n: number): string {
	return [24, 16, 8, 0].map((shift) => Math.floor(n / 2 ** shift) % 256).join('.');
}

/** True if `ip` falls inside the block that starts at `network` with `prefix`. */
function inBlock(ip: number, network: number, prefix: number): boolean {
	const size = 2 ** (32 - prefix);
	return Math.floor(ip / size) === Math.floor(network / size);
}

/**
 * Validate the subnet NetTap will hand out over DHCP.
 *
 * @param cidr          what the user typed, e.g. "10.77.0.0/24"
 * @param nicAddresses  IPv4 addresses of NetTap's ports (bare or with "/nn")
 */
export function validateDhcpSubnet(cidr: string, nicAddresses: string[]): SubnetValidation {
	const match = CIDR_RE.exec(cidr);
	if (!match) {
		return { valid: false, error: `Enter the subnet like ${DEFAULT_DHCP_SUBNET}.` };
	}

	const address = match[1];
	const prefix = Number(match[6]);
	if (prefix < MIN_PREFIX || prefix > MAX_PREFIX) {
		return {
			valid: false,
			error: `The size must be between /${MIN_PREFIX} and /${MAX_PREFIX}. /24 (254 devices) suits most homes.`,
		};
	}

	const ip = toNumber(address) as number;
	const size = 2 ** (32 - prefix);
	const network = ip - (ip % size);
	if (network !== ip) {
		const suggestion = `${toDotted(network)}/${prefix}`;
		return {
			valid: false,
			error: `${cidr} isn't the start of a subnet. Did you mean ${suggestion}?`,
		};
	}

	// Prefix is at least /16, so checking the first address is enough.
	const isPrivate = PRIVATE_RANGES.some(([start, len]) => inBlock(ip, toNumber(start) as number, len));
	if (!isPrivate) {
		return {
			valid: false,
			error: 'Use a private range: 10.x.x.x, 172.16.x.x to 172.31.x.x, or 192.168.x.x.',
		};
	}

	for (const raw of nicAddresses) {
		const nicIp = toNumber((raw || '').split('/')[0].trim());
		if (nicIp !== null && inBlock(nicIp, network, prefix)) {
			return {
				valid: false,
				error: `This subnet includes ${toDotted(nicIp)}, an address NetTap already uses on your network. Pick a different subnet.`,
			};
		}
	}

	return { valid: true, error: '' };
}

export interface StaticAddressHint {
	ip: string;
	mask: string;
	router: string;
}

/**
 * A fixed address a laptop can use on the router's network to reach its admin
 * page when no DHCP server answers (NetTap down, router DHCP off; design §7).
 *
 * Picks host .20 of the router's network (or the first free host in a tiny one),
 * skipping NetTap's own address and the router.
 *
 * @param upstream  NetTap's router-side address ("192.168.1.50/24") and the router
 * @returns null when upstream is unknown or doesn't parse
 */
export function staticAddressHint(
	upstream: { address: string; gateway: string } | null
): StaticAddressHint | null {
	if (!upstream) return null;
	const [addr, prefixText] = (upstream.address || '').split('/');
	const own = toNumber(addr);
	const router = toNumber(upstream.gateway || '');
	const prefix = Number(prefixText);
	if (own === null || router === null || !Number.isInteger(prefix) || prefix < 8 || prefix > 30) {
		return null;
	}

	const size = 2 ** (32 - prefix);
	const network = own - (own % size);
	if (!inBlock(router, network, prefix)) return null;

	const lastHost = size - 2;
	const offsets = [20, 21, 22, ...Array.from({ length: Math.min(lastHost, 19) }, (_, i) => i + 1)];
	const offset = offsets.find((o) => o <= lastHost && network + o !== own && network + o !== router);
	if (offset === undefined) return null;

	return { ip: toDotted(network + offset), mask: toDotted(2 ** 32 - size), router: upstream.gateway };
}
