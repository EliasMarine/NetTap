/**
 * Client-side API helpers for LAN security endpoints.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LanAnomaly {
	type: string;
	severity: string;
	description: string;
	detected_at: string;
	// ARP spoofing fields
	ip?: string;
	mac_addresses?: string[];
	mac_count?: number;
	event_count?: number;
	// Rogue DHCP fields
	server_ip?: string;
	server_mac?: string;
	offer_count?: number;
	legitimate_server?: string;
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function buildQuery(params: Record<string, string | undefined>): string {
	const qs = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value !== undefined && value !== '') {
			qs.set(key, String(value));
		}
	}
	const str = qs.toString();
	return str ? `?${str}` : '';
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

export async function getLanAnomalies(
	opts: { from?: string; to?: string } = {}
): Promise<{ from: string; to: string; anomalies: LanAnomaly[]; count: number }> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/lan/anomalies${query}`);

	if (!res.ok) {
		return { from: '', to: '', anomalies: [], count: 0 };
	}

	return res.json();
}

export async function getArpSpoofing(
	opts: { from?: string; to?: string } = {}
): Promise<{ from: string; to: string; alerts: LanAnomaly[]; count: number }> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/lan/arp-spoofing${query}`);

	if (!res.ok) {
		return { from: '', to: '', alerts: [], count: 0 };
	}

	return res.json();
}

export async function getRogueDhcp(
	opts: { from?: string; to?: string } = {}
): Promise<{ from: string; to: string; alerts: LanAnomaly[]; count: number }> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/lan/rogue-dhcp${query}`);

	if (!res.ok) {
		return { from: '', to: '', alerts: [], count: 0 };
	}

	return res.json();
}
