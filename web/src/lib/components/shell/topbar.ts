/** Pure helpers for the top bar (search hand-off and the "Updated" text). */
import type { RegistryDevice } from '$api/devices-registry';
import { domainHref } from '$lib/stores/lan';
import { toNumber } from '$lib/utils/dhcpSubnet';
import { isHostName } from '$lib/utils/drilldown';

// OLD CODE START — NET-202: every IP went to Log Explorer, and a MAC passed the IPv6 test
// const IPV4 = /^(\d{1,3})(\.\d{1,3}){3}$/;
// const IPV6 = /^[0-9a-f:]+$/i;
//
// /** Where a global search goes: Log Explorer filtered by IP, or searching for the text. */
// export function searchTarget(text: string): string | null {
// 	const q = text.trim();
// 	if (!q) return null;
// 	const isIp = IPV4.test(q) || (q.includes(':') && IPV6.test(q));
// 	return isIp ? `/logs?ip=${encodeURIComponent(q)}` : `/logs?query=${encodeURIComponent(q)}`;
// }
// OLD CODE END

/** A device the search can open, by its stored MAC. */
export interface Suggestion {
	label: string;
	detail: string;
	href: string;
}

/** Where a search goes: a page, or the devices sharing the typed name for the owner to pick from. */
export type SearchTarget = { href: string } | { matches: RegistryDevice[] };

const SUGGESTION_LIMIT = 6;

/** A whole IPv4 address, or an IPv6 address the platform's URL parser accepts (a MAC never is). */
export function isSearchIp(text: string): boolean {
	if (toNumber(text) !== null) return true;
	// the character check keeps "::1]#[" (a valid URL, not an address) out of the parser
	if (!text.includes(':') || !/^[0-9a-f:.]+$/i.test(text)) return false;
	try {
		new URL(`http://[${text}]`);
		return true;
	} catch {
		return false;
	}
}

const deviceHref = (d: RegistryDevice) => `/devices/mac/${encodeURIComponent(d.mac)}`;

/** Every name NetTap knows a device by. */
function names(d: RegistryDevice): string[] {
	return [d.display_name, d.custom_name, d.discovered_name, d.friendly_name, ...(d.hostnames ?? [])].filter((n): n is string => !!n);
}

/**
 * Where a submitted search goes (NET-202). An IP opens its own page (`ipHref`: the device page on
 * the LAN, the address page otherwise); one device whose MAC or name is the text opens its page;
 * several are returned to pick from; a domain opens its page; anything else searches Log Explorer.
 */
export function searchTarget(text: string, ipHref: (ip: string) => string, devices: RegistryDevice[] = []): SearchTarget | null {
	const q = text.trim();
	if (!q) return null;
	if (isSearchIp(q)) return { href: ipHref(q) };
	const key = q.toLowerCase();
	const exact = devices.filter((d) => d.mac.toLowerCase() === key || names(d).some((n) => n.toLowerCase() === key));
	const macs = new Set(exact.map((d) => d.mac.toLowerCase()));
	if (macs.size === 1) return { href: deviceHref(exact[0]) };
	if (macs.size > 1) return { matches: exact };
	if (q.includes('.') && isHostName(q)) return { href: domainHref(q) };
	return { href: `/logs?query=${encodeURIComponent(q)}` };
}

/** A device as a search option: its name, then its first IP and MAC so same-named devices differ. */
export function toSuggestion(d: RegistryDevice): Suggestion {
	return { label: d.display_name || d.mac, detail: d.ips[0] ? `${d.ips[0]} · ${d.mac}` : d.mac, href: deviceHref(d) };
}

/** Up to 6 devices whose name, hostname, IP or MAC contains the text; name matches first. */
export function deviceSuggestions(devices: RegistryDevice[], text: string): Suggestion[] {
	const key = text.trim().toLowerCase();
	const has = (s: string) => s.toLowerCase().includes(key);
	const byName = devices.filter((d) => names(d).some(has));
	const named = new Set(byName);
	const byAddress = devices.filter((d) => !named.has(d) && [d.mac, ...d.ips].some(has));
	return [...byName, ...byAddress].slice(0, SUGGESTION_LIMIT).map(toSuggestion);
}

/** "Updated 12 s ago", from the page's last fully successful load. */
export function updatedText(updatedAt: number | null, now: number): string {
	if (updatedAt === null) return 'Not updated yet';
	const s = Math.max(0, Math.floor((now - updatedAt) / 1000));
	if (s < 5) return 'Updated just now';
	if (s < 60) return `Updated ${s} s ago`;
	if (s < 3600) return `Updated ${Math.floor(s / 60)} min ago`;
	const at = new Date(updatedAt);
	return `Updated at ${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`;
}
