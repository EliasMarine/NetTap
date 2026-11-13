/**
 * Device traffic compare (NET-265): the two periods the card asks for, and its plain-English lines.
 * The words say what the capture saw in each period, never why it changed.
 */
import type { CompareQuery, DeviceCompareResponse } from '$api/device-compare';

const HOUR = 3_600_000;
export const COMPARE_LENGTHS = [
	{ value: '1h', label: '1 hour', ms: HOUR },
	{ value: '24h', label: '24 hours', ms: 24 * HOUR },
	{ value: '7d', label: '7 days', ms: 7 * 24 * HOUR },
] as const;
export type CompareLength = (typeof COMPARE_LENGTHS)[number]['value'];

export const COMPARE_SCOPE =
	"Compares connections this device started in each period. Bytes are each connection's lifetime total. A connection still open is counted once it closes, so the last few minutes can still grow.";
export const TOO_MANY_LISTED =
	'This device talked to more than 10,000 destinations in a period, so new and no-longer-seen destinations cannot be worked out.';
export const NOT_EXACT = 'Too many destinations to compare exactly in these periods. Try a shorter window.';

export const lengthMs = (length: CompareLength): number => COMPARE_LENGTHS.find((l) => l.value === length)?.ms ?? 24 * HOUR;

/** epoch ms as datetime-local text: the browser's local time, to the minute. */
export function localInput(ms: number): string {
	const d = new Date(ms);
	const p = (n: number) => String(n).padStart(2, '0');
	return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** The first period ends one length before this minute and the second starts where it ends, so it ends now. */
export function defaultStarts(length: number, nowMs: number): { a: string; b: string } {
	const minute = Math.floor(nowMs / 60_000) * 60_000;
	return { a: localInput(minute - 2 * length), b: localInput(minute - length) };
}

/** The query's bounds for two datetime-local starts, each period `length` long; null if a start is unreadable. */
export function periods(ip: string, aStart: string, bStart: string, length: number): CompareQuery | null {
	const a = new Date(aStart).getTime();
	const b = new Date(bStart).getTime();
	if (!aStart || !bStart || Number.isNaN(a) || Number.isNaN(b)) return null;
	const iso = (ms: number) => new Date(ms).toISOString();
	return { ip, a_from: iso(a), a_to: iso(a + length), b_from: iso(b), b_to: iso(b + length) };
}

const count = (n: number, one: string, many: string) => `${n.toLocaleString('en-GB')} ${n === 1 ? one : many}`;

/** "In the second period this device started connections to 4 new destinations and none to 2 earlier ones. Bytes went from 1.2 GB to 3.4 GB." */
export function compareSummary(r: DeviceCompareResponse, formatBytes: (bytes: number) => string): string {
	const bytes = `Bytes went from ${formatBytes(r.a.total_bytes)} to ${formatBytes(r.b.total_bytes)}.`;
	if (!r.exact) return `${NOT_EXACT} ${bytes}`;
	if (!r.complete || !r.new || !r.gone) return `${TOO_MANY_LISTED} ${bytes}`;
	const fresh = r.new.total === 0 ? 'no new destinations' : count(r.new.total, 'new destination', 'new destinations');
	const gone = r.gone.total === 0 ? '' : ` and none to ${count(r.gone.total, 'earlier one', 'earlier ones')}`;
	return `In the second period this device started connections to ${fresh}${gone}. ${bytes}`;
}
