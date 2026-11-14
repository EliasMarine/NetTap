/**
 * Changelog v2 (NET-272): each event joined, in the browser, to the device list over the loaded
 * window (`GET /api/devices`, the Devices page's own accounting), plus the coverage the page must
 * state, the KPIs, the chart's buckets, the pick and the export.
 *
 * Figures are counted per address: the daemon groups records by IP and attaches a MAC, so a device
 * sums every list row carrying its MAC, and matches by IP only when the event has no MAC.
 */
import type { ChangelogEvent } from '$lib/api/changelog';
import type { Device, DeviceListResponse } from '$lib/api/devices';
import type { IconName } from '$lib/components/ui/icons';
import { bucketWindow, customRange, type DrillWindow } from '$lib/utils/drilldown';
import { ipv6ListNotes } from '$lib/utils/ipv6-coverage';
import { formatDuration } from '$lib/utils/tshark-helpers';

/** The daemon's cap on one changelog request (services/changelog.py), newest first. */
export const EVENT_LIMIT = 1000;
/** The daemon's cap on one device list (api/devices.py _MAX_DEVICE_LIMIT), busiest first. */
export const DEVICE_LIMIT = 500;

// Moved from +page.svelte (NET-272), with their history
// OLD CODE START — never rendered; each type now has a system icon
// const eventIcons: Record<string, string> = {
// 	device_joined: 'device-join',
// 	device_left: 'device-leave',
// 	alert_triggered: 'alert',
// 	config_changed: 'config',
// 	rule_updated: 'rule',
// 	capture_started: 'capture-start',
// 	capture_stopped: 'capture-stop',
// 	storage_pruned: 'storage',
// };
// OLD CODE END
export const eventIcons: Record<string, IconName> = {
	device_joined: 'devices',
	device_left: 'devices',
	alert_triggered: 'alerts',
	config_changed: 'settings',
	rule_updated: 'filter',
	capture_started: 'play',
	capture_stopped: 'pause',
	storage_pruned: 'system',
	device_cap_reached: 'devices',
};

// OLD CODE START — sentence case (design system voice)
// const eventLabels: Record<string, string> = {
// 	device_joined: 'Device Joined',
// 	device_left: 'Device Left',
// 	alert_triggered: 'Alert Triggered',
// 	config_changed: 'Config Changed',
// 	rule_updated: 'Rule Updated',
// 	capture_started: 'Capture Started',
// 	capture_stopped: 'Capture Stopped',
// 	storage_pruned: 'Storage Pruned',
// };
// OLD CODE END
export const eventLabels: Record<string, string> = {
	device_joined: 'Device joined',
	device_left: 'Device left',
	alert_triggered: 'Alert triggered',
	config_changed: 'Config changed',
	rule_updated: 'Rule updated',
	capture_started: 'Capture started',
	capture_stopped: 'Capture stopped',
	storage_pruned: 'Storage pruned',
	device_cap_reached: 'Device limit reached',
};

/** Why a row's traffic cells are empty. */
export type Missing = 'system' | 'devices-failed' | 'no-figures';

export const MISSING_TEXT: Record<Missing, string> = {
	system: 'Not a device event, so there are no traffic figures.',
	'devices-failed': 'Traffic figures unavailable: the device list failed.',
	'no-figures': 'No address-level traffic figures matched this device in this range.',
};

export const PER_ADDRESS_NOTE =
	'Counted per address. If another device used one of these addresses in this range, its traffic is included.';

export interface ChangelogRow {
	/** The event's id (its position when it has none): the table's row key. */
	id: string;
	/** The event as the daemon sent it, for the export and the system rows' detail. */
	event: ChangelogEvent;
	/** The event's time, ms. */
	t: number;
	kind: 'device' | 'system';
	name: string | null;
	mac: string | null;
	vendor: string | null;
	/** Where the device joined (the event's own address), never a traffic address. */
	eventIp: string | null;
	/** The matched list rows' addresses, busiest first: the figures and destinations come from these. */
	trafficIps: string[];
	firstSeen: string | null;
	/** Last seen in the loaded range. */
	lastSeen: string | null;
	/** From the first to the last record in the range, gaps included; not a connection time. */
	spanMs: number | null;
	sent: number | null;
	received: number | null;
	total: number | null;
	connections: number | null;
	alerts: number | null;
	ipv6Notes: string[];
	missing: Missing | null;
}

