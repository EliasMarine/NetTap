/**
 * Where an IP or a domain drills down to (NET-160).
 *
 * A LAN address goes to its device page, anything else to the address page. "LAN" is the
 * daemon's own policy (/api/network/lan), refetched every 5 minutes: IPv4 in its subnets
 * (every RFC 1918 range when it lists none), never IPv6. Until the policy loads, an address
 * links to the address page, which knows the daemon's answer and offers the device page.
 */
import { derived, readable, type Readable } from 'svelte/store';
import { getLanPolicy, type LanPolicy } from '$lib/api/network';

export const LAN_REFRESH_MS = 5 * 60_000;

const RFC1918 = ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'];

/** A dotted-quad IPv4 address as a 32-bit number, or null for anything else (IPv6 included). */
export function ipv4ToNumber(ip: string): number | null {
	const parts = ip.trim().split('.');
	if (parts.length !== 4 || !parts.every((p) => /^\d{1,3}$/.test(p) && Number(p) <= 255)) return null;
	return parts.reduce((n, p) => n * 256 + Number(p), 0);
}

/** True when `ip` is in `cidr` ("a.b.c.d/n"); false for a malformed CIDR. */
export function inCidr(ip: number, cidr: string): boolean {
	const [base, bitsText] = cidr.split('/');
	const net = ipv4ToNumber(base ?? '');
	const bits = Number(bitsText);
	if (net === null || !/^\d{1,2}$/.test(bitsText ?? '') || bits > 32) return false;
	// 2 ** (32 - bits) addresses per block; integer division keeps /0 and /32 exact without bit shifts
	const size = 2 ** (32 - bits);
	return Math.floor(ip / size) === Math.floor(net / size);
}

/** On the LAN by `policy`: null while the policy hasn't loaded, false for IPv6 and non-addresses. */
export function lanStatus(policy: LanPolicy | null, ip: string): boolean | null {
	if (!policy) return null;
	const n = ipv4ToNumber(ip);
	if (n === null) return false;
	const subnets = policy.subnets.length ? policy.subnets : RFC1918;
	return subnets.some((cidr) => inCidr(n, cidr));
}

/** The page an address drills down to: its device page only when the policy says LAN. */
export function addressHref(policy: LanPolicy | null, ip: string): string {
	const enc = encodeURIComponent(ip);
	return lanStatus(policy, ip) === true ? `/devices/${enc}` : `/address/${enc}`;
}

/** The domain page, for the name as the daemon matches it: one trailing dot dropped, lower case. */
export function domainHref(name: string): string {
	return `/domain/${encodeURIComponent(name.trim().replace(/\.$/, '').toLowerCase())}`;
}

/**
 * The policy, fetched when the first link subscribes and every 5 minutes while any does. A
 * failed fetch keeps the last policy (or none). The same version keeps the same object, so
 * links only re-render when the subnets change.
 */
export const lanPolicy: Readable<LanPolicy | null> = readable<LanPolicy | null>(null, (set) => {
	// Server rendering shares this module between requests; links render with no policy there
	if (typeof window === 'undefined') return;
	let current: LanPolicy | null = null;
	let stopped = false;
	const load = () =>
		getLanPolicy().then(
			(policy) => {
				if (stopped || policy.version === current?.version) return;
				current = policy;
				set(policy);
			},
			() => {},
		);
	void load();
	const timer = setInterval(load, LAN_REFRESH_MS);
	return () => {
		stopped = true;
		clearInterval(timer);
	};
});

/** `$isLan(ip)`: true, false, or null while the policy hasn't loaded. */
export const isLan: Readable<(ip: string) => boolean | null> = derived(lanPolicy, (p) => (ip: string) => lanStatus(p, ip));

/** `$ipHref(ip)`: `/devices/<ip>` on the LAN, `/address/<ip>` otherwise or before the policy loads. */
export const ipHref: Readable<(ip: string) => string> = derived(lanPolicy, (p) => (ip: string) => addressHref(p, ip));
