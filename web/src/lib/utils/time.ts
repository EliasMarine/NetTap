/**
 * One way to write a time across the app (NET-192 PR 4): en-GB and 24-hour whatever the browser's
 * locale, so a US browser never shows "07:00 PM" or "11/6/2026". Chart axes use `chartTime`
 * (utils/drilldown.ts), which picks its detail from the window's length.
 */
const STYLES = {
	/** "6 Nov, 22:37" */
	short: { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' },
	/** "6 Nov 2026, 22:37:23" */
	long: { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' },
	/** "22:37:23" */
	clock: { hour: '2-digit', minute: '2-digit', second: '2-digit' },
	/** "6 Nov 2026" */
	date: { day: 'numeric', month: 'short', year: 'numeric' },
} satisfies Record<string, Intl.DateTimeFormatOptions>;

export type TimeStyle = keyof typeof STYLES;

/** A time as the app writes it: "—" when there is none, the input as given when it isn't a date. */
export function formatTime(ts: string | number | Date | null | undefined, style: TimeStyle = 'long'): string {
	if (ts == null || ts === '') return '—';
	const d = new Date(ts);
	return Number.isFinite(d.getTime()) ? d.toLocaleString('en-GB', STYLES[style]) : String(ts);
}