export interface Coverage {
	/** The daemon returned its cap of events, so the oldest part of the range is missing. */
	eventsTruncated: boolean;
	/** The device list held fewer rows than it counted (`total`): only the busiest have figures. */
	devicesTruncated: boolean;
	devicesFailed: boolean;
	/** IPv6 coverage notes of every matched address row. */
	ipv6Notes: string[];
}

export const normaliseMac = (mac: string): string => mac.trim().toLowerCase().replace(/-/g, ':');

const text = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null);

/** A field's sum over the rows, or null when any row lacks it (an older daemon): never a made-up 0. */
function sumOf(rows: readonly Device[], pick: (d: Device) => number | undefined): number | null {
	const values = rows.map(pick);
	return values.every((v) => typeof v === 'number' && Number.isFinite(v)) ? (values as number[]).reduce((a, b) => a + b, 0) : null;
}

function edge(times: readonly string[], latest: boolean): string | null {
	const ms = times.map(Date.parse).filter(Number.isFinite);
	return ms.length ? new Date(latest ? Math.max(...ms) : Math.min(...ms)).toISOString() : null;
}

// A new object (and arrays) per row: rows never share mutable state
const noFigures = () => ({
	lastSeen: null, spanMs: null, sent: null, received: null, total: null, connections: null, alerts: null,
	trafficIps: [] as string[], ipv6Notes: [] as string[],
});

function joinEvent(event: ChangelogEvent, devices: readonly Device[] | null, byMac: ReadonlyMap<string, Device[]>, index: number): ChangelogRow {
	const rawMac = text(event.metadata?.mac);
	const mac = rawMac ? normaliseMac(rawMac) : null;
	const eventIp = text(event.metadata?.ip);
	const joinedAt = event.event_type === 'device_joined' ? event['@timestamp'] : null;
	const base = { id: event._id || `event-${index}`, event, t: Date.parse(event['@timestamp']), mac, eventIp };
	if (!mac && !eventIp) {
		return { ...base, ...noFigures(), kind: 'system', name: null, vendor: null, firstSeen: null, missing: 'system' };
	}
	const matched = devices === null ? [] : mac ? (byMac.get(mac) ?? []) : devices.filter((d) => d.ip === eventIp);
	if (matched.length === 0) {
		const missing: Missing = devices === null ? 'devices-failed' : 'no-figures';
		return { ...base, ...noFigures(), kind: 'device', name: mac ?? eventIp, vendor: null, firstSeen: joinedAt, missing };
	}
	const busiest = [...matched].sort((a, b) => b.total_bytes - a.total_bytes);
	const firstSeen = joinedAt ?? edge(matched.map((d) => d.first_seen), false);
	const lastSeen = edge(matched.map((d) => d.last_seen), true);
	const span = firstSeen && lastSeen ? Date.parse(lastSeen) - Date.parse(firstSeen) : NaN;
	return {
		...base,
		kind: 'device',
		name: busiest.find((d) => d.hostname)?.hostname ?? mac ?? eventIp,
		vendor: busiest.find((d) => d.manufacturer)?.manufacturer ?? null,
		trafficIps: busiest.map((d) => d.ip),
		firstSeen,
		lastSeen,
		spanMs: span >= 0 ? span : null,
		sent: sumOf(matched, (d) => d.upload_bytes),
		received: sumOf(matched, (d) => d.download_bytes),
		total: sumOf(matched, (d) => d.total_bytes),
		connections: sumOf(matched, (d) => d.connection_count),
		alerts: sumOf(matched, (d) => d.alert_count),
		ipv6Notes: ipv6ListNotes(matched),
		missing: null,
	};
}

