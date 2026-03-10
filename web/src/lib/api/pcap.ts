/**
 * Client-side API helpers for PCAP search endpoints.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PcapFile {
	file: string;
	name: string;
	size_bytes: number;
	modified: string;
	relative_path: string;
}

export interface PcapFilesResponse {
	count: number;
	files: PcapFile[];
}

export interface PcapSearchResult extends PcapFile {
	matching_packets: number;
}

export interface PcapSearchResponse {
	filter: string;
	count: number;
	results: PcapSearchResult[];
}

export interface PcapPacket {
	frame_number: string;
	timestamp: string;
	source: string;
	destination: string;
	protocol: string;
	length: string;
	info: string;
}

export interface PcapPreviewResponse {
	file: string;
	filter: string | null;
	count: number;
	packets: PcapPacket[];
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function buildQuery(params: Record<string, string | number | undefined>): string {
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

/**
 * List available PCAP files.
 */
export async function getPcapFiles(
	opts: { from?: string; to?: string } = {}
): Promise<PcapFilesResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/pcap/files${query}`);

	if (!res.ok) {
		return { count: 0, files: [] };
	}

	return res.json();
}

/**
 * Search PCAPs by BPF filter.
 */
export async function searchPcaps(
	filter: string,
	opts: { from?: string; to?: string } = {}
): Promise<PcapSearchResponse> {
	const query = buildQuery({ filter, from: opts.from, to: opts.to });
	const res = await fetch(`/api/pcap/search${query}`);

	if (!res.ok) {
		const data = await res.json().catch(() => ({ error: 'Search failed' }));
		throw new Error(data.error || `Search failed: ${res.status}`);
	}

	return res.json();
}

/**
 * Preview packets from a PCAP file.
 */
export async function previewPcap(
	file: string,
	opts: { filter?: string; limit?: number } = {}
): Promise<PcapPreviewResponse> {
	const query = buildQuery({ file, filter: opts.filter, limit: opts.limit });
	const res = await fetch(`/api/pcap/preview${query}`);

	if (!res.ok) {
		const data = await res.json().catch(() => ({ error: 'Preview failed' }));
		throw new Error(data.error || `Preview failed: ${res.status}`);
	}

	return res.json();
}

/**
 * Get download URL for filtered PCAP.
 */
export function getDownloadUrl(
	filter: string,
	opts: { from?: string; to?: string } = {}
): string {
	const query = buildQuery({ filter, from: opts.from, to: opts.to });
	return `/api/pcap/download${query}`;
}

/**
 * Get download URL for a single PCAP file (no filter).
 */
export function getFileDownloadUrl(file: string): string {
	const query = buildQuery({ file });
	return `/api/pcap/download-file${query}`;
}

// ---------------------------------------------------------------------------
// BPF filter quick filters
// ---------------------------------------------------------------------------

export const QUICK_FILTERS = [
	{ label: 'DNS Traffic', filter: 'dns' },
	{ label: 'HTTP Traffic', filter: 'http || tls' },
	{ label: 'SSH Traffic', filter: 'ssh' },
	{ label: 'DHCP Traffic', filter: 'dhcp' },
	{ label: 'ICMP', filter: 'icmp' },
	{ label: 'ARP', filter: 'arp' },
] as const;

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

/**
 * Format bytes into human-readable string.
 */
export function formatBytes(bytes: number): string {
	if (bytes === 0) return '0 B';
	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	const i = Math.floor(Math.log(bytes) / Math.log(1024));
	return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}
