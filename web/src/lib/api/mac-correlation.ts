/**
 * Client-side API helpers for MAC correlation endpoints.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RandomizedMac {
	mac: string;
	connection_count: number;
	first_seen: string | null;
	last_seen: string | null;
	total_bytes: number;
	top_destinations: string[];
}

export interface RandomizedMacsResponse {
	from: string;
	to: string;
	count: number;
	randomized_macs: RandomizedMac[];
}

export interface DnsPattern {
	domain: string;
	count: number;
}

export interface TlsFingerprint {
	ja3: string;
	count: number;
}

export interface DestinationIp {
	ip: string;
	count: number;
}

export interface TimingEntry {
	hour: string;
	connections: number;
}

export interface TrafficProfile {
	orig_bytes: number;
	resp_bytes: number;
	total_bytes: number;
	orig_packets: number;
	resp_packets: number;
	avg_packet_size: number;
}

export interface BehavioralFingerprint {
	mac: string;
	is_randomized: boolean;
	dns_patterns: DnsPattern[];
	tls_fingerprints: TlsFingerprint[];
	destination_ips: DestinationIp[];
	timing_pattern: TimingEntry[];
	traffic_profile: TrafficProfile;
}

export interface FingerprintResponse {
	from: string;
	to: string;
	fingerprint: BehavioralFingerprint;
}

export interface MergeSuggestion {
	mac_randomized: string;
	mac_real: string;
	confidence: number;
	confidence_level: string;
	shared_dns: string[];
	shared_ja3: string[];
	shared_destinations: string[];
}

export interface MergeSuggestionsResponse {
	from: string;
	to: string;
	count: number;
	suggestions: MergeSuggestion[];
}

export interface MergeRecord {
	id: string;
	mac_randomized: string;
	mac_real: string;
	merged_at: string;
	status: string;
	undone_at?: string;
}

export interface MergeHistoryResponse {
	count: number;
	merges: MergeRecord[];
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function buildQuery(params: Record<string, string | undefined>): string {
	const qs = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value !== undefined && value !== '') {
			qs.set(key, value);
		}
	}
	const str = qs.toString();
	return str ? `?${str}` : '';
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get detected randomized MACs.
 */
export async function getRandomizedMacs(
	opts: { from?: string; to?: string } = {}
): Promise<RandomizedMacsResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/mac/randomized${query}`);

	if (!res.ok) {
		return { from: '', to: '', count: 0, randomized_macs: [] };
	}

	return res.json();
}

/**
 * Get behavioral fingerprint for a MAC address.
 */
export async function getFingerprint(
	mac: string,
	opts: { from?: string; to?: string } = {}
): Promise<FingerprintResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/mac/fingerprint/${encodeURIComponent(mac)}${query}`);

	if (!res.ok) {
		throw new Error(`Failed to get fingerprint: ${res.status}`);
	}

	return res.json();
}

/**
 * Get merge suggestions.
 */
export async function getMergeSuggestions(
	opts: { from?: string; to?: string } = {}
): Promise<MergeSuggestionsResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/mac/merge-suggestions${query}`);

	if (!res.ok) {
		return { from: '', to: '', count: 0, suggestions: [] };
	}

	return res.json();
}

/**
 * Merge two devices.
 */
export async function mergeDevices(
	macRandomized: string,
	macReal: string
): Promise<{ result: string; merge: MergeRecord }> {
	const res = await fetch('/api/mac/merge', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ mac_randomized: macRandomized, mac_real: macReal }),
	});

	if (!res.ok) {
		throw new Error(`Failed to merge devices: ${res.status}`);
	}

	return res.json();
}

/**
 * Get merge history.
 */
export async function getMergeHistory(): Promise<MergeHistoryResponse> {
	const res = await fetch('/api/mac/merge-history');

	if (!res.ok) {
		return { count: 0, merges: [] };
	}

	return res.json();
}

/**
 * Undo a previous merge.
 */
export async function undoMerge(
	mergeId: string
): Promise<{ result: string; merge_id: string }> {
	const res = await fetch('/api/mac/undo-merge', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ merge_id: mergeId }),
	});

	if (!res.ok) {
		throw new Error(`Failed to undo merge: ${res.status}`);
	}

	return res.json();
}
