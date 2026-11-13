/** NET-266: the plain-English lines of the LAN throughput test. */
import type { ThroughputResult } from '$api/tools';
import { formatBitRate } from '$lib/utils/bitrate';

/**
 * "This test runs over eno1 (192.168.1.199, wired, 1 Gbit/s)." Unknown parts are left out: "wired"
 * needs a link speed, because a tunnel (wg0, tailscale0) is neither Wi-Fi nor a cable.
 */
export function pathLine(r: ThroughputResult): string | null {
	if (!r.path) return null;
	const { source_ip, wifi, speed_mbps } = r.path;
	// OLD CODE: const parts = [source_ip, wifi ? 'Wi-Fi' : 'wired', speed_mbps ? … : null]; (review of #266)
	const kind = wifi ? 'Wi-Fi' : speed_mbps ? 'wired' : null;
	const parts = [source_ip, kind, speed_mbps ? formatBitRate(speed_mbps * 1e6) : null];
	return `This test runs over ${r.path.interface} (${parts.filter(Boolean).join(', ')}).`;
}

/** In mirror mode the capture port has no address, so the test can't cross it: say which path it measured. */
export function mirrorNote(r: ThroughputResult): string | null {
	const { mode, interface: port, has_ip } = r.capture;
	if (mode !== 'mirror' || has_ip !== false || !port) return null;
	return `The capture port ${port} has no IP address, so this measures the management path, not the mirror port.`;
}

/** "941 Mbit/s", or "—" for a run that failed. */
export const rate = (bps: number | null | undefined): string => (bps == null ? '—' : formatBitRate(bps));

/** "1 retransmit", "12 retransmits", or "—" when iperf3 gave none. */
export const retransmitsText = (n: number | null): string => (n == null ? '—' : `${n} ${n === 1 ? 'retransmit' : 'retransmits'}`);
