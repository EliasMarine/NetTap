/**
 * The beaconing pair page's words (daemon/api/threat_drilldowns.py's reply in plain English).
 * Text only: every number comes from the reply, and the scan's rule stays in the daemon. Context
 * (a network owner, a name) is described as context; nothing here tells the user a pair is cleared.
 */
import type { BeaconPair } from '$lib/api/threats';
import { fmt } from './drilldown';

// OLD CODE: const MIN_CALLS = 10; (the reply's timing.min_calls is the scan's own threshold)

/** The drill-down page for one pair, opening on `range`. */
export function beaconHref(device: string, server: string, port: number, range: string): string {
	return `/threats/beaconing/${encodeURIComponent(device)}/${encodeURIComponent(server)}/${port}?${new URLSearchParams({ range }).toString()}`;
}

/** "203.0.113.9:443", or "[2001:db8::1]:443" so an IPv6 address's last group isn't read as the port. */
export const hostPort = (ip: string, port: number): string => (ip.includes(':') ? `[${ip}]:${port}` : `${ip}:${port}`);

/** "45 seconds", "60 minutes", "2.5 hours". */
export function intervalWords(seconds: number): string {
	if (seconds < 90) return `${Math.round(seconds)} seconds`;
	if (seconds < 5400) return `${Math.round(seconds / 60)} minutes`;
	return `${Math.round((seconds / 3600) * 10) / 10} hours`;
}

/** "2.6%": a ratio as the page shows jitter. */
export const pct = (ratio: number): string => `${(ratio * 100).toFixed(1)}%`;
const times = (n: number) => `${fmt(n)} ${n === 1 ? 'time' : 'times'}`;
const listed = (names: readonly string[]) =>
	names.length <= 2 ? names.join(' and ') : `${names.slice(0, 2).join(', ')} and ${fmt(names.length - 2)} more`;

/** What the calls are, from the transport, Zeek's service name and the port. */
export function serviceWords(pair: Pick<BeaconPair, 'port' | 'transports' | 'services'>): string {
	const transport = pair.transports[0]?.name;
	const service = pair.services[0]?.name;
	if (transport === 'icmp') return 'pings (ICMP), not connections to a service';
	if (service === 'quic') return 'encrypted web traffic over QUIC';
	if (service === 'ssl' || pair.port === 443) return 'encrypted connections (TLS), the kind web pages and apps use';
	if (service === 'ssh' || pair.port === 22) return 'SSH sessions (remote login)';
	if (service === 'http' || pair.port === 80) return 'unencrypted web requests (HTTP)';
	return `connections to port ${pair.port}${service ? ` (${service.toUpperCase()})` : ''}`;
}

// OLD CODE: BlocklistWords and blocklistWords lived here; moved to utils/drilldown.ts so the address page renders the same words

export interface BeaconContext {
	/** The window in words: "last 24 hours". */
	words: string;
	/** The device's name from the registry, when it has one. */
	deviceName: string | null;
	/** "Google LLC (AS15169)", from GeoIP; null when unknown or not looked up. */
	owner: string | null;
	anycast: boolean;
}

const who = (pair: BeaconPair, ctx: BeaconContext) => (ctx.deviceName ? `${ctx.deviceName} (${pair.device})` : pair.device);
const named = (pair: BeaconPair) => [...new Set([...pair.dns_names.map((n) => n.name), ...pair.tls_names.flatMap((n) => (n.name ? [n.name] : []))])];

