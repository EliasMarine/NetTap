/**
 * NET-267: the plain-English result line of the path MTU check, and each probe in words.
 * The wording says what the probes showed; silence never reads as a known limit.
 */
import type { MtuProbe, PathMtuResult } from '$api/tools';

const SILENT_ABOVE =
	'This can be an MTU problem (common over VPNs: small pings work, big transfers stall), or the destination may drop larger pings.';

/** The sentence for a finished check; null when there is none (the check could not start). */
export function mtuSummary(r: PathMtuResult): string | null {
	const t = r.target;
	const largest = r.largest_confirmed;
	switch (r.status) {
		case 'interface':
			return `Full-size packets (${largest} bytes) reach ${t} from NetTap.`;
		case 'icmp_bound':
			return `The path to ${t} carries packets up to ${largest} bytes. A router reported an MTU of ${r.icmp_reported_mtu}.`;
		case 'unanswered_above': {
			const above = r.first_unanswered
				? `Probes of ${r.first_unanswered} bytes and up got no reply`
				: 'Larger probes did not get through';
			const report = r.icmp_reported_mtu ? ` A router reported an MTU of ${r.icmp_reported_mtu}, which the probes did not confirm.` : '';
			return `Largest confirmed: ${largest} bytes. ${above}, so the upper limit is unknown. ${SILENT_ABOVE}${report}`;
		}
		case 'local_limit':
			// every probe above the confirmed size failed inside NetTap, so the path above it was never tested
			return r.local_mtu
				? `Largest confirmed: ${largest} bytes. NetTap would not send larger packets: it still holds a ${r.local_mtu}-byte limit for this path, from an earlier router report or a route setting (a cached report clears within 10 minutes), so the upper limit is unknown.`
				: `Largest confirmed: ${largest} bytes. NetTap would not send larger packets (ping reported an error), so the upper limit is unknown.`;
		case 'floor_unanswered':
			// OLD CODE: return `${t} answers small pings but not ${r.first_unanswered}-byte ones. …`; (review: null read as "null-byte")
			return `${t} answers small pings but not ${r.first_unanswered ? `${r.first_unanswered}-byte` : 'larger'} ones. That points to a possible MTU problem.`;
		case 'no_ping_reply':
			return `${t} did not answer ping, so the MTU cannot be tested from NetTap.`;
		case 'unreliable':
			return `Replies from ${t} were inconsistent, so no size can be confirmed.`;
		case 'stopped':
			return largest
				? `The check stopped before it finished. Largest confirmed so far: ${largest} bytes, so the upper limit is unknown.`
				: 'The check stopped before it finished, so no size was confirmed.';
		default:
			return null;
	}
}

/** The result card's sub line; a name target also shows the address it resolved to. */
export function mtuPathLine(r: PathMtuResult): string {
	const tested = r.resolved_ip && r.resolved_ip !== r.target ? `Tested ${r.resolved_ip} · ` : '';
	return `${tested}${r.interface ?? 'interface unknown'} · interface MTU ${r.interface_mtu ?? 'unknown'} · don't-fragment pings, IP packet sizes in bytes`;
}

/** One probe's result: "Reply", "No reply (2 tries)", "Router: too big, MTU 1420", … */
export function probeLabel(p: MtuProbe): string {
	switch (p.result) {
		case 'reply':
			return 'Reply';
		case 'no_reply':
			return 'No reply (2 tries)';
		case 'icmp_too_big':
			return p.mtu ? `Router: too big, MTU ${p.mtu}` : 'Router: too big';
		default:
			return p.mtu ? `Not sent: NetTap's limit is ${p.mtu}` : 'Not sent: ping error';
	}
}