/** One row per event (the daemon's order), joined to the device list; null `list` = the list failed. */
export function joinChangelog(events: readonly ChangelogEvent[], list: DeviceListResponse | null): { rows: ChangelogRow[]; coverage: Coverage } {
	const devices = list?.devices ?? null;
	// The list rows per normalised MAC, built once (not once per event)
	const byMac = new Map<string, Device[]>();
	for (const d of devices ?? []) {
		if (!d.mac) continue;
		const key = normaliseMac(d.mac);
		byMac.set(key, [...(byMac.get(key) ?? []), d]);
	}
	const rows = events.map((e, i) => joinEvent(e, devices, byMac, i));
	return {
		rows,
		coverage: {
			eventsTruncated: events.length >= EVENT_LIMIT,
			devicesTruncated: !!list && list.total > list.devices.length,
			devicesFailed: list === null,
			ipv6Notes: [...new Set(rows.flatMap((r) => r.ipv6Notes))],
		},
	};
}

export interface ChangelogKpis {
	events: number;
	newDevices: number;
	/** New devices with traffic figures: the two traffic KPIs cover these only. */
	matched: number;
	moved: number | null;
	busiest: ChangelogRow | null;
}

export function changelogKpis(rows: readonly ChangelogRow[]): ChangelogKpis {
	const joined = rows.filter((r) => r.event.event_type === 'device_joined');
	// one device, one entry, even if it was recorded twice
	const devices = [...new Map(joined.map((r) => [r.mac ?? r.eventIp ?? r.id, r])).values()];
	const matched = devices.filter((r): r is ChangelogRow & { total: number } => r.total !== null);
	const busiest = matched.reduce<(typeof matched)[number] | null>((top, r) => (!top || r.total > top.total ? r : top), null);
	return {
		events: rows.length,
		newDevices: devices.length,
		matched: matched.length,
		moved: matched.length ? matched.reduce((sum, r) => sum + r.total, 0) : null,
		busiest,
	};
}

/**
 * Where the loaded events are complete from, ms. When the list stopped at its cap, the bucket that
 * holds the oldest returned event (events with its timestamp may be missing) and every earlier one
 * are unknown, so coverage starts at the next bucket. Buckets start on multiples of `stepMs`.
 */
export function knownFrom(rows: readonly ChangelogRow[], win: DrillWindow, stepMs: number, truncated: boolean): number {
	const times = rows.map((r) => r.t).filter(Number.isFinite);
	if (!truncated || times.length === 0) return Date.parse(win.from);
	return Math.floor(Math.min(...times) / stepMs) * stepMs + stepMs;
}

export interface EventBucket {
	/** The bucket's start, ISO (bucketWindow's `timestamp`). */
	timestamp: string;
	/** Events in [start, start + step); NaN where the events are unknown (drawn as a gap). */
	count: number;
}

/** Events per bucket over the loaded window, buckets on multiples of `stepMs`, unknown before `known`. */
export function eventBuckets(rows: readonly ChangelogRow[], win: DrillWindow, stepMs: number, known: number): EventBucket[] {
	const first = Math.floor(Date.parse(win.from) / stepMs) * stepMs;
	const n = Math.floor((Date.parse(win.to) - first) / stepMs) + 1;
	const counts = new Array<number>(n).fill(0);
	for (const r of rows) {
		const i = Math.floor((r.t - first) / stepMs);
		if (i >= 0 && i < n) counts[i] += 1;
	}
	return counts.map((count, i) => {
		const start = first + i * stepMs;
		// unknown only when the whole bucket ends before coverage starts: a first bucket the window cuts is known
		return { timestamp: new Date(start).toISOString(), count: start + stepMs <= known ? NaN : count };
	});
}

/** Chart points i..j as an inclusive window (bucketWindow, clipped to the loaded one); null when it touches unknown coverage. */
export function pickRange(buckets: readonly EventBucket[], i: number, j: number, stepMs: number, win: DrillWindow): DrillWindow | null {
	const lo = Math.min(i, j);
	const hi = Math.max(i, j);
	if (buckets.slice(lo, hi + 1).some((b) => !Number.isFinite(b.count))) return null;
	return bucketWindow(buckets, i, j, stepMs, win);
}