/** The opening: what the timing shows, one branch per status, naming whatever fell short. */
function timingLine(pair: BeaconPair, ctx: BeaconContext): string {
	const t = pair.timing;
	const lead = `${who(pair, ctx)} contacted ${hostPort(pair.server, pair.port)}`;
	// OLD CODE: if (t.status === 'periodic' && t.beacon) { … t.beacon.interval_seconds … t.beacon.jitter_coefficient … } (the same figures as mean_gap_seconds and jitter)
	if (t.status === 'periodic' && t.mean_gap_seconds !== null && t.jitter !== null) {
		return `${lead} about every ${intervalWords(t.mean_gap_seconds)}, ${times(pair.connections)} in the ${ctx.words}; the gaps between calls typically varied by only ${pct(t.jitter)}.`;
	}
	if (t.status === 'irregular' && t.mean_gap_seconds !== null && t.jitter !== null) {
		return `${lead} ${times(pair.connections)} in the ${ctx.words}, on average every ${intervalWords(t.mean_gap_seconds)}, but the gaps varied by ${pct(t.jitter)}. That's too uneven for NetTap's check, which lists pairs whose gaps vary by less than ${Math.round(t.max_jitter * 100)}%, so it wouldn't list this pair for this window.`;
	}
	if (t.status === 'too_few') {
		// which of the two quantities fell short, named with the scan's own threshold
		return pair.connections < t.min_calls
			? `${lead} ${times(pair.connections)} in the ${ctx.words}; NetTap needs at least ${t.min_calls} calls to judge a schedule.`
			: `${lead} ${times(pair.connections)} in the ${ctx.words}, but the calls fell in only ${fmt(t.slots)} distinct 10-second intervals; NetTap needs ${t.min_calls} occupied intervals to judge the timing.`;
	}
	return `${lead} ${times(pair.connections)} in the ${ctx.words}: too many calls to time them all at once, so this page can't say whether they keep a schedule. Choose a shorter range.`;
}

/** The explanation, every figure from the reply. */
export function beaconStory(pair: BeaconPair, ctx: BeaconContext): string[] {
	const names = named(pair);
	const ti = pair.threat_intel;
	return [
		timingLine(pair, ctx),
		`These are ${serviceWords(pair)}.`,
		names.length > 0
			? `In this window the device called this address ${listed(names)}.`
			: "In this window the device never looked this address up or named it in TLS, so there's no name to go on.",
		ctx.anycast
			? 'It is an anycast address, answered from many places, so its location says little.'
			: ctx.owner
				? `The network belongs to ${ctx.owner}. That says whose network it is, not which app or customer uses it.`
				: "NetTap doesn't know whose network this is.",
		"Malware that “phones home” looks like this, but so do update checkers, chat apps and smart-home devices. What matters is whether an app you expect on this device makes these calls.",
		ti === null
			? "NetTap couldn't check every blocklist alert in this window, so it can't say whether a list names this address."
			: ti.matched
				? `A blocklist names this address: ${ti.feeds.map((f) => f.label).join(', ')}.`
				: "No blocklist NetTap knows names this address. That isn't a clean bill of health: lists only hold addresses already reported.",
	];
}

/** What to do. The first step is always to find the app; no branch says nothing needs doing. */
export function beaconTodo(pair: BeaconPair, ctx: BeaconContext): string[] {
	return [
		`Find the app on ${who(pair, ctx)} that makes these calls, and confirm this destination is expected for it.`,
		...(pair.threat_intel?.matched ? ['A blocklist names this address: disconnect the device from the network and check it for malware.'] : []),
		...(pair.threat_intel === null ? ['Check again over a shorter range, so the blocklist alerts can all be read.'] : []),
		...(pair.timing.status === 'capped' ? ['Choose a shorter range so the calls can be timed.'] : []),
		...(named(pair).length === 0 ? ["With no name to go on, look at the device's other connections for the same app."] : []),
	];
}

/** How the scan's confidence adds up (daemon/services/threat_detection.py _beacon_confidence), in words. */
export const CONFIDENCE_HOW =
	'Confidence adds up to 100: up to 50 for steady timing (gaps varying by under 5%: 50, under 10%: 35, under 15%: 20), up to 30 for many calls (over 100: 30, over 50: 20, over 20: 10), and 20 when the interval is within 10% of a common timer (30 seconds; 1, 2, 5, 10, 15 or 30 minutes; 1 hour).';
