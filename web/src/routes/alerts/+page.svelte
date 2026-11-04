<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import {
		getAlerts,
		// OLD CODE START — the severity counts come from the shared alert snapshot (PLAN.md §4.1)
		// getAlertCount,
		// OLD CODE END
		getAlertTimeline,
		getAlertTopSignatures,
		getAlertTopIps,
		getEnhancedCategories,
		getSmartAlertSummary,
		formatNumber,
		// OLD CODE START — severity shows as SeverityPill now
		// severityLabel,
		// severityBadgeClass,
		// OLD CODE END
		suppressAlert,
		markFalsePositive,
	} from '$api/alerts';
	import type {
		Alert,
		AlertsListResponse,
		AlertTimelineBucket,
		AlertSignature,
		AlertIpEntry,
		AlertCategory,
		SmartAlertSummary,
		AlertSort,
	} from '$api/alerts';
	// OLD CODE START — AlertDetailPanel replaced by DetailDrawer
	// import AlertDetailPanel from '$components/AlertDetailPanel.svelte';
	// OLD CODE END
	import IPAddress from '$components/IPAddress.svelte';
	// OLD CODE START — 2026-11-03 redesign: the system's BarList and the docked drawer column
	// import HorizontalBarList from '$components/HorizontalBarList.svelte';
	// import DetailDrawer from '$components/DetailDrawer.svelte';
	// import AlertDrawerContent from '$components/drawer/content/AlertDrawerContent.svelte';
	// OLD CODE END
	import { acknowledgeAlert } from '$api/alerts';
	// OLD CODE START — #146: the alert table sorts on the daemon now
	// import { compareValues, severityRank } from '$lib/utils/table-sort.svelte';
	// OLD CODE END
	import { severityRank } from '$lib/utils/table-sort.svelte';
	import { severityBuckets, type SeverityLevel } from '$lib/utils/severity';
	import { alertSnapshots, loadAlertSnapshot, refreshAlertSnapshots } from '$lib/stores/alertSnapshot';
	import { createLoadGuard, registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import SearchField from '$lib/components/ui/SearchField.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import BarList from '$lib/components/ui/BarList.svelte';
	import AlertRow from '$lib/components/ui/AlertRow.svelte';
	import AlertGroup from '$lib/components/ui/AlertGroup.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { loadFailed } from '$lib/utils/load-failed';
	import AreaChart from '$lib/components/ui/charts/AreaChart.svelte';
	import SeverityGauge from '$lib/components/ui/charts/SeverityGauge.svelte';
	import Ring from '$lib/components/ui/charts/Ring.svelte';
	import AlertDetail from './AlertDetail.svelte';
	import { alertLevel, alertTitle, groupAlerts, shortSeen } from './alert-view';

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	const TIME_RANGES = [
		{ label: '15m', value: '15m', ms: 15 * 60 * 1000, words: 'last 15 minutes' },
		{ label: '1h', value: '1h', ms: 60 * 60 * 1000, words: 'last hour' },
		{ label: '4h', value: '4h', ms: 4 * 60 * 60 * 1000, words: 'last 4 hours' },
		{ label: '24h', value: '24h', ms: 24 * 60 * 60 * 1000, words: 'last 24 hours' },
		{ label: '7d', value: '7d', ms: 7 * 24 * 60 * 60 * 1000, words: 'last 7 days' },
	];

	const INTERVAL_MAP: Record<string, string> = {
		'15m': '1m',
		'1h': '5m',
		'4h': '15m',
		'24h': '1h',
		'7d': '6h',
	};

	type SeverityFilter = 'all' | 'high' | 'medium' | 'low' | 'info';

	const SEVERITY_FILTERS: { value: SeverityFilter; label: string }[] = [
		{ value: 'all', label: 'All' },
		{ value: 'high', label: 'High' },
		{ value: 'medium', label: 'Medium' },
		{ value: 'low', label: 'Low' },
		{ value: 'info', label: 'Info' },
	];

	const THREAT_LEVELS: SeverityLevel[] = ['critical', 'high', 'medium', 'low'];

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	// OLD CODE START — a filter clicked before the first load finished was ignored; the load guards order every request now
	// let initialized = $state(false);
	// let loading = $state(false);
	// OLD CODE END
	/** The first full load has finished (every card leaves its loading state). */
	let loaded = $state(false);
	/** The alert list has answered at least once. */
	let listLoaded = $state(false);
	let selectedTimeRange = $state('24h');
	let autoRefresh = $state(false);
	let refreshInterval = $state<ReturnType<typeof setInterval> | null>(null);

	// Server data
	// OLD CODE START — the counts come from the shared alert snapshot (PLAN.md §4.1)
	// let alertCounts = $state({ total: 0, high: 0, medium: 0, low: 0 });
	// OLD CODE END
	let timeline = $state<AlertTimelineBucket[]>([]);
	let topSignatures = $state<AlertSignature[]>([]);
	let topDestIps = $state<AlertIpEntry[]>([]);
	let topSrcIps = $state<AlertIpEntry[]>([]);
	let enhancedCategories = $state<AlertCategory[]>([]);
	let alerts = $state<Alert[]>([]);
	let threatScore = $state(0);
	let threatLevel = $state('none');
	let smartSummary = $state<SmartAlertSummary | null>(null);
	// #96: sections whose request failed; they say so instead of showing the last value or "none"
	let failed = $state<Record<string, boolean>>({});

	// Filters
	let activeFilter = $state<SeverityFilter>('all');
	let signatureSearch = $state('');
	let urlSignature = $page.url.searchParams.get('signature') || '';
	let urlCategory = $page.url.searchParams.get('category') || '';
	let signatureFilter = $state(urlSignature);
	let ipFilter = $derived($page.url.searchParams.get('ip') || '');

	// Pagination
	let currentPage = $state(1);
	let totalPages = $state(0);
	let totalAlerts = $state(0);
	const pageSize = 50;

	// OLD CODE START — replaced by DetailDrawer
	// let selectedAlert = $state<Alert | null>(null);
	// let expandedAlertId = $state<string | null>(null);
	// OLD CODE END

	// Detail drawer state
	let drawerAlert = $state<Alert | null>(null);
	// OLD CODE START — 2026-11-03: the drawer's tabs became its collapsible sections, and the timeline is the AreaChart
	// let drawerTab = $state('summary');
	// const ALERT_DRAWER_TABS = [
	// 	{ id: 'summary', label: 'Summary' },
	// 	{ id: 'related', label: 'Related Events' },
	// 	{ id: 'raw', label: 'Raw JSON' },
	// ];
	// let hoveredBarIndex = $state<number | null>(null);
	// let chartWidth = $state(800);
	// OLD CODE END
	let actionError = $state('');
	/** The list shows grouped AlertRows or the full table; both read the same page of alerts. */
	let view = $state<'category' | 'all'>('category');

	// Sort
	// OLD CODE START — Protocol couldn't be sorted (design system: every column sorts)
	// type SortKey = 'timestamp' | 'severity' | 'signature' | 'src_ip' | 'dest_ip' | 'category';
	// OLD CODE END
	type SortKey = 'timestamp' | 'severity' | 'signature' | 'src_ip' | 'dest_ip' | 'protocol' | 'category';
	let sortKey = $state<SortKey>('timestamp');
	let sortDir = $state<'asc' | 'desc'>('desc');
	// Each column's name on the daemon, which sorts every page (#146)
	const SERVER_SORT: Record<SortKey, AlertSort> = {
		timestamp: 'time', severity: 'severity', signature: 'signature', src_ip: 'source',
		dest_ip: 'destination', protocol: 'proto', category: 'category',
	};

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	// OLD CODE START — 2026-11-03: the hand-drawn timeline and bar lists scaled themselves; AreaChart and BarList do it now
	// let maxBucketTotal = $derived(
	// 	Math.max(1, ...timeline.map((b) => b.high + b.medium + b.low))
	// );
	// OLD CODE END

	let filteredSignatures = $derived.by(() => {
		if (!signatureSearch) return topSignatures;
		const q = signatureSearch.toLowerCase();
		return topSignatures.filter((s) => s.signature.toLowerCase().includes(q));
	});

	// OLD CODE START — 2026-11-03: BarList scales to its largest item
	// let maxSigCount = $derived(topSignatures.length > 0 ? topSignatures[0].count : 1);
	//
	// let maxDestIpCount = $derived(topDestIps.length > 0 ? topDestIps[0].count : 1);
	// let maxSrcIpCount = $derived(topSrcIps.length > 0 ? topSrcIps[0].count : 1);
	// OLD CODE END

	// OLD CODE START — PLAN.md §4.1: "Critical" was the malware-c2 category, which overlaps High; the
	// category's figure now shows with the other smart-alert categories in the threat summary card
	// /** Compute "critical" count as total minus high+medium+low (info-severity alerts). */
	// let criticalCount = $derived(
	// 	smartSummary
	// 		? (smartSummary.categories['malware-c2']?.events ?? 0)
	// 		: 0
	// );
	// OLD CODE END

	// OLD CODE START — #146: ordered only the page of rows it had; the daemon sorts every page now
	// let sortedAlerts = $derived.by(() => {
	// 	const list = [...alerts];
	// 	list.sort((a, b) => {
	// 		let cmp = 0;
	// 		switch (sortKey) {
	// 			case 'timestamp':
	// 				// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 				// cmp = (a.timestamp || '').localeCompare(b.timestamp || '');
	// 				// OLD CODE END
	// 				cmp = compareValues(a.timestamp || '', b.timestamp || '');
	// 				break;
	// 			case 'severity':
	// 				// OLD CODE START — Suricata's 1 is the most severe, so the first (descending) click put LOW on top
	// 				// cmp = (a.alert?.severity ?? 4) - (b.alert?.severity ?? 4);
	// 				// OLD CODE END
	// 				cmp = severityRank(a.alert?.severity) - severityRank(b.alert?.severity);
	// 				break;
	// 			case 'protocol':
	// 				cmp = compareValues(a.proto ?? '', b.proto ?? '');
	// 				break;
	// 			case 'signature':
	// 				// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 				// cmp = (a.alert?.signature || '').localeCompare(b.alert?.signature || '');
	// 				// OLD CODE END
	// 				cmp = compareValues(a.alert?.signature || '', b.alert?.signature || '');
	// 				break;
	// 			case 'src_ip':
	// 				// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 				// cmp = (a.src_ip || '').localeCompare(b.src_ip || '');
	// 				// OLD CODE END
	// 				cmp = compareValues(a.src_ip || '', b.src_ip || '');
	// 				break;
	// 			case 'dest_ip':
	// 				// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 				// cmp = (a.dest_ip || '').localeCompare(b.dest_ip || '');
	// 				// OLD CODE END
	// 				cmp = compareValues(a.dest_ip || '', b.dest_ip || '');
	// 				break;
	// 			case 'category':
	// 				// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 				// cmp = (a.alert?.category || '').localeCompare(b.alert?.category || '');
	// 				// OLD CODE END
	// 				cmp = compareValues(a.alert?.category || '', b.alert?.category || '');
	// 				break;
	// 		}
	// 		return sortDir === 'asc' ? cmp : -cmp;
	// 	});
	// 	return list;
	// });
	// OLD CODE END
	// The daemon returns the rows in the table's order (#146)
	let sortedAlerts = $derived(alerts);

	const range = $derived(TIME_RANGES.find((r) => r.value === selectedTimeRange) ?? TIME_RANGES[3]);
	const rangeHours = $derived(range.ms / 3_600_000);
	// One global count per window, shared with Home and the sidebar (PLAN.md §4.1)
	const snapshot = $derived($alertSnapshots[rangeHours]);
	// on 'error' the store keeps the last good counts (#96): show them with a stale note, as Home does
	const counts = $derived(snapshot?.data?.counts);
	const buckets = $derived(counts ? severityBuckets(counts) : []);
	const groups = $derived(groupAlerts(sortedAlerts));
	const fromRow = $derived(totalAlerts > 0 ? (currentPage - 1) * pageSize + 1 : 0);
	const toRow = $derived(Math.min(totalAlerts, fromRow + alerts.length - 1));

	// OLD CODE START — the counts come from the shared alert snapshot, and info from severityBuckets
	// function filterCountForTab(filter: SeverityFilter): number {
	// 	switch (filter) {
	// 		case 'all':
	// 			return alertCounts.total;
	// 		case 'high':
	// 			return alertCounts.high;
	// 		case 'medium':
	// 			return alertCounts.medium;
	// 		case 'low':
	// 			return alertCounts.low;
	// 		case 'info':
	// 			return Math.max(
	// 				0,
	// 				alertCounts.total - alertCounts.high - alertCounts.medium - alertCounts.low
	// 			);
	// 	}
	// }
	// OLD CODE END
	function filterCountForTab(filter: SeverityFilter): string {
		if (!counts) return '—';
		const n = filter === 'all' ? counts.total : (buckets.find((b) => b.level === filter)?.count ?? 0);
		return n.toLocaleString('en-GB');
	}

	const severityOptions = $derived(
		SEVERITY_FILTERS.map((f) => ({ value: f.value, label: `${f.label} ${filterCountForTab(f.value)}` })),
	);

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function getTimeRange(): { from: string; to: string } {
		const now = Date.now();
		const range = TIME_RANGES.find((r) => r.value === selectedTimeRange) || TIME_RANGES[3];
		return {
			from: new Date(now - range.ms).toISOString(),
			to: new Date(now).toISOString(),
		};
	}

	function severityFilterToNumber(f: SeverityFilter): number | undefined {
		switch (f) {
			case 'high':
				return 1;
			case 'medium':
				return 2;
			case 'low':
				return 3;
			default:
				return undefined;
		}
	}

	function formatTimestamp(ts: string): string {
		try {
			return new Date(ts).toLocaleString(undefined, {
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit',
				second: '2-digit',
			});
		} catch {
			return ts;
		}
	}

	function formatShortTimestamp(ts: string): string {
		try {
			return new Date(ts).toLocaleString(undefined, {
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit',
			});
		} catch {
			return ts;
		}
	}

	// OLD CODE START — the DataTable owns the header buttons and reports the new sort (onsortchange)
	// function toggleSort(key: SortKey) {
	// 	if (sortKey === key) {
	// 		sortDir = sortDir === 'asc' ? 'desc' : 'asc';
	// 	} else {
	// 		sortKey = key;
	// 		// OLD CODE START — severity is now a rank (higher = worse), so it starts descending like time
	// 		// sortDir = key === 'timestamp' ? 'desc' : 'asc';
	// 		// OLD CODE END
	// 		sortDir = key === 'timestamp' || key === 'severity' ? 'desc' : 'asc';
	// 	}
	// 	fetchAlerts(1);
	// }
	//
	// function sortIndicator(key: SortKey): string {
	// 	if (sortKey !== key) return '';
	// 	return sortDir === 'asc' ? ' ↑' : ' ↓';
	// }
	// OLD CODE END
	function changeSort(key: string, dir: 'asc' | 'desc') {
		sortKey = key as SortKey;
		sortDir = dir;
		fetchAlerts(1);
	}

	function copyToClipboard(text: string, e: Event) {
		e.stopPropagation();
		navigator.clipboard.writeText(text);
	}

	// OLD CODE START — 2026-11-03 redesign: helpers for the hand-drawn category cards, sparklines and
	// threat gauge, replaced by BarList, Ring and SeverityPill (no emoji, no raw colour names)
	// /** Convert sparkline data array to SVG polyline points. */
	// function sparklinePoints(data: number[]): string {
	// 	if (!data.length) return '';
	// 	const max = Math.max(...data, 1);
	// 	return data.map((v, i) => {
	// 		const x = (i / Math.max(data.length - 1, 1)) * 56;
	// 		const y = 20 - (v / max) * 18;
	// 		return `${x},${y}`;
	// 	}).join(' ');
	// }
	//
	// /** Map category color names to CSS variable references. */
	// /** Map icon name from API to emoji for category cards */
	// const ICON_EMOJI: Record<string, string> = {
	// 	'shield-alert': '\u{1F6E1}', 'upload-cloud': '\u{2601}', 'search': '\u{1F50D}', 'bug': '\u{1F41B}',
	// 	'gavel': '\u{2696}', 'alert-triangle': '\u{26A0}', 'key': '\u{1F511}', 'globe': '\u{1F310}',
	// 	'lock': '\u{1F512}', 'cpu': '\u{1F4BB}', 'zap': '\u{26A1}', 'eye': '\u{1F441}', 'info': '\u{2139}',
	// };
	//
	// function catIconEmoji(icon: string): string {
	// 	return ICON_EMOJI[icon] ?? '\u{2139}';
	// }
	//
	// function catColorVar(color: string): string {
	// 	if (color === 'muted') return 'var(--text-muted)';
	// 	if (color.startsWith('#') || color.startsWith('rgb')) return color;
	// 	return `var(--${color})`;
	// }
	//
	// function catColorDimVar(color: string): string {
	// 	if (color === 'muted') return 'var(--bg-tertiary)';
	// 	if (color.startsWith('#') || color.startsWith('rgb')) return `${color}33`;
	// 	return `var(--${color}-dim)`;
	// }
	//
	// /** Compute percentage of a severity count within a category. */
	// function sevPct(cat: AlertCategory, level: 'critical' | 'high' | 'medium' | 'low' | 'info'): number {
	// 	const total = cat.severity_breakdown.critical + cat.severity_breakdown.high + cat.severity_breakdown.medium + cat.severity_breakdown.low + cat.severity_breakdown.info;
	// 	if (total === 0) return 0;
	// 	return (cat.severity_breakdown[level] / total) * 100;
	// }
	//
	// /** Determine trend CSS class for category cards. */
	// function trendClass(dir: string): string {
	// 	if (dir === 'increasing') return 'up-bad';
	// 	if (dir === 'decreasing') return 'down-good';
	// 	return 'stable';
	// }
	//
	// /** Get threat score color based on score value. */
	// function threatScoreColor(score: number): string {
	// 	if (score >= 75) return 'var(--red)';
	// 	if (score >= 50) return 'var(--orange)';
	// 	if (score >= 25) return 'var(--amber)';
	// 	return 'var(--green)';
	// }
	//
	// /** Compute the arc path for the threat gauge based on score (0-100). */
	// function threatArcPath(score: number): string {
	// 	// Semi-circle from (6,28) to (54,28) with radius 24, center (30,28)
	// 	const fraction = Math.min(score, 100) / 100;
	// 	const angle = Math.PI * fraction;
	// 	const endX = 30 - 24 * Math.cos(angle);
	// 	const endY = 28 - 24 * Math.sin(angle);
	// 	const largeArc = fraction > 0.5 ? 1 : 0;
	// 	return `M 6 28 A 24 24 0 ${largeArc} 1 ${endX.toFixed(1)} ${endY.toFixed(1)}`;
	// }
	//
	// /** Get the threat level badge color. */
	// function threatLevelColor(level: string): { bg: string; text: string } {
	// 	switch (level) {
	// 		case 'critical': return { bg: 'var(--sev-critical-muted)', text: 'var(--sev-critical)' };
	// 		case 'high': return { bg: 'var(--sev-high-muted)', text: 'var(--sev-high)' };
	// 		case 'medium': return { bg: 'var(--sev-medium-muted)', text: 'var(--sev-medium)' };
	// 		case 'low': return { bg: 'var(--sev-low-muted)', text: 'var(--sev-low)' };
	// 		default: return { bg: 'var(--green-dim)', text: 'var(--ok)' };
	// 	}
	// }
	// OLD CODE END

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	// OLD CODE START — PLAN.md §5.5: didn't report what loaded, and a slow older load could overwrite a newer one
	// // OLD CODE START — always reloaded page 1, so auto-refresh threw the user back to the first page
	// // async function fetchAll() {
	// // OLD CODE END
	// /** Reload everything; the alert table stays on `pg` (the current page unless told otherwise). */
	// async function fetchAll(pg: number = currentPage) {
	// 	loading = true;
	// 	const { from, to } = getTimeRange();
	// 	const interval = INTERVAL_MAP[selectedTimeRange] || '1h';
	//
	// 	const results = await Promise.allSettled([
	// 		getAlertCount({ from, to }),
	// 		getAlertTimeline({ from, to, interval }),
	// 		getAlertTopSignatures({ from, to, limit: 20 }),
	// 		getAlertTopIps({ from, to, limit: 10, direction: 'dest' }),
	// 		getAlertTopIps({ from, to, limit: 10, direction: 'src' }),
	// 		getEnhancedCategories({ from, to }),
	// 		getAlerts({
	// 			from,
	// 			to,
	// 			severity: severityFilterToNumber(activeFilter),
	// 			// OLD CODE START
	// 			// page: 1,
	// 			// OLD CODE END
	// 			page: pg,
	// 			size: pageSize,
	// 			ip: ipFilter || undefined,
	// 			signature: signatureFilter || undefined,
	// 			sort: SERVER_SORT[sortKey],
	// 			order: sortDir,
	// 		}),
	// 		getSmartAlertSummary({ from, to }),
	// 	]);
	//
	// 	if (results[0].status === 'fulfilled') alertCounts = results[0].value.counts;
	// 	if (results[1].status === 'fulfilled') timeline = results[1].value.buckets;
	// 	if (results[2].status === 'fulfilled') topSignatures = results[2].value.signatures;
	// 	if (results[3].status === 'fulfilled') topDestIps = results[3].value.ips;
	// 	if (results[4].status === 'fulfilled') topSrcIps = results[4].value.ips;
	// 	if (results[5].status === 'fulfilled') enhancedCategories = results[5].value.categories;
	// 	if (results[6].status === 'fulfilled') {
	// 		const r = results[6].value;
	// 		alerts = r.alerts;
	// 		totalPages = r.total_pages;
	// 		totalAlerts = r.total;
	// 		// OLD CODE START
	// 		// currentPage = 1;
	// 		// OLD CODE END
	// 		currentPage = r.page;
	// 	}
	// 	if (results[7].status === 'fulfilled') {
	// 		smartSummary = results[7].value;
	// 		threatScore = results[7].value.threat_score;
	// 		threatLevel = results[7].value.threat_level;
	// 	}
	// 	const sections = ['counts', 'timeline', 'signatures', 'destIps', 'srcIps', 'categories', 'alerts', 'summary'];
	// 	failed = Object.fromEntries(sections.map((name, i) => [name, results[i].status === 'rejected']));
	// 	loading = false;
	// }
	//
	// async function fetchAlerts(pg: number = 1) {
	// 	loading = true;
	// 	const { from, to } = getTimeRange();
	// 	try {
	// 		const r = await getAlerts({
	// 			from,
	// 			to,
	// 			severity: severityFilterToNumber(activeFilter),
	// 			page: pg,
	// 			size: pageSize,
	// 			ip: ipFilter || undefined,
	// 			signature: signatureFilter || undefined,
	// 			sort: SERVER_SORT[sortKey],
	// 			order: sortDir,
	// 		});
	// 		alerts = r.alerts;
	// 		totalPages = r.total_pages;
	// 		totalAlerts = r.total;
	// 		currentPage = r.page;
	// 		failed = { ...failed, alerts: false };
	// 	} catch {
	// 		alerts = [];
	// 		totalPages = 0;
	// 		totalAlerts = 0;
	// 		failed = { ...failed, alerts: true };
	// 	} finally {
	// 		loading = false;
	// 	}
	// }
	// OLD CODE END

	/** The list request for page `pg`, built from the filters as they are now (copied before any await). */
	function listParams(pg: number, window: { from: string; to: string }) {
		return {
			...window,
			severity: severityFilterToNumber(activeFilter),
			page: pg,
			size: pageSize,
			ip: ipFilter || undefined,
			signature: signatureFilter || undefined,
			sort: SERVER_SORT[sortKey],
			order: sortDir,
		};
	}

	function applyList(result: PromiseSettledResult<AlertsListResponse>) {
		if (result.status === 'fulfilled') {
			const r = result.value;
			alerts = r.alerts;
			totalPages = r.total_pages;
			totalAlerts = r.total;
			currentPage = r.page;
		} else {
			// a failure clears the list: the rows on screen may be another filter's or range's
			alerts = [];
			totalPages = 0;
			totalAlerts = 0;
		}
		failed = { ...failed, alerts: result.status === 'rejected' };
		listLoaded = true;
	}

	// The list has its own generation as well, so a filter change mid-refresh drops only the
	// refresh's stale list and keeps the rest of what it loaded
	const listGuard = createLoadGuard();
	/** The snapshot window this page already loaded: loading it again is a refresh. */
	let snapshotHoursLoaded: number | null = null;

	/**
	 * The page refresh contract (PLAN.md §5.5): every request, awaited, then the result.
	 * The alert table stays on the current page.
	 */
	async function loadAll(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const lg = listGuard.begin();
		const timeRange = TIME_RANGES.find((r) => r.value === selectedTimeRange) ?? TIME_RANGES[3];
		const hours = timeRange.ms / 3_600_000;
		const { from, to } = getTimeRange();
		const interval = INTERVAL_MAP[timeRange.value] || '1h';
		const list = listParams(currentPage, { from, to });

		// A refresh moves every reader of the shared count (sidebar, Home) to the new window together
		if (snapshotHoursLoaded === hours) void refreshAlertSnapshots();
		snapshotHoursLoaded = hours;

		const [snap, results] = await Promise.all([
			loadAlertSnapshot(hours),
			Promise.allSettled([
				getAlertTimeline({ from, to, interval }),
				getAlertTopSignatures({ from, to, limit: 20 }),
				getAlertTopIps({ from, to, limit: 10, direction: 'dest' }),
				getAlertTopIps({ from, to, limit: 10, direction: 'src' }),
				getEnhancedCategories({ from, to }),
				getAlerts(list),
				getSmartAlertSummary({ from, to }),
			] as const),
		]);
		const [tl, sigs, dest, src, cats, listResult, summary] = results;
		const succeeded = [snap.status === 'ok', ...results.map((r) => r.status === 'fulfilled')];
		if (!guard.current(g)) return 'skipped';

		if (tl.status === 'fulfilled') timeline = tl.value.buckets;
		if (sigs.status === 'fulfilled') topSignatures = sigs.value.signatures;
		if (dest.status === 'fulfilled') topDestIps = dest.value.ips;
		if (src.status === 'fulfilled') topSrcIps = src.value.ips;
		if (cats.status === 'fulfilled') enhancedCategories = cats.value.categories;
		if (summary.status === 'fulfilled') {
			smartSummary = summary.value;
			threatScore = summary.value.threat_score;
			threatLevel = summary.value.threat_level;
		}
		const sections = ['timeline', 'signatures', 'destIps', 'srcIps', 'categories', 'alerts', 'summary'];
		failed = { ...Object.fromEntries(sections.map((name, i) => [name, results[i].status === 'rejected'])), alerts: failed.alerts ?? false };
		if (listGuard.current(lg)) applyList(listResult);
		loaded = true;

		if (succeeded.every(Boolean)) return 'ok';
		return succeeded.some(Boolean) ? 'partial' : 'failed';
	}

	const refresh = registerPageRefresh(loadAll);

	async function fetchAlerts(pg: number = 1) {
		const lg = listGuard.begin();
		const params = listParams(pg, getTimeRange());
		const result = await getAlerts(params).then(
			(value): PromiseSettledResult<AlertsListResponse> => ({ status: 'fulfilled', value }),
			(reason): PromiseSettledResult<AlertsListResponse> => ({ status: 'rejected', reason }),
		);
		if (listGuard.current(lg)) applyList(result);
	}

	function scrollToList() {
		document.getElementById('alerts-table')?.scrollIntoView?.({ behavior: 'smooth' });
	}

	function handleTimeRangeChange(value: string) {
		selectedTimeRange = value;
		// A new time range is a new result set: start from page 1
		// OLD CODE START — waited for the first load; the guards drop whichever load is older now
		// if (initialized) fetchAll(1);
		// OLD CODE END
		currentPage = 1;
		refresh.run();
	}

	function handleSeverityChange(value: SeverityFilter) {
		activeFilter = value;
		// OLD CODE START — waited for the first load; the list guard drops the older list now
		// if (initialized) fetchAlerts(1);
		// OLD CODE END
		fetchAlerts(1);
	}

	/** A severity tile: filter the list by that severity and bring it into view (the old stat cards). */
	function showSeverity(level: SeverityFilter) {
		handleSeverityChange(level);
		scrollToList();
	}

	function filterBySignature(sig: string) {
		// Toggle: click same signature again to clear filter
		if (signatureFilter === sig) {
			signatureFilter = '';
		} else {
			signatureFilter = sig;
		}
		// OLD CODE START — waited for the first load; the list guard drops the older list now
		// if (initialized) {
		// 	fetchAlerts(1).then(() => {
		// 		document.getElementById('alerts-table')?.scrollIntoView({ behavior: 'smooth' });
		// 	});
		// }
		// OLD CODE END
		fetchAlerts(1).then(scrollToList);
	}

	function clearSignatureFilter() {
		signatureFilter = '';
		// OLD CODE START — waited for the first load; the list guard drops the older list now
		// if (initialized) fetchAlerts(1);
		// OLD CODE END
		fetchAlerts(1);
	}

	// Pagination
	function goToPage(pg: number) {
		if (pg < 1 || pg > totalPages) return;
		fetchAlerts(pg);
	}

	// Auto-refresh
	function toggleAutoRefresh() {
		autoRefresh = !autoRefresh;
		if (autoRefresh) {
			// OLD CODE START
			// refreshInterval = setInterval(fetchAll, 15_000);
			// OLD CODE END
			// OLD CODE START — the auto loop goes through the page refresh contract, so "Updated" stays honest
			// refreshInterval = setInterval(() => fetchAll(), 15_000);
			// OLD CODE END
			refreshInterval = setInterval(() => refresh.run(), 15_000);
		} else if (refreshInterval) {
			clearInterval(refreshInterval);
			refreshInterval = null;
		}
	}

	// OLD CODE START — replaced by DetailDrawer
	// function openAlertDetail(alert: Alert) { selectedAlert = alert; }
	// function closeAlertDetail() { selectedAlert = null; }
	// function toggleExpandRow(alertId: string) { ... }
	// OLD CODE END

	function openDrawer(alert: Alert) {
		drawerAlert = alert;
		// OLD CODE START — the drawer has no tabs now
		// drawerTab = 'summary';
		// OLD CODE END
	}

	function closeDrawer() {
		drawerAlert = null;
		// OLD CODE START — the drawer has no tabs now
		// drawerTab = 'summary';
		// OLD CODE END
	}

	// OLD CODE START — a refused acknowledgement did nothing, so it looked like the click was lost
	// async function handleDrawerAcknowledge(alertId: string) {
	// 	const result = await acknowledgeAlert(alertId);
	// 	if (result && drawerAlert) {
	// 		drawerAlert.acknowledged = true;
	// 		drawerAlert.acknowledged_at = result.acknowledged_at;
	// 	}
	// }
	// OLD CODE END
	async function handleDrawerAcknowledge(alertId: string) {
		const result = await acknowledgeAlert(alertId);
		if (!result) throw new Error('the acknowledgement failed. Try again.');
		if (drawerAlert) {
			drawerAlert.acknowledged = true;
			drawerAlert.acknowledged_at = result.acknowledged_at;
		}
	}

	// OLD CODE START — no error handling; the helpers now throw when the daemon refuses
	// async function handleSuppressAlert(alert: Alert) {
	// 	const sigId = alert.alert?.signature_id;
	// 	if (sigId) {
	// 		await suppressAlert(sigId);
	// 		// Refresh alerts to reflect the change
	// 		fetchAlerts(currentPage);
	// 	}
	// }
	//
	// async function handleFalsePositive(alert: Alert) {
	// 	const sigId = alert.alert?.signature_id;
	// 	if (sigId) {
	// 		await markFalsePositive(sigId);
	// 		fetchAlerts(currentPage);
	// 	}
	// }
	// OLD CODE END
	async function runAlertAction(action: () => Promise<void>) {
		actionError = '';
		try {
			await action();
			// Refresh alerts to reflect the change
			fetchAlerts(currentPage);
		} catch (err) {
			actionError = err instanceof Error ? err.message : 'Action failed';
		}
	}

	async function handleSuppressAlert(alert: Alert) {
		const sigId = alert.alert?.signature_id;
		if (sigId) await runAlertAction(() => suppressAlert(sigId));
	}

	async function handleFalsePositive(alert: Alert) {
		const sigId = alert.alert?.signature_id;
		if (sigId) await runAlertAction(() => markFalsePositive(sigId));
	}

	/** The drawer's own Suppress and False positive: the same calls, with the error in the drawer. */
	async function drawerAction(alert: Alert, action: (sigId: number) => Promise<void>) {
		const sigId = alert.alert?.signature_id;
		if (!sigId) return;
		await action(sigId);
		fetchAlerts(currentPage);
	}

	// ---------------------------------------------------------------------------
	// IP filter reactivity
	// ---------------------------------------------------------------------------

	let prevIpFilter: string | null = null;
	$effect(() => {
		if (prevIpFilter !== null && prevIpFilter !== ipFilter) {
			fetchAlerts(1);
		}
		prevIpFilter = ipFilter;
	});

	// ---------------------------------------------------------------------------
	// Init
	// ---------------------------------------------------------------------------

	// OLD CODE START — loads go through the page refresh contract now
	// onMount(() => {
	// 	fetchAll().then(() => {
	// 		initialized = true;
	// 	});
	// 	return () => {
	// 		if (refreshInterval) clearInterval(refreshInterval);
	// 	};
	// });
	// OLD CODE END
	onMount(() => {
		refresh.run();
	});

	onDestroy(() => {
		if (refreshInterval) clearInterval(refreshInterval);
		refresh.unregister();
		listGuard.invalidate();
	});

	// ---------------------------------------------------------------------------
	// View data
	// ---------------------------------------------------------------------------

	const fmt = (n: number) => n.toLocaleString('en-GB');
	const rowKey = (a: Alert) => `${a._id}-${alerts.indexOf(a)}`;
	// After a reload the open alert is a new object: find its row by id
	const selectedRowKey = $derived.by(() => {
		const open = drawerAlert && alerts.find((a) => a._id === drawerAlert?._id);
		return open ? rowKey(open) : undefined;
	});

	const timelineTotals = $derived(timeline.map((b) => b.high + b.medium + b.low));
	const busiest = $derived(timelineTotals.reduce((best, v, i) => (v > timelineTotals[best] ? i : best), 0));
	const timelineLabel = $derived(
		timelineTotals.length && timelineTotals[busiest] > 0
			? `Busiest ${formatShortTimestamp(timeline[busiest].timestamp)}, with ${fmt(timelineTotals[busiest])} alerts`
			: `No alerts in the ${range.words}`,
	);
	const gaugeLabel = $derived(
		counts
			? `${fmt(counts.total)} alerts in the ${range.words}: ${buckets.map((b) => `${fmt(b.count)} ${b.level}`).join(', ')}`
			: '',
	);
	const smartCategories = $derived(
		Object.entries(smartSummary?.categories ?? {})
			.map(([key, c]) => ({ key, ...c }))
			.sort((a, b) => b.events - a.events || a.label.localeCompare(b.label)),
	);
	const threatPill = $derived(THREAT_LEVELS.find((l) => l === threatLevel));

	const ipBars = (entries: AlertIpEntry[]) =>
		entries.map((e) => ({ key: e.ip, label: e.ip, value: e.count, display: fmt(e.count), href: `/devices/${e.ip}` }));

	const columns: Column<Alert>[] = [
		{ key: 'timestamp', label: 'Time', cell: timeCell },
		{ key: 'severity', label: 'Severity', cell: severityCell },
		{ key: 'signature', label: 'Signature', class: 'sig-cell', cell: signatureCell },
		{ key: 'src_ip', label: 'Source', cell: srcCell },
		{ key: 'dest_ip', label: 'Destination', cell: destCell },
		{ key: 'protocol', label: 'Protocol', cell: protoCell },
		// Suppress and False positive sit in the last column: every column sorts, so there is no "Actions" one
		{ key: 'category', label: 'Category', cell: categoryCell },
	];

	const signatureColumns: Column<AlertSignature>[] = [
		{ key: 'signature', label: 'Signature', cell: sigNameCell },
		{ key: 'severity', label: 'Severity', sortValue: (s) => severityRank(s.severity), cell: sigSeverityCell },
		{ key: 'count', label: 'Alerts', numeric: true, cell: sigCountCell },
	];
</script>

{#snippet timeCell(a: Alert)}
	<span class="mono">{formatTimestamp(a.timestamp)}</span>{#if a.acknowledged}<span class="chip">Acknowledged</span>{/if}
{/snippet}
{#snippet severityCell(a: Alert)}<SeverityPill level={alertLevel(a.alert?.severity)} />{/snippet}
{#snippet signatureCell(a: Alert)}<span class="mono" title={a.alert?.signature || 'Unknown'}>{a.alert?.signature || 'Unknown'}</span>{/snippet}
{#snippet srcCell(a: Alert)}{#if a.src_ip}<IPAddress ip={a.src_ip} />{:else}<span class="dim">—</span>{/if}{/snippet}
{#snippet destCell(a: Alert)}{#if a.dest_ip}<IPAddress ip={a.dest_ip} />{:else}<span class="dim">—</span>{/if}{/snippet}
{#snippet protoCell(a: Alert)}{#if a.proto}<span class="tag">{a.proto.toUpperCase()}</span>{:else}<span class="dim">—</span>{/if}{/snippet}
{#snippet categoryCell(a: Alert)}
	<span class="cat-cell">
		<span>{a.alert?.category || '—'}</span>
		<span class="row-actions">
			<button class="btn" type="button" title="Suppress this signature" onclick={(e) => { e.stopPropagation(); handleSuppressAlert(a); }}>Suppress</button>
			<button class="btn" type="button" title="Mark as false positive" onclick={(e) => { e.stopPropagation(); handleFalsePositive(a); }}>False positive</button>
		</span>
	</span>
{/snippet}
{#snippet sigNameCell(s: AlertSignature)}<span class="mono">{s.signature}</span>{/snippet}
{#snippet sigSeverityCell(s: AlertSignature)}<SeverityPill level={alertLevel(s.severity)} />{/snippet}
{#snippet sigCountCell(s: AlertSignature)}{fmt(s.count)}{/snippet}

<svelte:head>
	<title>Alerts | NetTap</title>
</svelte:head>

<header class="page-head">
	<div>
		<h1 class="page-title">Alerts</h1>
		<p class="page-sub">What Suricata flagged on your network · {range.words}</p>
	</div>
	<div class="head-actions">
		<Pills
			options={TIME_RANGES.map((r) => ({ value: r.value, label: r.label }))}
			value={selectedTimeRange}
			onchange={handleTimeRangeChange}
			ariaLabel="Time range"
		/>
		<div class="pills" role="group" aria-label="Auto-refresh every 15 seconds">
			<button class="pill" type="button" aria-pressed={autoRefresh} onclick={toggleAutoRefresh}>Auto</button>
		</div>
	</div>
</header>

<div class="grid">
	<Card class="c-12" title="Alerts by severity" sub="Alerts · {range.words}, by severity">
		{#if !snapshot || snapshot.status === 'loading'}
			<CardState state="loading" title="Loading alert counts" />
		{:else if !counts}
			<CardState state="error" title="Couldn't load the alert counts: the request failed." message="Check that NetTap is running on the System page, then try again." onaction={() => refresh.run()} />
		{:else}
			{#if snapshot.status === 'error'}
				<p class="notice is-warn"><Icon name="warn" /><span>{loadFailed('the alert counts', true)}</span></p>
			{/if}
			<div class="sev-sum">
				<div class="sev-left">
					<div class="sev-counts">
						{#each buckets as b (b.level)}
							<button class="sev-tile" type="button" aria-label="Show {b.level} alerts ({fmt(b.count)})" onclick={() => showSeverity(b.level as SeverityFilter)}>
								<SeverityPill level={b.level} count={b.count} />
							</button>
						{/each}
					</div>
				</div>
				<SeverityGauge {buckets} total={counts.total} ariaLabel={gaugeLabel} />
			</div>
		{/if}
	</Card>
</div>

<div class="grid alert-layout" class:no-drawer={!drawerAlert}>
	<Card class="c-8 alert-list-card" title={view === 'category' ? 'Alerts by category' : 'All alerts'} sub={listLoaded && !failed.alerts ? `${fmt(totalAlerts)} matching · ${range.words}${view === 'category' && totalAlerts > 0 ? ` · alerts ${fmt(fromRow)} to ${fmt(toRow)}, grouped` : ''}` : range.words}>
		{#snippet actions()}
			<Pills
				options={[{ value: 'category', label: 'By category' }, { value: 'all', label: 'All alerts' }]}
				bind:value={view}
				ariaLabel="Alert list view"
			/>
		{/snippet}
		<div id="alerts-table">
			<div class="toolbar">
				<Pills options={severityOptions} value={activeFilter} onchange={handleSeverityChange} ariaLabel="Severity" />
				{#if signatureFilter}
					<span class="chip">
						Signature: <span class="mono">{signatureFilter.length > 40 ? signatureFilter.slice(0, 40) + '…' : signatureFilter}</span>
						<button class="chip-x" type="button" onclick={clearSignatureFilter} aria-label="Clear signature filter"><Icon name="close" /></button>
					</span>
				{/if}
				{#if ipFilter}
					<span class="chip">
						IP: <span class="mono">{ipFilter}</span>
						<button class="chip-x" type="button" onclick={() => goto('/alerts')} aria-label="Clear IP filter"><Icon name="close" /></button>
					</span>
				{/if}
			</div>
			{#if actionError}
				<p class="notice is-error" role="alert"><Icon name="warn" />Not applied: {actionError}</p>
			{/if}
			{#if !listLoaded}
				<CardState state="loading" title="Loading alerts" />
			{:else if failed.alerts}
				<CardState state="error" title="Couldn't load alerts: the request failed." message="Check that NetTap is running on the System page, then try again." onaction={() => fetchAlerts(currentPage)} />
			{:else if alerts.length === 0}
				<CardState state="empty" icon="alerts" title="No alerts" message="Alerts will appear here once Suricata is running and generating detections." />
			{:else if view === 'category'}
				{#each groups as group (group.title)}
					<AlertGroup title={group.title} count={group.count}>
						{#each group.lines as line (line.key)}
							<AlertRow
								severity={line.level}
								title={alertTitle(line.alert)}
								signature={line.alert.alert?.signature || 'Unknown'}
								device={line.alert.src_ip ? { name: line.alert.src_ip } : undefined}
								count={line.count}
								lastSeen={shortSeen(line.lastSeen)}
								selected={drawerAlert?._id === line.alert._id}
								onselect={() => openDrawer(line.alert)}
							/>
						{/each}
					</AlertGroup>
				{/each}
			{:else}
				<DataTable
					{columns}
					rows={sortedAlerts}
					ariaLabel="Alerts, newest first unless sorted"
					{rowKey}
					initialSort={{ key: 'timestamp', dir: 'desc' }}
					onsortchange={changeSort}
					onrowactivate={openDrawer}
					rowLabel={(a) => `Open alert ${a.alert?.signature || 'Unknown'}${a.src_ip ? ` from ${a.src_ip}` : ''}`}
					selectedKey={selectedRowKey}
					pager={totalPages > 1 ? { page: currentPage, pageCount: totalPages, total: totalAlerts, from: fromRow, to: toRow, onpage: goToPage } : undefined}
				/>
			{/if}
		</div>
	</Card>
	{#if drawerAlert}
		{@const open = drawerAlert}
		{#key open._id}
			<AlertDetail
				alert={open}
				onclose={closeDrawer}
				onacknowledge={() => handleDrawerAcknowledge(open._id)}
				onsuppress={() => drawerAction(open, (sigId) => suppressAlert(sigId))}
				onfalsepositive={() => drawerAction(open, (sigId) => markFalsePositive(sigId))}
			/>
		{/key}
	{/if}
</div>

<div class="grid">
	<Card class="c-8" hero title="Alert timeline" sub="Alerts per {INTERVAL_MAP[selectedTimeRange] ?? '1h'} · {range.words}">
		{#if !loaded}
			<CardState state="loading" title="Loading the alert timeline" />
		{:else if failed.timeline}
			<CardState state="error" title="Couldn't load the alert timeline: the request failed." onaction={() => refresh.run()} />
		{:else if timeline.length === 0}
			<CardState state="empty" title="No timeline data yet" message="The timeline fills in once Suricata reports alerts in this window." />
		{:else}
			<AreaChart
				series={[{ key: 'alerts', label: 'Alerts', colour: 1, points: timeline.map((b, i) => ({ t: b.timestamp, v: timelineTotals[i] })) }]}
				formatX={(t) => formatShortTimestamp(String(t))}
				formatY={(v) => fmt(v)}
				formatTip={(i) => `${formatShortTimestamp(timeline[i].timestamp)} · ${fmt(timelineTotals[i])} alerts · High ${fmt(timeline[i].high)} · Medium ${fmt(timeline[i].medium)} · Low ${fmt(timeline[i].low)}`}
				highlightIndex={busiest}
				ariaLabel={timelineLabel}
			/>
		{/if}
	</Card>

	<Card class="c-4" title="Threat summary" sub="Smart alert analysis · {range.words}">
		{#if !loaded}
			<CardState state="loading" title="Loading the threat summary" />
		{:else if failed.summary || !smartSummary}
			<CardState state="error" title="Couldn't load the threat summary: the request failed." onaction={() => refresh.run()} />
		{:else}
			<div class="threat-top">
				<Ring value={threatScore} label="threat score" ariaLabel="Threat score {threatScore} of 100, level {threatLevel}" />
				<div class="chips">
					{#if threatPill}<SeverityPill level={threatPill} />{:else}<span class="chip">No threat level</span>{/if}
					<span class="chip">{fmt(smartSummary.total_groups)} alert groups</span>
				</div>
			</div>
			{#if smartCategories.length > 0}
				<ul class="kv">
					{#each smartCategories as c (c.key)}
						<li><span>{c.label}</span><span></span><b>{fmt(c.events)}</b><span class="pct">events</span></li>
					{/each}
				</ul>
			{:else}
				<p class="dim">No actionable alert groups in this window.</p>
			{/if}
		{/if}
	</Card>

	<Card class="c-4" title="Alert categories" sub={failed.categories ? 'Check failed' : `${enhancedCategories.length} categories · alerts per category · ${range.words}`}>
		{#if !loaded}
			<CardState state="loading" title="Loading alert categories" />
		{:else if failed.categories}
			<CardState state="error" title="Couldn't load alert categories: the request failed." onaction={() => refresh.run()} />
		{:else if enhancedCategories.length === 0}
			<CardState state="empty" title="No category data yet" message="Categories appear once Suricata reports alerts in this window." />
		{:else}
			<BarList
				items={enhancedCategories.map((cat) => ({
					key: cat.id,
					label: cat.label,
					value: cat.count,
					display: formatNumber(cat.count),
					detail: cat.trend.direction === 'stable' ? undefined : cat.trend.direction,
					href: `/alerts/${cat.id}`,
				}))}
			/>
		{/if}
	</Card>

	<Card class="c-8" title="Top signatures" sub={failed.signatures ? 'Check failed' : `${topSignatures.length} rules · alerts per rule · select one to filter the list`}>
		{#snippet actions()}
			<SearchField id="alerts-signature-search" label="Search signatures" placeholder="Search signatures…" size="toolbar" bind:value={signatureSearch} />
		{/snippet}
		{#if !loaded}
			<CardState state="loading" title="Loading top signatures" />
		{:else if failed.signatures}
			<CardState state="error" title="Couldn't load top signatures: the request failed." onaction={() => refresh.run()} />
		{:else if filteredSignatures.length === 0}
			<CardState state="empty" title="No signatures found" message={signatureSearch ? 'No rule matches that search.' : 'Rules appear here once Suricata reports alerts in this window.'} />
		{:else}
			<DataTable
				columns={signatureColumns}
				rows={filteredSignatures}
				ariaLabel="Top signatures"
				rowKey={(s) => s.signature}
				initialSort={{ key: 'count', dir: 'desc' }}
				onrowactivate={(s) => filterBySignature(s.signature)}
				rowLabel={(s) => (signatureFilter === s.signature ? `Clear the filter for ${s.signature}` : `Filter alerts by ${s.signature}`)}
				selectedKey={signatureFilter || undefined}
			/>
		{/if}
	</Card>

	<Card class="c-6 ip-bars" title="Top affected devices" sub="Alerts per destination · {range.words}">
		{#if !loaded}
			<CardState state="loading" title="Loading affected devices" />
		{:else if failed.destIps}
			<CardState state="error" title="Couldn't load affected devices: the request failed." onaction={() => refresh.run()} />
		{:else if topDestIps.length === 0}
			<CardState state="empty" title="No destination IPs found" message="Devices appear here once alerts name them as the destination." />
		{:else}
			<BarList items={ipBars(topDestIps)} />
		{/if}
	</Card>

	<Card class="c-6 ip-bars" title="Top source IPs" sub="Alerts per source · {range.words}">
		{#if !loaded}
			<CardState state="loading" title="Loading source IPs" />
		{:else if failed.srcIps}
			<CardState state="error" title="Couldn't load source IPs: the request failed." onaction={() => refresh.run()} />
		{:else if topSrcIps.length === 0}
			<CardState state="empty" title="No source IPs found" message="Sources appear here once alerts name them." />
		{:else}
			<BarList items={ipBars(topSrcIps)} />
		{/if}
	</Card>
</div>

<style>
	/* Layout glue the system lacks */
	.alert-layout { align-items: start; }
	.sev-tile {
		all: unset; display: flex; cursor: pointer; color: var(--text-1); border-radius: var(--r-md);
	}
	.sev-tile > :global(.sev-count) { flex: 1; transition: background var(--dur-fast); }
	.sev-tile:hover > :global(.sev-count) { background: var(--surface-3); }
	.sev-tile:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
	.chip-x {
		all: unset; display: inline-grid; place-items: center; cursor: pointer; color: var(--text-2); border-radius: var(--r-pill);
	}
	.chip-x:hover { color: var(--text-1); }
	.chip-x:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
	.notice { margin-bottom: var(--sp-4); }
	.cat-cell { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); }
	.row-actions { display: inline-flex; gap: var(--sp-1); }
	.row-actions .btn { min-height: 28px; padding: 0 var(--sp-3); font-size: var(--text-xs); }
	.threat-top { display: flex; align-items: center; gap: var(--sp-5); margin-bottom: var(--sp-4); }
	:global(.ip-bars) :global(.bar-label), :global(.ip-bars) :global(.bars li > span:first-child) { font-family: var(--font-mono); }
</style>
