/**
 * A Security posture category page's content, worked out from one load (pure, so every rule is
 * unit-tested without rendering). Availability is per data source: one source that saw nothing or
 * failed never hides another's findings. The rules themselves are in report-traffic.ts (Encryption,
 * DNS security, Patch currency) and report-network.ts (segmentation, alerts, monitoring).
 */
import type { BarItem } from '$lib/components/ui/BarList.svelte';
import type { IconName } from '$lib/components/ui/icons';
import type { SeverityLevel } from '$lib/utils/severity';
import type { AlertTopSignaturesResponse } from '$api/alerts';
import type { CaptureMode, CaptureStatsResponse } from '$api/capture';
import type { NetworkIsolation } from '$api/iot';
import type { DeviceList, DnsDetail, EncryptionDetail, PatchDetail } from '$api/posture';
import { nothingFound } from '$api/system';
import { loadFailed } from '$lib/utils/load-failed';
import { fmt } from '$lib/utils/drilldown';
import type { CategoryScore, PostureInputs, PostureSlug } from './score';
import { encryptionReport, dnsReport, patchReport } from './report-traffic';
import { segmentationReport, alertReport, monitoringReport } from './report-network';

/** The per-category requests beside the five score inputs. */
export interface PostureExtras {
	encryption?: EncryptionDetail;
	'dns-security'?: DnsDetail;
	'patch-currency'?: PatchDetail;
	isolation?: NetworkIsolation;
	signatures?: AlertTopSignaturesResponse;
	mode?: CaptureMode;
	stats?: CaptureStatsResponse;
}
export type ExtraKey = keyof PostureExtras;

/** Which extra requests each category makes. */
export const EXTRAS: Record<PostureSlug, readonly ExtraKey[]> = {
	encryption: ['encryption'],
	'dns-security': ['dns-security'],
	'network-segmentation': ['isolation'],
	'patch-currency': ['patch-currency'],
	'alert-response': ['signatures'],
	'monitoring-coverage': ['mode', 'stats'],
};

export interface ReportData {
	/** The window every windowed request used; links carry it */
	window: { from: string; to: string };
	inputs: PostureInputs;
	category: CategoryScore;
	extras: PostureExtras;
	/** Extra requests that failed */
	failed: readonly ExtraKey[];
	names: ReadonlyMap<string, string>;
}

export interface Kpi {
	key: string;
	label: string;
	icon: IconName;
	value: string;
	unit?: string;
	sub?: string;
}

export interface FindingDevice {
	ip: string;
	name?: string;
}

export interface Finding {
	key: string;
	severity: SeverityLevel;
	title: string;
	detail: string;
	devices: FindingDevice[];
	count?: number;
	fix: string;
	href?: string;
}

export type Priority = 'high' | 'medium' | 'low';

export interface Step {
	priority: Priority;
	text: string;
	href?: string;
}

export type SourceState = 'measured' | 'not-measured' | 'unattributed' | 'failed';

export interface Source {
	key: string;
	label: string;
	state: SourceState;
	note?: string;
}

/** A line under a list that shows only part of what was counted. */
export interface Note {
	text: string;
	href?: string;
}

/** One row of the DNS resolvers table. */
export interface ResolverRow {
	key: string;
	ip: string;
	kind: 'Plain' | 'DNS-over-TLS';
	org: string;
	scope: string;
	count: number;
}

export interface Drivers {
	/** The score's sum with this load's numbers */
	formula: string;
	/** What is counted and left out, and the other figures checked beside the score */
	counts: string[];
	/** What the score can't see, said plainly */
	limits: string[];
	bars: BarItem[];
	resolvers?: ResolverRow[];
}

export interface Report {
	kpis: Kpi[];
	drivers: Drivers;
	sources: Source[];
	findings: Finding[];
	steps: Step[];
	notes: Note[];
}

// --- Shared helpers ---

export const UNATTRIBUTED =
	"NetTap saw this traffic but couldn't tie it to devices on your network; in inline bridge mode your router hides them.";

/** "12%": a share of a whole, 0 when the whole is 0. */
export const pct = (part: number, whole: number): number => (whole > 0 ? Math.round((part / whole) * 100) : 0);

export const device = (ip: string, names: ReadonlyMap<string, string>): FindingDevice => {
	const name = names.get(ip);
	return name ? { ip, name } : { ip };
};

/** A device by name, else by address, for a sentence. */
export const deviceWords = (ip: string, names: ReadonlyMap<string, string>): string => names.get(ip) ?? ip;

export const failedSource = (key: string, label: string): Source => ({ key, label, state: 'failed', note: loadFailed(label.toLowerCase()) });

/** A source that saw nothing, with the pipeline's state now beside it. */
export function notMeasured(key: string, label: string, nothing: string, inputs: PostureInputs): Source {
	const zero = nothingFound(nothing, inputs.health.health, inputs.health.failed, nothing);
	return { key, label, state: 'not-measured', note: `${nothing} · ${zero.detail}` };
}

/** A capped device list's source: nothing seen, seen but tied to no device, or measured. */
export function listSource(
	key: string,
	label: string,
	o: { seen: boolean; total: number; list: DeviceList<unknown>; nothing: string },
	inputs: PostureInputs,
): Source {
	if (!o.seen) return notMeasured(key, label, o.nothing, inputs);
	if (o.total > 0 && o.list.lan === 0) return { key, label, state: 'unattributed', note: UNATTRIBUTED };
	return { key, label, state: 'measured' };
}

/** The line under a list that holds only the busiest devices. */
export function truncationNote(list: DeviceList<unknown>, href?: string): Note | null {
	if (list.other <= 0) return null;
	const text = `Showing the ${list.rows.length} busiest devices. Other devices on your network made ${fmt(list.other)} more of these connections.`;
	return href ? { text, href } : { text };
}

/** A KPI read from a score input whose request failed: no stand-in zero. */
export const unloaded = (kpi: Kpi, failed: boolean): Kpi => (failed ? { ...kpi, value: '—', unit: undefined, sub: "Couldn't load" } : kpi);

/** The Score KPI every category starts with: the overview's figure and status word. */
export function scoreKpi(category: CategoryScore): Kpi {
	const value = category.score === null ? '—' : category.empty ? 'Not measured' : String(category.score);
	return { key: 'score', label: 'Score', icon: 'check', value, unit: value === String(category.score) ? '%' : undefined, sub: category.status };
}

export const SEVERITY_RANK: Record<SeverityLevel, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };

/** The category's report: most severe findings and highest-priority steps first. */
export function buildReport(slug: PostureSlug, data: ReportData): Report {
	const build = {
		encryption: encryptionReport,
		'dns-security': dnsReport,
		'patch-currency': patchReport,
		'network-segmentation': segmentationReport,
		'alert-response': alertReport,
		'monitoring-coverage': monitoringReport,
	}[slug];
	const report = build(data);
	return {
		...report,
		// an empty category's score is a stand-in 100, so there is no sum to show
		drivers: data.category.empty ? { ...report.drivers, formula: 'Nothing to score in the last 24 hours.' } : report.drivers,
		findings: [...report.findings].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || (b.count ?? 0) - (a.count ?? 0)),
		steps: [...report.steps].sort((a, b) => SEVERITY_RANK[a.priority] - SEVERITY_RANK[b.priority]),
	};
}
