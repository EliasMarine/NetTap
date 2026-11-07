/**
 * Client-side API helpers for packet analysis (NET-188).
 * Wraps daemon endpoints at /api/packets.
 *
 * Times and other decimal values stay strings ("1700000000.25"): the daemon works in
 * nanoseconds and a JS number would round them. A search's `manifest` goes back to the
 * daemon exactly as it came.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type PacketRowLimit = 100 | 250 | 1000;

export interface CaptureFile {
	id: string;
	name: string;
	size_bytes: number;
	/** ISO time */
	modified: string;
	/** Still being written, so its contents may change */
	recent: boolean;
	state: 'indexed' | 'pending' | 'failed';
	/** Epoch seconds as a decimal string; null until indexed */
	first: string | null;
	last: string | null;
	packets: number | null;
	encapsulation: string | null;
	cut_short: boolean;
	error: string | null;
}

export interface CapturesResponse {
	files: CaptureFile[];
	count: number;
	bytes_total: number;
	/** Epoch seconds as a decimal string */
	oldest_packet: string | null;
	unindexed: number;
	failed: number;
	limits: {
		max_window_seconds: number;
		max_files: number;
		max_bytes: number;
		rows: PacketRowLimit[];
	};
}

export interface PacketSearchRequest {
	filter: string;
	/** Epoch seconds as decimal strings */
	from: string;
	to: string;
	limit: PacketRowLimit;
}

/** Opaque to the page: pass it back to getPacket and downloadPackets unchanged. */
export interface PacketManifest {
	from: string;
	to: string;
	filter: string;
	files: { id: string; size: number; mtime_ns: string; recent: boolean }[];
	frames: { n: number; t: string; cap_len: number; md5: string }[];
}

export interface PacketRow {
	n: number;
	/** Epoch seconds as a decimal string */
	t: string;
	len: number;
	cap_len: number;
	md5: string;
	protocol: string;
	info: string;
	fields: Record<string, string[]>;
}

export interface PacketSearchResult {
	rows: PacketRow[];
	termination: 'eof' | 'limit' | 'deadline';
	complete: boolean;
	provisional: boolean;
	message: string | null;
	manifest: PacketManifest;
	files: { id: string; size_bytes: number; first: string | null; last: string | null; cut_short: boolean }[];
	skipped_files: { id: string; error: string | null; modified: string }[];
	window: {
		requested: { from: string; to: string };
		effective: { from: string; to: string };
		from_iso: string;
		to_iso: string;
	};
	filter: string;
	limit: PacketRowLimit;
	tshark_version: string | null;
	seconds: number;
}

/** One node of a packet's dissection tree (TShark's PDML). */
export interface PacketNode {
	kind: 'proto' | 'field';
	name: string;
	showname: string;
	show: string;
	value: string;
	pos: number | null;
	size: number | null;
	hide: boolean;
	children: PacketNode[];
	/** Top-level layers only: whether its fields' byte ranges were checked */
	markable?: boolean;
	/** [pos, size] in bytes_hex, only where proven against the bytes */
	mark?: [number, number] | null;
}

export interface PacketDetail {
	n: number;
	t: string;
	len: number;
	cap_len: number;
	md5: string;
	layers: PacketNode[];
	bytes_hex: string;
	marking: 'headers' | 'none';
}

export interface FieldSuggestion {
	field: string;
	name: string;
	type: string;
	description: string;
}

export interface FieldsResponse {
	prefix: string;
	fields: FieldSuggestion[];
	more: boolean;
}

/**
 * A non-OK reply. The page tells 409 (the captures changed), 503 (busy or still
 * indexing) and 507 apart by `status`; `message` is the daemon's own reason.
 */
export class PacketApiError extends Error {
	status: number;
	detail?: string;

	constructor(message: string, status: number, detail?: string) {
		super(message);
		this.name = 'PacketApiError';
		this.status = status;
		this.detail = detail;
	}
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

async function failure(res: Response): Promise<PacketApiError> {
	const data: { error?: unknown; detail?: unknown } | null = await res.json().catch(() => null);
	const message = typeof data?.error === 'string' && data.error ? data.error : `HTTP ${res.status}`;
	return new PacketApiError(message, res.status, typeof data?.detail === 'string' ? data.detail : undefined);
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
	const res = await fetch(url, init);
	if (!res.ok) throw await failure(res);
	// A signed-out request gets 401 above (NET-197); a 2xx that isn't JSON is not the daemon's answer either
	return res.json().catch(() => {
		throw new PacketApiError('NetTap sent an unexpected reply. Sign in again and retry.', res.status);
	});
}

const post = (body: unknown): RequestInit => ({
	method: 'POST',
	headers: { 'Content-Type': 'application/json' },
	body: JSON.stringify(body),
});

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

/** The saved capture files and what the daemon allows in one search. */
export function getCaptures(): Promise<CapturesResponse> {
	return request('/api/packets/captures');
}

/** Run a display-filter search over a window. Can take up to ~48 s. */
export function searchPackets(body: PacketSearchRequest): Promise<PacketSearchResult> {
	return request('/api/packets/search', post(body));
}

/** One packet of a search, fully dissected. Can take up to ~48 s. */
export function getPacket(manifest: PacketManifest, frame: number): Promise<PacketDetail> {
	return request('/api/packets/packet', post({ manifest, frame }));
}

/** Resolves when TShark accepts the filter; rejects (400) with TShark's message when not. */
export function checkFilter(filter: string): Promise<{ ok: true; filter: string }> {
	return request('/api/packets/check-filter', post({ filter }));
}

/** Field names starting with `prefix` (the daemon wants at least 3 letters). */
export function suggestFields(prefix: string, signal?: AbortSignal): Promise<FieldsResponse> {
	return request(`/api/packets/fields?${new URLSearchParams({ prefix })}`, { signal });
}

/**
 * A search's packets as a pcap. Rejects if the daemon stops part-way, so a short
 * file is never handed over as if it were complete.
 */
export async function downloadPackets(manifest: PacketManifest): Promise<Blob> {
	const res = await fetch('/api/packets/download', post({ manifest }));
	if (!res.ok) throw await failure(res);
	return res.blob();
}

/** Link to download one saved capture file. */
export function captureFileUrl(id: string): string {
	return `/api/packets/capture-file?${new URLSearchParams({ id })}`;
}
