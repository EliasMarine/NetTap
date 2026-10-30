// ---------------------------------------------------------------------------
// Shared TShark packet display helpers
//
// Pure utility functions for unwrapping TShark JSON values and extracting
// human-readable packet summaries. Used by both ConnectionDrawer.svelte
// and ConnectionDrawerContent.svelte to eliminate duplicated logic.
// ---------------------------------------------------------------------------

import type { TSharkPacket } from '$api/tshark';

// ---------------------------------------------------------------------------
// unwrap — Extract scalar from TShark's array-wrapped JSON values
// ---------------------------------------------------------------------------

/**
 * Unwrap TShark -T json array-wrapped values (e.g. ["1"] -> "1").
 * TShark JSON output wraps every field value in an array, even scalars.
 * This safely extracts the first element as a string.
 */
export function unwrap(val: unknown): string {
	if (Array.isArray(val)) return String(val[0] ?? '');
	if (val == null) return '';
	return String(val);
}

// ---------------------------------------------------------------------------
// Packet summary extraction
// ---------------------------------------------------------------------------

export interface PacketSummary {
	no: string;
	time: string;
	src: string;
	dst: string;
	proto: string;
	len: string;
	info: string;
}

/**
 * Extract a human-readable summary from a TShark JSON packet object.
 * Handles the nested `_source.layers` structure that TShark -T json produces.
 *
 * Returns a flat object with no, time, src, dst, proto, len, info fields.
 * The `info` field may be empty if the `_ws.col.Info` column is not present.
 */
export function getPacketSummary(pkt: TSharkPacket): PacketSummary {
	const layers = pkt?.['_source']?.['layers'] || pkt;
	const frame = layers?.['frame'] || {};
	const ip = layers?.['ip'] || layers?.['ipv6'] || {};
	const protocols = unwrap(frame['frame.protocols']);
	return {
		no: unwrap(frame['frame.number']) || '?',
		time: unwrap(frame['frame.time_relative']) || unwrap(frame['frame.time']) || '?',
		src: unwrap(ip['ip.src']) || unwrap(ip['ipv6.src']) || '?',
		dst: unwrap(ip['ip.dst']) || unwrap(ip['ipv6.dst']) || '?',
		proto: protocols.split(':').pop() || '?',
		len: unwrap(frame['frame.len']) || '?',
		info: unwrap(pkt?.['_source']?.['layers']?.['_ws.col']?.['_ws.col.Info']) || '',
	};
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

/**
 * Format a duration value (in seconds) to a human-readable string.
 * Handles microseconds, milliseconds, seconds, minutes, and hours.
 */
export function formatDuration(val: unknown): string {
	if (val == null) return '--';
	const n = Number(val);
	if (isNaN(n)) return String(val);
	if (n < 0.001) return `${(n * 1_000_000).toFixed(0)}\u00b5s`;
	if (n < 1) return `${(n * 1000).toFixed(0)}ms`;
	if (n < 60) return `${n.toFixed(1)}s`;
	if (n < 3600) return `${Math.floor(n / 60)}m ${(n % 60).toFixed(0)}s`;
	return `${Math.floor(n / 3600)}h ${Math.floor((n % 3600) / 60)}m`;
}

/**
 * Format a byte count to a human-readable string with appropriate unit.
 */
export function formatBytes(val: unknown): string {
	if (val == null) return '--';
	const n = Number(val);
	if (isNaN(n)) return String(val);
	if (n >= 1_073_741_824) return `${(n / 1_073_741_824).toFixed(1)} GB`;
	if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`;
	if (n >= 1_024) return `${(n / 1_024).toFixed(1)} KB`;
	return `${n} B`;
}

// ---------------------------------------------------------------------------
// Zeek connection state descriptions
// ---------------------------------------------------------------------------

/**
 * Map of Zeek connection state codes to human-readable descriptions.
 * Used by both drawer components to display conn_state meaning.
 */
export const CONN_STATE_DESC: Record<string, string> = {
	S0: 'Connection attempt seen, no reply',
	S1: 'Connection established, not terminated',
	SF: 'Normal establishment and termination',
	REJ: 'Connection attempt rejected',
	S2: 'Connection established, close attempted by originator',
	S3: 'Connection established, close attempted by responder',
	RSTO: 'Connection established, originator aborted',
	RSTR: 'Connection established, responder aborted',
	RSTOS0: 'Originator sent a SYN then RST, responder never replied',
	RSTRH: 'Responder sent a SYN ACK then RST, originator never replied',
	SH: 'Originator sent SYN then FIN, responder never replied (half-open)',
	SHR: 'Responder sent SYN ACK then FIN, originator never replied',
	OTH: 'No SYN seen, midstream traffic',
};