/** A pick read from the URL, or null when either end isn't a date or `from` is after `to`. */
export function readPick(from: string | null, to: string | null): DrillWindow | null {
	const w = customRange(from, to);
	return w ? { from: w.from, to: w.to } : null;
}

/** The pick a new load keeps: only one inside the loaded window and its known coverage. */
export function keepPick(pick: DrillWindow | null, win: DrillWindow, known: number): DrillWindow | null {
	if (!pick) return null;
	const from = Date.parse(pick.from);
	return from >= Date.parse(win.from) && from >= known && Date.parse(pick.to) <= Date.parse(win.to) ? pick : null;
}

/** The rows inside the pick, inclusive at both ends (the daemon's `gte from, lte to`). */
export function inPick(rows: readonly ChangelogRow[], pick: DrillWindow | null): readonly ChangelogRow[] {
	if (!pick) return rows;
	const from = Date.parse(pick.from);
	const to = Date.parse(pick.to);
	return rows.filter((r) => r.t >= from && r.t <= to);
}

/** "6d 0h" from a day up, formatDuration's "3h 12m" / "12m 5s" / "4.0s" below. */
export function spanText(ms: number | null): string {
	if (ms === null) return '—';
	// formatDuration(0) reads "0µs"; records a moment apart read better as under a second
	if (ms < 1000) return '< 1s';
	const days = Math.floor(ms / 86_400_000);
	return days >= 1 ? `${days}d ${Math.floor((ms % 86_400_000) / 3_600_000)}h` : formatDuration(ms / 1000);
}

const FORMULA_START = /^[=+\-@\t\r]/;

/**
 * One CSV cell. Text that a spreadsheet would read as a formula (names come from discovery or the
 * owner) gets a leading `'`; then it is quoted with quotes doubled. Numbers stay numeric.
 */
export function csvCell(v: unknown): string {
	if (v === null || v === undefined) return '';
	if (typeof v === 'number') return Number.isFinite(v) ? String(v) : '';
	const s = String(v);
	return `"${(FORMULA_START.test(s) ? `'${s}` : s).replace(/"/g, '""')}"`;
}

const CSV_COLUMNS: readonly [string, (r: ChangelogRow) => unknown][] = [
	['Timestamp', (r) => r.event['@timestamp']],
	['Event type', (r) => r.event.event_type],
	['Title', (r) => r.event.title],
	['Description', (r) => r.event.description],
	['Device name', (r) => r.name],
	['MAC', (r) => r.mac],
	['Vendor', (r) => r.vendor],
	['Joined at', (r) => r.eventIp],
	['Counted from', (r) => r.trafficIps.join(' ')],
	['First seen', (r) => r.firstSeen],
	['Last seen in range', (r) => r.lastSeen],
	['Seen over (s)', (r) => (r.spanMs === null ? null : Math.round(r.spanMs / 1000))],
	['Sent (bytes)', (r) => r.sent],
	['Received (bytes)', (r) => r.received],
	['Total (bytes)', (r) => r.total],
	['Connections', (r) => r.connections],
	['Alerts', (r) => r.alerts],
	['No figures because', (r) => (r.missing ? MISSING_TEXT[r.missing] : null)],
];

export function toCsv(rows: readonly ChangelogRow[]): string {
	const head = CSV_COLUMNS.map(([label]) => csvCell(label)).join(',');
	return [head, ...rows.map((r) => CSV_COLUMNS.map(([, value]) => csvCell(value(r))).join(','))].join('\n');
}

/** The JSON export: each event as the daemon sent it, plus what the page joined to it (`joined`). */
export function toJson(rows: readonly ChangelogRow[]): string {
	// id and t are the page's keys, not data
	return JSON.stringify(rows.map(({ event, id, t, ...joined }) => ({ ...event, joined })), null, 2);
}
