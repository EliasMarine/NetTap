/**
 * View helpers shared by /alerts and /alerts/[category]: severity level, the plain title,
 * and the "By category" grouping of the alerts a page has loaded (AlertRow README).
 */
import type { Alert } from '$api/alerts';
import type { SeverityLevel } from '$lib/utils/severity';
import { severityRank } from '$lib/utils/table-sort.svelte';

/** Suricata's 1–3 as the system's levels; anything else is info. */
export function alertLevel(severity: number | undefined): SeverityLevel {
	return severity === 1 ? 'high' : severity === 2 ? 'medium' : severity === 3 ? 'low' : 'info';
}

const text = (value: unknown): string | undefined =>
	typeof value === 'string' && value.trim() ? value : undefined;

/** The enrichment description; without one, the category label (PLAN.md §4.1). */
export function alertTitle(alert: Alert): string {
	return text(alert.plain_description) ?? text(alert.alert?.category) ?? 'Uncategorised alert';
}

/** The enrichment's risk context, shown as the drawer's explanation. */
export function alertExplanation(alert: Alert): string | undefined {
	return text(alert.risk_context);
}

/** The enrichment's advice; the What to do box never invents one. */
export function alertAdvice(alert: Alert): string {
	return text(alert.recommendation) ?? 'No specific advice for this alert yet.';
}

/** Log Explorer query for both ends of the alert (the old drawer's "View in Log Explorer"). */
export function logExplorerHref(alert: Alert): string {
	const ips = [alert.src_ip, alert.dest_ip].filter(Boolean);
	const query = ips.map((ip) => `(source.ip:"${ip}" OR destination.ip:"${ip}")`).join(' OR ');
	return `/logs?query=${encodeURIComponent(query)}`;
}

/** One signature from one source within the loaded alerts. */
export interface AlertLine {
	key: string;
	/** The newest event of the line: what the drawer opens. */
	alert: Alert;
	level: SeverityLevel;
	count: number;
	lastSeen: string;
}

export interface AlertCategoryGroup {
	title: string;
	count: number;
	lines: AlertLine[];
}

const time = (ts: string) => {
	const ms = Date.parse(ts);
	return Number.isFinite(ms) ? ms : -Infinity;
};

const rank = (line: AlertLine) => severityRank(line.alert.alert?.severity);
const byWorst = (a: AlertLine, b: AlertLine) => rank(b) - rank(a) || b.count - a.count || a.key.localeCompare(b.key);

/**
 * Group alerts by Suricata category, one line per signature and source. Lines sort by
 * severity, then count; groups by their worst line, then their count.
 * Counts are of the alerts given (one page), never extrapolated.
 */
export function groupAlerts(alerts: readonly Alert[]): AlertCategoryGroup[] {
	const groups = new Map<string, Map<string, AlertLine>>();
	for (const alert of alerts) {
		const title = text(alert.alert?.category) ?? 'Uncategorised';
		const key = [title, alert.alert?.signature_id ?? alert.alert?.signature ?? '', alert.src_ip ?? ''].join('\u0000');
		const lines = groups.get(title) ?? new Map<string, AlertLine>();
		groups.set(title, lines);
		const line = lines.get(key);
		if (!line) {
			lines.set(key, { key, alert, level: alertLevel(alert.alert?.severity), count: 1, lastSeen: alert.timestamp });
			continue;
		}
		const newer = time(alert.timestamp) > time(line.lastSeen);
		lines.set(key, {
			...line,
			count: line.count + 1,
			alert: newer ? alert : line.alert,
			lastSeen: newer ? alert.timestamp : line.lastSeen,
		});
	}
	return [...groups]
		.map(([title, lines]) => {
			const sorted = [...lines.values()].sort(byWorst);
			return { title, count: sorted.reduce((n, l) => n + l.count, 0), lines: sorted };
		})
		.sort((a, b) => rank(b.lines[0]) - rank(a.lines[0]) || b.count - a.count || a.title.localeCompare(b.title));
}

/** "21:05" today, "3 Nov" before today (AlertRow's narrow last-seen column). */
export function shortSeen(ts: string, now: Date = new Date()): string {
	const d = new Date(ts);
	if (!Number.isFinite(d.getTime())) return ts;
	return d.toDateString() === now.toDateString()
		? d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
		: d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}
