import { getField } from '$lib/utils/tshark-filter';

/** Epoch ms from Malcolm's epoch-ms text ("1793613468348"), a number, or an ISO date; NaN when none. */
export function epochMs(value: unknown): number {
	if (typeof value === 'number') return value;
	const text = String(value ?? '');
	return /^\d+$/.test(text) ? Number(text) : Date.parse(text);
}

/**
 * A connection record's duration in ms, or null when the record can't say (#144).
 *
 * `length` (end minus start, in ms) is on every record and is what the daemon sorts by. Malcolm
 * 26.x writes event.start/end as epoch-ms text, which `new Date()` reads as Invalid Date, so the
 * pages that subtracted them showed "--" on every row.
 */
export function connectionDurationMs(conn: Record<string, unknown>): number | null {
	const length = getField(conn, 'length');
	if (typeof length === 'number' && length >= 0) return length;
	const ms = epochMs(getField(conn, 'event.end')) - epochMs(getField(conn, 'event.start'));
	if (Number.isFinite(ms) && ms >= 0) return ms;
	const zeekSeconds = getField(conn, 'zeek.conn.duration');
	return typeof zeekSeconds === 'number' ? zeekSeconds * 1000 : null;
}
