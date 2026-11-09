/**
 * NET-226: a device's IPv6 traffic is matched to it by MAC address. Where the daemon couldn't
 * do that safely it leaves the traffic out and says why (`ipv6_left_out_reason`).
 */
export type Ipv6LeftOutReason = 'router' | 'no_gateway';

interface Covered {
	ip: string;
	ipv6_left_out?: number;
	ipv6_left_out_reason?: Ipv6LeftOutReason | null;
}

/** Why some of a device's IPv6 isn't counted, said of `who`; null when nothing was left out. */
export function ipv6LeftOutText(reason: Ipv6LeftOutReason | null | undefined, who = 'This device'): string | null {
	if (reason === 'no_gateway') return "IPv6 traffic other than link-local isn't counted for this period: no internet traffic showed which device is the router.";
	if (reason === 'router') return `${who} forwards other devices' traffic (it's the router), so only its link-local IPv6 is counted.`;
	return null;
}

/** The notes a list of devices needs: one per router, and one for the whole period. */
export function ipv6ListNotes(rows: readonly Covered[]): string[] {
	const notes = rows
		.filter((d) => (d.ipv6_left_out ?? 0) > 0)
		.map((d) => ipv6LeftOutText(d.ipv6_left_out_reason, `The device at ${d.ip}`))
		.filter((n): n is string => n !== null);
	return [...new Set(notes)];
}
