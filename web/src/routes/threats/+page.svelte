<script lang="ts">
	/**
	 * Threats page — /threats
	 *
	 * Behavioural threat analysis from the threat report and the threat intel feeds:
	 *   1. KPI row (threat score, alert groups, kill chains, beaconing)
	 *   2. Threat brief + threat intel matches
	 *   3. Active kill chains
	 *   4. Beaconing + DNS anomalies
	 *   5. Lateral movement
	 *   6. Auto-investigations
	 */

	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	// OLD CODE: import { getThreatReport, getThreatIntel } from '$api/threats'; (NET-192 PR 3: the pill → request helper)
	import { getBeaconing, getThreatReport, getThreatIntel, threatRequest, type ThreatRequest } from '$api/threats';
	// OLD CODE: import { THREAT_SCORE_HOW } from '$api/alerts'; (NET-225: and the bridge-mode line)
	// OLD CODE: import { THREAT_SCORE_BRIDGE, THREAT_SCORE_HOW } from '$api/alerts'; (NET-239: and the score's inputs)
	import { scoreInputs, THREAT_SCORE_BRIDGE, THREAT_SCORE_HOW } from '$api/alerts';
	import { captureMode, initCaptureMode } from '$lib/stores/captureMode';
	import { formatBytes, formatCompactNumber as formatNumber } from '$lib/api/logs';
	import type {
		ThreatReport,
		BeaconSuspect,
		LateralMovement,
		ThreatIntelInfo,
	} from '$api/threats';
	import { registerPageRefresh, type LoadGuard, type LoadResult, outcome } from '$lib/stores/pageRefresh';
	import type { SeverityLevel } from '$lib/utils/severity';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import BarList from '$lib/components/ui/BarList.svelte';
	import Meter from '$lib/components/ui/Meter.svelte';
	import StackBar from '$lib/components/ui/charts/StackBar.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import IPAddress from '$components/IPAddress.svelte';
	import { ipHref } from '$lib/stores/lan';
	import { formatTime } from '$lib/utils/time';
	// OLD CODE: import { DRILL_RANGES, rangeWindow, startRange } from '$lib/utils/drilldown'; (NET-238: fmt, SCAN_CAP)
	import { DRILL_RANGES, fmt, rangeWindow, SCAN_CAP, startRange } from '$lib/utils/drilldown';
	// NET-228 (audit B5): "nothing needs attention" carries the pipeline's current state
	// OLD CODE: import { getSystemHealth, nothingFound, type SystemHealth } from '$api/system'; (review L7)
	// OLD CODE: import { nothingFound } from '$api/system'; (NET-242: and the page-level pipeline line)
	import { nothingFound, pipelineProblem } from '$api/system';
	import { HEALTH_CHECKING, readHealth, type HealthCheck } from '$lib/utils/read-health';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let loading = $state(true);
	let report = $state<ThreatReport | null>(null);
	let threatIntel = $state<ThreatIntelInfo | null>(null);
	// #96: a failed check must not read as "none detected"
	let intelFailed = $state(false);
	/** NET-228: the system health, for the pipeline state beside a zero; null until it loads or when it failed */
	// OLD CODE: let health = $state<SystemHealth | null>(null); let healthFailed = $state(false); (review L7: one health helper for the loaders; its failure marks only the lines that read it)
	let healthCheck = $state<HealthCheck>(HEALTH_CHECKING);
	/** NET-242: the pipeline's problem, shown even while older findings are listed */
	const pipelineNote = $derived(pipelineProblem(healthCheck));
	const BEACONS_SHOWN = 20;
	const CHECK_NAMES: Record<string, string> = {
		beaconing: 'beaconing',
		dns_anomalies: 'DNS anomalies',
		lateral_movement: 'lateral movement',
		investigations: 'auto-investigations',
	};
	// OLD CODE START — NET-196: the app's one list (DRILL_RANGES)
	// const RANGES = [
	// 	{ value: '1h', label: '1h' },
	// 	{ value: '6h', label: '6h' },
	// 	{ value: '24h', label: '24h' },
	// 	{ value: '7d', label: '7d' },
	// 	{ value: '30d', label: '30d' },
	// ];
	// const RANGE_TEXT: Record<string, string> = {
	// 	'1h': 'last hour',
	// 	'6h': 'last 6 hours',
	// 	'24h': 'last 24 hours',
	// 	'7d': 'last 7 days',
	// 	'30d': 'last 30 days',
	// };
	// OLD CODE END
	const RANGES = DRILL_RANGES.map((r) => ({ value: r.value, label: r.label }));
	// OLD CODE: let selectedRange = $state('24h'); (NET-195: Settings › Display's default, read where the range starts)
	let selectedRange = $state<string>(startRange('24h'));
	// OLD CODE START — the top bar's "Updated N s ago" (page refresh contract) replaces "Last scan";
	// this derived never re-ran as time passed, so it read "just now" until the next load
	// let lastUpdated = $state(new Date());
	// OLD CODE END
	let expandedInvestigation = $state<number | null>(0);

	// Derived
	let summary = $derived(report?.summary);
	let killChains = $derived(report?.kill_chains ?? []);
	// OLD CODE START — #96: every scheduled pair counted as a suspect (283 of 366 were one laptop's BitTorrent peers)
	// let beacons = $derived(report?.beaconing ?? []);
	// OLD CODE END
	let allBeacons = $derived(report?.beaconing ?? []);
	let beacons = $derived(allBeacons.filter((b) => b.pattern !== 'many_hosts'));
	// one row per device that contacts many internet hosts on schedules
	let manyHostSources = $derived.by(() => {
		const seen = new Map<string, number>();
		for (const b of allBeacons) {
			if (b.pattern === 'many_hosts') seen.set(b.source_ip, b.host_count ?? 0);
		}
		return [...seen].map(([ip, hosts]) => ({ ip, hosts }));
	});
	let dnsAnomalies = $derived(report?.dns_anomalies ?? { dga_suspects: [], tunnel_suspects: [], nxdomain_spikes: [], suspicious_tlds: [] });
	let lateralMoves = $derived(report?.lateral_movement ?? []);
	let investigations = $derived(report?.investigations ?? []);
	let failedChecks = $derived(new Set(report?.failed_checks ?? []));
	let incompleteChecks = $derived(new Set(report?.incomplete_checks ?? []));
	let baseline = $derived(summary?.baseline);

	// NET-192 PR 3: 24h, 7d and 30d read the background beaconing scan; its state decides what
	// the KPI, the brief and the card may say (never "none found" before a scan has finished)
	let beaconSnap = $derived(report?.beaconing_snapshot);
	let beaconPending = $derived(beaconSnap?.state === 'pending');
	let beaconFailed = $derived(failedChecks.has('beaconing') || beaconSnap?.state === 'failed');
	// a live scan the bucket cap stopped part way (a snapshot is only ever a complete scan)
	let beaconPartial = $derived(incompleteChecks.has('beaconing'));
	let beaconCheckedAt = $derived(beaconSnap?.last_success_at ? formatTime(beaconSnap.last_success_at, 'short') : null);
	// live: the report's query failed; snapshot: no background check has succeeded yet
	let beaconFailReason = $derived(failedChecks.has('beaconing') ? 'the query failed' : 'the latest check failed');
	// the page stopped asking after 10 min with the check still running: no more "a few minutes"
	let pollGaveUp = $state(false);
	let beaconPendingText = $derived(
		pollGaveUp ? 'Beaconing check still running. Refresh to check again.' : 'Beaconing check running, ready in a few minutes.',
	);
	let beaconKpiSub = $derived.by(() => {
		if (beaconPending) return pollGaveUp ? 'Still running. Refresh to check again.' : 'Check running, ready in a few minutes';
		if (beaconFailed) return `Not checked: ${beaconFailReason}`;
		// an older scan's count: say when, so it isn't read as live
		if (beaconSnap?.state === 'stale') return `Last checked ${beaconCheckedAt}`;
		return 'Devices calling one server on a schedule';
	});

	let threatScore = $derived(summary?.threat_score ?? 0);
	let threatLevel = $derived(summary?.threat_level ?? 'none');
	// OLD CODE: let rangeText = $derived(RANGE_TEXT[selectedRange] ?? selectedRange); (NET-196: the list's words)
	let rangeText = $derived(DRILL_RANGES.find((r) => r.value === selectedRange)?.words ?? selectedRange);

	// OLD CODE START — the hand-drawn gauge, legacy level colours and min-2% category bar are
	// replaced by the KPI card, SeverityPill and StackBar (data-1..6, 6 px minimum, topSeries)
	// let lastUpdatedText = $derived.by(() => {
	// 	const diff = Math.floor((Date.now() - lastUpdated.getTime()) / 1000);
	// 	if (diff < 5) return 'just now';
	// 	if (diff < 60) return `${diff}s ago`;
	// 	return `${Math.floor(diff / 60)}m ago`;
	// });
	// let gaugeArcPath = $derived.by(() => {
	// 	const pct = Math.min(threatScore / 100, 1);
	// 	const angle = pct * 180;
	// 	const rad = (angle * Math.PI) / 180;
	// 	const endX = 90 - 75 * Math.cos(rad);
	// 	const endY = 90 - 75 * Math.sin(rad);
	// 	const largeArc = angle > 180 ? 1 : 0;
	// 	return `M 15 90 A 75 75 0 ${largeArc} 1 ${endX} ${endY}`;
	// });
	// let threatColor = $derived(
	// 	threatLevel === 'critical' ? 'var(--sev-critical)' :
	// 	threatLevel === 'high' ? 'var(--sev-high)' :
	// 	threatLevel === 'medium' ? 'var(--sev-medium)' :
	// 	threatLevel === 'low' ? 'var(--sev-low)' : 'var(--text-muted)'
	// );
	// let categorySegments = $derived.by(() => {
	// 	if (!summary?.categories) return [];
	// 	const cats = Object.entries(summary.categories);
	// 	const total = cats.reduce((s, [, v]) => s + v.events, 0) || 1;
	// 	const colors: Record<string, string> = {
	// 		malware_c2: 'var(--red)', exfiltration: 'var(--orange)',
	// 		reconnaissance: 'var(--amber)', exploit: 'var(--purple)',
	// 		policy: 'var(--blue)', protocol_anomaly: 'var(--teal)',
	// 		informational: 'var(--text-dim)',
	// 	};
	// 	return cats
	// 		.filter(([, v]) => v.events > 0)
	// 		.map(([key, v]) => ({
	// 			key,
	// 			label: v.label,
	// 			pct: Math.max(2, (v.events / total) * 100),
	// 			color: colors[key] ?? 'var(--text-dim)',
	// 			events: v.events,
	// 			groups: v.groups,
	// 		}))
	// 		.sort((a, b) => b.pct - a.pct);
	// });
	// OLD CODE END
	let threatLevelPill = $derived(levelOf(threatLevel));
	let categoryItems = $derived(
		Object.entries(summary?.categories ?? {})
			.filter(([, v]) => v.events > 0)
			.map(([key, v]) => ({ key, label: v.label, value: v.events })),
	);
	let categoryLabel = $derived(
		`Alert events by category: ${categoryItems.map((c) => `${c.label} ${formatNumber(c.value)}`).join(', ')}`,
	);

	/** NET-228 (audit B5): no groups is "can't tell" unless current data is arriving */
	let noGroups = $derived(
		nothingFound('No alert groups need attention in this period', healthCheck.health, healthCheck.failed, "Can't tell if any alert needs attention"),
	);

	// Headline
	let headline = $derived.by(() => {
		const groups = summary?.total_groups ?? 0;
		const invCount = investigations.length;
		// OLD CODE: if (groups === 0) return 'No actionable threats detected.'; (NET-228: no sign of whether data was arriving)
		if (groups === 0) return `${noGroups.title}. ${noGroups.detail}.`;
		// OLD CODE START — I8: total_events leaves out informational alerts, so it read as everything Suricata raised
		// return `Suricata generated ${formatNumber(summary?.total_events ?? 0)} alert events. NetTap found ${invCount} investigation${invCount !== 1 ? 's' : ''}.`;
		// OLD CODE END
		const info = summary?.informational_events ?? 0;
		// OLD CODE START — NET-209: the figure now also holds context categories and blocklist hits devices did not start
		// const notCounted = info > 0 ? ` · ${formatNumber(info)} informational not counted` : '';
		// OLD CODE END
		const notCounted = info > 0 ? ` · ${formatNumber(info)} not counted` : '';
		return `${formatNumber(summary?.total_events ?? 0)} alert events need attention${notCounted}. NetTap found ${invCount} investigation${invCount !== 1 ? 's' : ''}.`;
	});

	let subheadline = $derived.by(() => {
		const parts: string[] = [];
		// OLD CODE: …`${killChains.length} active kill chain…` (NET-228, audit ALR-18: a reading of rule matches, not an attack)
		if (killChains.length > 0) parts.push(`${killChains.length} possible kill chain${killChains.length > 1 ? 's' : ''}`);
		if (beacons.length > 0) parts.push(`${beacons.length} beaconing suspect${beacons.length > 1 ? 's' : ''}`);
		const tiTotal = threatIntel?.total_indicators ?? 0;
		// OLD CODE START: if (tiTotal > 0) parts.push(`${tiTotal} threat intel indicators`); (I7: now the window's matches) OLD CODE END
		// OLD CODE: if (tiTotal > 0) parts.push(`${tiTotal} threat intel matches`); (NET-238: a capped scan's count is a floor)
		if (tiTotal > 0) parts.push(`${threatIntel?.complete === false ? 'at least ' : ''}${tiTotal} threat intel matches`);
		if (beaconPending) parts.push('Beaconing check running');
		if (beaconPartial && beacons.length === 0) parts.push('Partial beaconing scan');
		// OLD CODE: const failed = [...failedChecks].map((c) => CHECK_NAMES[c] ?? c); (NET-192 PR 3: or the background check failed)
		const failed = [...new Set([...failedChecks, ...(beaconFailed ? ['beaconing'] : [])])].map((c) => CHECK_NAMES[c] ?? c);
		if (failed.length > 0) parts.push(`Couldn't check ${failed.join(', ')}`);
		// OLD CODE START — #96: shown after loading too, as if a scan were still running
		// return parts.join(' · ') || 'Scanning network activity...';
		// OLD CODE END
		return parts.join(' · ') || 'No kill chains, beaconing or threat intel matches.';
	});

	let dnsFindings = $derived(
		(dnsAnomalies.dga_suspects?.length ?? 0) + (dnsAnomalies.tunnel_suspects?.length ?? 0) + (dnsAnomalies.nxdomain_spikes?.length ?? 0),
	);
	let invFailedText = $derived(
		`Couldn't investigate one or more critical alerts: a query failed.${investigations.length > 0 ? ` ${investigations.length} completed.` : ''}`,
	);

	// ---------------------------------------------------------------------------
	// Table rows (keys by position: the daemon can report the same pair twice)
	// ---------------------------------------------------------------------------

	type BeaconRow = BeaconSuspect & { key: number };
	let beaconRows = $derived(beacons.slice(0, BEACONS_SHOWN).map((b, key): BeaconRow => ({ ...b, key })));

	type LateralRow = LateralMovement & { key: number };
	let lateralRows = $derived(lateralMoves.slice(0, 8).map((m, key): LateralRow => ({ ...m, key })));

	interface DnsRow {
		key: string;
		kind: string;
		name: string;
		signal: string;
		signalValue: number;
		queries: number;
		queriesText: string;
	}
	let dnsRows = $derived<DnsRow[]>([
		...(dnsAnomalies.dga_suspects ?? []).slice(0, 5).map((d, i) => ({
			key: `dga-${i}`, kind: 'DGA suspect', name: d.domain, signal: `H=${d.entropy}`, signalValue: d.entropy,
			queries: d.query_count, queriesText: formatNumber(d.query_count),
		})),
		...(dnsAnomalies.tunnel_suspects ?? []).slice(0, 5).map((t, i) => ({
			key: `tunnel-${i}`, kind: 'DNS tunnelling', name: t.domain, signal: `${t.subdomain_length} chars`, signalValue: t.subdomain_length,
			queries: t.query_count, queriesText: formatNumber(t.query_count),
		})),
		...(dnsAnomalies.nxdomain_spikes ?? []).slice(0, 5).map((nx, i) => ({
			key: `nx-${i}`, kind: 'NXDOMAIN spike', name: nx.source_ip, signal: `${Math.round(nx.nxdomain_ratio * 100)}% failed`,
			signalValue: nx.nxdomain_ratio, queries: nx.total_queries,
			queriesText: `${formatNumber(nx.nxdomain_count)} / ${formatNumber(nx.total_queries)}`,
		})),
	]);

	const BEACON_COLUMNS: Column<BeaconRow>[] = [
		{ key: 'source_ip', label: 'Device', class: 'mono' },
		{ key: 'destination_ip', label: 'Server', cell: beaconServer },
		{ key: 'interval_seconds', label: 'Every', numeric: true, cell: beaconInterval },
		{ key: 'jitter_coefficient', label: 'Jitter', numeric: true, cell: beaconJitter },
		{ key: 'confidence', label: 'Confidence', numeric: true, cell: beaconConfidence },
	];
	const DNS_COLUMNS: Column<DnsRow>[] = [
		{ key: 'kind', label: 'Finding' },
		{ key: 'name', label: 'Domain or device', class: 'mono' },
		{ key: 'signal', label: 'Signal', numeric: true, sortValue: (r) => r.signalValue },
		{ key: 'queries', label: 'Queries', numeric: true, cell: dnsQueries },
	];
	const LATERAL_COLUMNS: Column<LateralRow>[] = [
		// OLD CODE START — slice 2a: the addresses weren't links
		// { key: 'source_ip', label: 'From', class: 'mono' },
		// { key: 'destination_ip', label: 'To', class: 'mono' },
		// OLD CODE END
		{ key: 'source_ip', label: 'From', class: 'mono', cell: lateralFrom },
		{ key: 'destination_ip', label: 'To', class: 'mono', cell: lateralTo },
		{ key: 'service', label: 'Service' },
		{ key: 'port', label: 'Port', numeric: true, class: 'mono' },
		// OLD CODE: { key: 'connection_count', label: 'Connections', numeric: true, cell: lateralCount }, (NET-240: a distinct count OpenSearch estimates)
		{ key: 'connection_count', label: 'Connections (approx.)', numeric: true, cell: lateralCount },
		{ key: 'fan_out', label: 'Fan-out', numeric: true },
	];

	// ---------------------------------------------------------------------------
	// Time helpers
	// ---------------------------------------------------------------------------

	// OLD CODE START — NET-196: the window ending now is rangeWindow, over the list's hours
	// function computeTimeParams(range: string): { from: string; to: string } {
	// 	const now = new Date();
	// 	let from: Date;
	// 	switch (range) {
	// 		case '1h': from = new Date(now.getTime() - 60 * 60 * 1000); break;
	// 		case '6h': from = new Date(now.getTime() - 6 * 60 * 60 * 1000); break;
	// 		case '7d': from = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000); break;
	// 		case '30d': from = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000); break;
	// 		default: from = new Date(now.getTime() - 24 * 60 * 60 * 1000); break;
	// 	}
	// 	return { from: from.toISOString(), to: now.toISOString() };
	// }
	// OLD CODE END
	/** The window ending now for a range; anything not in the list is 24 hours. */
	const computeTimeParams = (range: string) => rangeWindow(DRILL_RANGES.find((r) => r.value === range)?.hours ?? 24);

	// ---------------------------------------------------------------------------
	// Fetching
	// ---------------------------------------------------------------------------

	// OLD CODE START — the page refresh contract (PLAN §5.5): the loader reports what succeeded,
	// and a load guard drops a slower, older range's response instead of letting it overwrite
	// async function fetchAll(range: string) {
	// 	loading = true;
	// 	const params = computeTimeParams(range);
	// 	// OLD CODE START — #96: one failure blanked both; the clients now throw instead of faking zeros
	// 	// try {
	// 	// 	const [reportRes, tiRes] = await Promise.all([getThreatReport(params), getThreatIntel(params)]);
	// 	// 	report = reportRes;
	// 	// 	threatIntel = tiRes;
	// 	// 	lastUpdated = new Date();
	// 	// } catch {
	// 	// 	report = null;
	// 	// 	threatIntel = null;
	// 	// } finally {
	// 	// 	loading = false;
	// 	// }
	// 	// OLD CODE END
	// 	const [reportRes, tiRes] = await Promise.allSettled([getThreatReport(params), getThreatIntel(params)]);
	// 	report = reportRes.status === 'fulfilled' ? reportRes.value : null;
	// 	threatIntel = tiRes.status === 'fulfilled' ? tiRes.value : null;
	// 	intelFailed = tiRes.status === 'rejected';
	// 	if (report) lastUpdated = new Date();
	// 	loading = false;
	// }
	//
	// $effect(() => {
	// 	const range = selectedRange;
	// 	fetchAll(range);
	// });
	// OLD CODE END
	// NET-192 PR 3: while the background beaconing check hasn't finished, ask for its state every
	// 20 s (the beaconing route, not the whole report), for at most 10 min per range; once it has
	// finished, load the page again so the other cards and "Updated" move with it
	const POLL_MS = 20_000;
	const POLL_FOR_MS = 10 * 60_000;
	let pollTimer: ReturnType<typeof setTimeout> | undefined;
	let pendingSince = { range: '', at: 0 };

	function pollWhilePending(g: number, range: string, request: ThreatRequest) {
		clearTimeout(pollTimer);
		if (report?.beaconing_snapshot?.state !== 'pending' || !('snapshot' in request)) {
			pendingSince = { range: '', at: 0 };
			pollGaveUp = false;
			return;
		}
		if (pendingSince.range !== range) pendingSince = { range, at: Date.now() };
		pollGaveUp = Date.now() - pendingSince.at >= POLL_FOR_MS;
		if (pollGaveUp) return;
		const { snapshot } = request;
		pollTimer = setTimeout(async () => {
			const next = await getBeaconing({ snapshot }).catch(() => null);
			if (!refresh.guard.current(g)) return;
			if (next) {
				report = report && { ...report, beaconing: next.beacons, beaconing_snapshot: next.beaconing_snapshot };
				if (next.beaconing_snapshot?.state !== 'pending') {
					reload();
					return;
				}
			}
			pollWhilePending(g, range, request);
		}, POLL_MS);
	}

	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		clearTimeout(pollTimer);
		// NET-225: the score's bridge-mode line; asks again if the startup request failed, never blocks the report
		void initCaptureMode();
		const range = selectedRange;
		const params = computeTimeParams(range);
		// one window for the report and the threat intel
		const request = threatRequest(range, params);
		loading = true;
		// OLD CODE: const [reportRes, tiRes] = await Promise.allSettled([getThreatReport(params), getThreatIntel(params)]); (NET-192 PR 3: 24h/7d/30d ask for the snapshot)
		// OLD CODE: const [reportRes, tiRes] = await Promise.allSettled([getThreatReport(request), getThreatIntel(params)]); (NET-228: and the health)
		// OLD CODE: const [reportRes, tiRes, healthRes] = await Promise.allSettled([getThreatReport(request), getThreatIntel(params), getSystemHealth()]); (review L7)
		const [[reportRes, tiRes], checked] = await Promise.all([Promise.allSettled([getThreatReport(request), getThreatIntel(params)]), readHealth()]);
		if (!guard.current(g)) return 'skipped';
		report = reportRes.status === 'fulfilled' ? reportRes.value : null;
		threatIntel = tiRes.status === 'fulfilled' ? tiRes.value : null;
		intelFailed = tiRes.status === 'rejected';
		// OLD CODE: health = healthRes.status === 'fulfilled' ? healthRes.value : null; healthFailed = healthRes.status === 'rejected'; (review L7)
		healthCheck = checked;
		loading = false;
		pollWhilePending(g, range, request);
		// OLD CODE START — counted by hand; outcome() in pageRefresh is the shared rule
		// const succeeded = [reportRes, tiRes].filter((r) => r.status === 'fulfilled').length;
		// return succeeded === 2 ? 'ok' : succeeded === 1 ? 'partial' : 'failed';
		// OLD CODE END
		// OLD CODE: return outcome([reportRes, tiRes]); (NET-228)
		// OLD CODE: return outcome([reportRes, tiRes, healthRes]); (review L7)
		return outcome([reportRes, tiRes]);
	}

	const refresh = registerPageRefresh(load);
	const reload = () => refresh.run();

	onMount(() => {
		reload();
		return () => {
			clearTimeout(pollTimer);
			refresh.unregister();
		};
	});

	// ---------------------------------------------------------------------------
	// Formatters
	// ---------------------------------------------------------------------------

	// OLD CODE START — one compact format for the app (NET-192 PR 4): formatCompactNumber in $lib/api/logs
	// function formatNumber(n: number): string {
	// 	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
	// 	if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
	// 	return n.toLocaleString();
	// }
	// OLD CODE END

	// OLD CODE START — 2026-11-06 (NET-166): a copy of formatBytes in $lib/api/logs, 1024-based under decimal labels; the shared one is decimal
	// function formatBytes(bytes: number): string {
	// 	if (bytes === 0) return '0 B';
	// 	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	// 	const i = Math.floor(Math.log(bytes) / Math.log(1024));
	// 	return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
	// }
	// OLD CODE END

	// OLD CODE START — the browser's locale printed "Nov 6, 2026, 10:37 PM" (NET-192 PR 4: formatTime)
	// function formatTimestamp(ts: string): string {
	// 	if (!ts) return '--';
	// 	try {
	// 		return new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
	// 	} catch { return ts; }
	// }
	// OLD CODE END
	const formatTimestamp = (ts: string) => formatTime(ts);

	const plural = (n: number, word: string) => `${n.toLocaleString('en-GB')} ${word}${n === 1 ? '' : 's'}`;

	const LEVELS: readonly string[] = ['critical', 'high', 'medium', 'low', 'info'];
	/** "HIGH" or "high" → the SeverityPill level; anything else (such as "none") → null. */
	function levelOf(label: string | undefined): SeverityLevel | null {
		const level = (label ?? '').toLowerCase();
		return LEVELS.includes(level) ? (level as SeverityLevel) : null;
	}

	const list = (value: unknown) => (Array.isArray(value) ? value.join(', ') : String(value));

	const STAGE_NAMES: Record<number, string> = { 1: 'Reconnaissance', 2: 'Exploit', 3: 'Malware & C2', 4: 'Exfiltration' };
</script>

{#snippet beaconServer(b: BeaconRow)}<span class="mono">{b.destination_ip}:{b.destination_port}</span>{/snippet}
{#snippet beaconInterval(b: BeaconRow)}~{b.interval_seconds}s{/snippet}
{#snippet beaconJitter(b: BeaconRow)}{(b.jitter_coefficient * 100).toFixed(1)}%{/snippet}
{#snippet beaconConfidence(b: BeaconRow)}
	<span class="confidence"><Meter value={b.confidence} label="Confidence {b.confidence}%" />{b.confidence}%</span>
{/snippet}
{#snippet dnsQueries(r: DnsRow)}{r.queriesText}{/snippet}
{#snippet lateralCount(m: LateralRow)}{formatNumber(m.connection_count)}{/snippet}
{#snippet lateralFrom(m: LateralRow)}<IPAddress ip={m.source_ip} />{/snippet}
{#snippet lateralTo(m: LateralRow)}<IPAddress ip={m.destination_ip} />{/snippet}

<svelte:head>
	<title>Threats | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">Threats</h1>
		<p class="page-sub">Behavioural analysis of your network · {rangeText}</p>
	</div>
	<div class="head-actions">
		<Pills options={RANGES} bind:value={selectedRange} onchange={reload} ariaLabel="Time range" />
	</div>
</div>

{#if $captureMode === 'bridge'}
	<p class="notice" role="note"><Icon name="infra" /><span>{THREAT_SCORE_BRIDGE}</span></p>
{/if}

{#if pipelineNote}
	<p class="notice is-warn" role="status"><Icon name="warn" /><span>Data pipeline now: {pipelineNote}. What this page shows may be out of date. See <a href="/system">System</a> for details.</span></p>
{/if}

{#if !report}
	<div class="grid">
		<Card title="Threat report" sub="Kill chains, beaconing, DNS and lateral movement · {rangeText}" class="c-12">
			{#if loading}
				<CardState state="loading" title="Loading the threat report" />
			{:else}
				<CardState
					state="error"
					title="Couldn't load the threat report: the request failed."
					message="Check that NetTap is running on the System page, then try again."
					onaction={reload}
				/>
			{/if}
		</Card>
	</div>
{:else}
	<div class="grid">
		<!-- KPI row -->
		<!-- OLD CODE: sub={THREAT_SCORE_HOW} (NET-192 PR 4: a whole paragraph in a KPI; it is one click away in the foot now) -->
		<KpiCard
			class="c-3"
			label="Threat score"
			icon="threats"
			value={threatScore}
			unit="/100"
			sub="Higher is riskier · {rangeText}"
			note={baseline ? `${baseline.deviation}× ${baseline.is_anomalous ? 'above' : 'vs'} baseline` : undefined}
		>
			{#snippet foot()}
				<!-- OLD CODE: {#if threatLevelPill}<SeverityPill level={threatLevelPill} />{:else}<span class="dim">No threat level</span>{/if} (NET-228: 0 read as good news with data not arriving) -->
				{#if threatLevelPill}<SeverityPill level={threatLevelPill} />{:else if (summary?.total_groups ?? 0) === 0 && !noGroups.trusted}<span class="chip is-warn">Can't tell</span>{:else}<span class="dim">No threat level</span>{/if}
				<details class="score-how">
					<summary>How the score is worked out</summary>
					<p>{THREAT_SCORE_HOW}</p>
					<!-- NET-239: the suppressions and baseline that changed this window's score -->
					{#each scoreInputs(summary ?? {}) as line (line)}<p>{line}</p>{/each}
				</details>
			{/snippet}
		</KpiCard>
		<KpiCard
			class="c-3"
			label="Alert groups"
			icon="alerts"
			value={formatNumber(summary?.total_groups ?? 0)}
			sub="{formatNumber(summary?.total_events ?? 0)} alert events need attention · {rangeText}"
		/>
		<!-- OLD CODE: sub="Devices moving through attack stages" (NET-228, audit ALR-18) -->
		<KpiCard class="c-3" label="Kill chains" icon="warn" value={killChains.length} sub="Rule matches mapped to attack stages" />
		<!-- OLD CODE START (NET-192 PR 3: "—" too while the background check is pending or has never succeeded)
		<KpiCard
			class="c-3"
			label="Beaconing"
			icon="connections"
			value={failedChecks.has('beaconing') ? '—' : beacons.length}
			sub={failedChecks.has('beaconing') ? 'Not checked: the query failed' : 'Devices calling one server on a schedule'}
		/>
		OLD CODE END -->
		<KpiCard
			class="c-3"
			label="Beaconing"
			icon="connections"
			value={beaconFailed || beaconPending ? '—' : beacons.length}
			sub={beaconKpiSub}
		/>

		<!-- Threat brief + threat intel -->
		<Card title="Threat brief" sub="Alert events by category · {rangeText}" hero class="c-8">
			<p class="brief-headline">{headline}</p>
			<p class="brief-sub">{subheadline}</p>
			{#if categoryItems.length > 0}
				<StackBar items={categoryItems} formatValue={formatNumber} ariaLabel={categoryLabel} />
			{/if}
		</Card>

		<!-- OLD CODE START: <Card title="Threat intel matches" sub="Indicators loaded per feed · {rangeText}" class="c-4"> (I7: every cached indicator, under the window's label) OLD CODE END -->
		<Card title="Threat intel matches" sub="Listed internet addresses seen in alerts · {rangeText}" class="c-4">
			{#snippet actions()}
				<!-- OLD CODE: >{intelFailed ? 'load failed' : plural(threatIntel?.total_indicators ?? 0, 'indicator')}</span (NET-238: a capped scan's count is a floor) -->
				<span class={['chip', (threatIntel?.total_indicators ?? 0) > 0 && 'is-warn']}
					>{intelFailed
						? 'load failed'
						: `${threatIntel?.complete === false ? 'at least ' : ''}${plural(threatIntel?.total_indicators ?? 0, 'indicator')}`}</span
				>
			{/snippet}
			{#if threatIntel?.complete === false}
				<p class="notice is-warn" role="status">
					<Icon name="warn" /><span
						>Stopped after checking the first {fmt(SCAN_CAP)} alert address pairs, in address order, not the busiest; more exist, so this list may be missing some.</span
					>
				</p>
			{/if}
			<!-- OLD CODE START — I7: cached indicators "loaded", and a bare request-failed state
			{#if threatIntel && Object.keys(threatIntel.feeds).length > 0}
				<BarList
					items={Object.entries(threatIntel.feeds).map(([feedId, feed]) => ({
						key: feedId,
						label: feed.label,
						value: feed.indicator_count,
						display: feed.indicator_count.toLocaleString('en-GB'),
						detail: 'loaded',
					}))}
				/>
			{:else if intelFailed}
				<CardState state="error" title="Couldn't load threat intel: the request failed." onaction={reload} />
			{:else}
				<CardState
					state="empty"
					title="No threat intel indicators loaded"
					message="Feeds populate from Suricata detections."
					icon="threats"
				/>
			{/if}
			OLD CODE END -->
			{#if threatIntel && threatIntel.total_indicators > 0}
				<BarList
					items={Object.entries(threatIntel.feeds)
						.filter(([, feed]) => feed.indicator_count > 0)
						.map(([feedId, feed]) => ({
							key: feedId,
							label: feed.label,
							value: feed.indicator_count,
							display: feed.indicator_count.toLocaleString('en-GB'),
							detail: 'seen',
						}))}
				/>
			{:else if intelFailed}
				<CardState state="error" title="Threat intel unavailable" message="Couldn't load threat intel: the request failed." onaction={reload} />
			{:else}
				<CardState
					state="empty"
					title="No threat intel matches"
					message="Matches are internet addresses on Suricata's blocklist rules seen in this window."
					icon="threats"
				/>
			{/if}
		</Card>

		<!-- Active kill chains -->
		<!-- OLD CODE: <Card title="Active kill chains" sub="Devices seen at more than one attack stage · {rangeText}"> … {killChains.length} detected (NET-228, audit ALR-18: stated as fact) -->
		<Card title="Possible kill chains" sub="Devices whose rule matches map to more than one attack stage, in order · {rangeText}" class="c-12">
			{#snippet actions()}
				<span class={['chip', killChains.length > 0 && 'is-warn']}>{killChains.length} found</span>
			{/snippet}
			{#if killChains.length > 0}
				<div class="kill-chains">
					{#each killChains as kc, i (`${kc.source_ip}-${i}`)}
						<section class="kill-chain">
							<div class="kc-head">
								<span class="mono kc-ip">{kc.source_ip}</span>
								<span class="chip is-warn">{kc.stages.length}-stage chain</span>
							</div>
							<ol class="chips kc-stages">
								{#each [1, 2, 3, 4] as stage (stage)}
									<li class={['chip', kc.stages.includes(stage) && 'is-warn']}>
										<!-- OLD CODE: … {kc.stages.includes(stage) ? 'Detected' : 'Not seen'} (NET-228: a stage is a rule match; one outside this chain's order can exist) -->
										Stage {stage} · {STAGE_NAMES[stage]} · {kc.stages.includes(stage) ? 'Rule matched' : 'Not in this chain'}
									</li>
								{/each}
							</ol>
							<p class="kc-text">{kc.assessment}</p>
							<div class="actions">
								<!-- OLD CODE START — NET-209: an internet source has no device page; ipHref picks device or address
								onclick={() => goto(`/devices/${encodeURIComponent(kc.source_ip)}`)}
								OLD CODE END -->
								<button class="btn primary" type="button" onclick={() => goto($ipHref(kc.source_ip))}>Investigate device</button>
								<button class="btn" type="button" onclick={() => goto(`/connections?ip=${encodeURIComponent(kc.source_ip)}`)}>View connections</button>
							</div>
						</section>
					{/each}
				</div>
			{:else}
				<!-- OLD CODE: title="No active kill chains" message="A kill chain appears when one device shows several attack stages, such as scanning and then contacting a control server." (NET-228, audit ALR-18) -->
				<CardState
					state="empty"
					title="No possible kill chains"
					message="A kill chain appears when one device's rule matches map to several attack stages in order, such as a scanning rule and then a control-server rule. Each stage is NetTap's reading of a rule match."
					icon="threats"
				/>
			{/if}
		</Card>

		<!-- Beaconing -->
		<!-- OLD CODE START (NET-192 PR 3: the background check's state: pending, stale, failed; and a live partial scan)
		<Card title="Beaconing" sub="Connections repeated on a schedule · {rangeText}" class="c-6">
			{#snippet actions()}
				<span class={['chip', beacons.length > 0 && 'is-warn']}
					>{failedChecks.has('beaconing') ? 'check failed' : plural(beacons.length, 'suspect')}</span
				>
			{/snippet}
			{#if failedChecks.has('beaconing')}
				<CardState state="error" title="Couldn't check for beaconing: the query failed." onaction={reload} />
			{:else if beacons.length > 0}
				<DataTable columns={BEACON_COLUMNS} rows={beaconRows} ariaLabel="Beaconing suspects" rowKey={(b) => b.key} />
				{#if beacons.length > BEACONS_SHOWN}
					<p class="note">Showing the {BEACONS_SHOWN} most confident of {beacons.length.toLocaleString('en-US')} suspects.</p>
				{/if}
			{:else}
				<CardState
					state="empty"
					title="No beaconing patterns detected."
					message="A device that calls the same server at a steady interval appears here."
					icon="connections"
				/>
			{/if}
			{#if !failedChecks.has('beaconing')}
				{#each manyHostSources as m (m.ip)}
					<p class="note">(the many-hosts note, unchanged below)</p>
				{/each}
			{/if}
			{#if incompleteChecks.has('beaconing')}
				<p class="note">Not every connection pair was checked: this window has more than the scan's limit.</p>
			{/if}
		</Card>
		OLD CODE END -->
		<Card
			title="Beaconing"
			sub="Connections repeated on a schedule · {rangeText}{beaconCheckedAt ? ` · checked ${beaconCheckedAt}` : ''}"
			class="c-6"
		>
			{#snippet actions()}
				<span class={['chip', beacons.length > 0 && 'is-warn']}
					>{beaconFailed ? 'check failed' : beaconPending ? 'checking…' : plural(beacons.length, 'suspect')}</span
				>
			{/snippet}
			{#if beaconFailed}
				<CardState state="error" title="Couldn't check for beaconing: {beaconFailReason}." onaction={reload} />
			{:else if beaconPending}
				<p class="note" aria-hidden="true">{beaconPendingText}</p>
				<CardState state="loading" title={beaconPendingText} />
			{:else}
				{#if beaconSnap?.state === 'stale'}
					<p class="notice is-warn" role="status">
						<Icon name="warn" /><span
							>Last checked {beaconCheckedAt};
							{beaconSnap.last_error ? 'the latest check failed.' : "a newer check hasn't finished yet."}</span
						>
					</p>
				{/if}
				{#if beaconPartial}
					<p class="notice is-warn" role="status">
						<Icon name="warn" /><span>Partial scan: not every connection pair was checked, because this window has more than the scan's limit.</span>
					</p>
				{/if}
				{#if beacons.length > 0}
					<DataTable columns={BEACON_COLUMNS} rows={beaconRows} ariaLabel="Beaconing suspects" rowKey={(b) => b.key} />
					{#if beacons.length > BEACONS_SHOWN}
						<p class="note">Showing the {BEACONS_SHOWN} most confident of {beacons.length.toLocaleString('en-US')} suspects.</p>
					{/if}
				{:else if !beaconPartial}
					<CardState
						state="empty"
						title="No beaconing patterns detected."
						message="A device that calls the same server at a steady interval appears here."
						icon="connections"
					/>
				{/if}
			{/if}
			{#if !beaconFailed && !beaconPending}
				{#each manyHostSources as m (m.ip)}
					<p class="note">
						<span class="mono">{m.ip}</span> contacts {m.hosts.toLocaleString('en-US')} internet hosts on regular schedules.
						Malware usually calls one or a few servers; this many usually means peer-to-peer software (such as BitTorrent)
						or a device syncing with many services, so these aren't counted as suspects.
					</p>
				{/each}
			{/if}
		</Card>

		<!-- DNS anomalies -->
		<Card title="DNS anomalies" sub="Up to 5 of each finding · {rangeText}" class="c-6">
			{#snippet actions()}
				<span class={['chip', (dnsAnomalies.dga_suspects?.length ?? 0) + (dnsAnomalies.nxdomain_spikes?.length ?? 0) > 0 && 'is-warn']}
					>{failedChecks.has('dns_anomalies') ? 'check failed' : plural(dnsFindings, 'finding')}</span
				>
			{/snippet}
			{#if failedChecks.has('dns_anomalies')}
				<CardState state="error" title="Couldn't check for DNS anomalies: the query failed." onaction={reload} />
			{:else if dnsRows.length > 0}
				<DataTable columns={DNS_COLUMNS} rows={dnsRows} ariaLabel="DNS anomalies" rowKey={(r) => r.key} />
			{:else}
				<CardState
					state="empty"
					title="No DNS anomalies detected."
					message="Lookups that look machine-generated, tunnelled or mostly failing appear here."
					icon="dns"
				/>
			{/if}
			{#if incompleteChecks.has('dns_anomalies')}
				<p class="note">Not every domain or client was checked: this window has more than the scan's limit.</p>
			{/if}
		</Card>

		<!-- Lateral movement -->
		<Card title="Lateral movement" sub="Device-to-device connections on admin services, top 8 · {rangeText}" class="c-12">
			{#snippet actions()}
				<span class="chip">{failedChecks.has('lateral_movement') ? 'check failed' : plural(lateralMoves.length, 'internal path')}</span>
			{/snippet}
			{#if failedChecks.has('lateral_movement')}
				<CardState state="error" title="Couldn't check for lateral movement: the query failed." onaction={reload} />
			{:else if lateralMoves.length > 0}
				<DataTable columns={LATERAL_COLUMNS} rows={lateralRows} ariaLabel="Lateral movement" rowKey={(m) => m.key} />
			{:else}
				<CardState
					state="empty"
					title="No lateral movement detected."
					message="Connections between your own devices on services such as SMB or SSH appear here."
					icon="devices"
				/>
			{/if}
			{#if incompleteChecks.has('lateral_movement')}
				<p class="note">Not every connection pair was checked: this window has more than the scan's limit.</p>
			{/if}
		</Card>

		<!-- Auto-investigations -->
		<Card title="Auto-investigations" sub="Context gathered for critical alerts · {rangeText}" class="c-12">
			{#snippet actions()}
				<span class="chip">{failedChecks.has('investigations') ? 'check failed' : `${investigations.length} completed`}</span>
			{/snippet}
			{#if failedChecks.has('investigations') && investigations.length === 0}
				<CardState state="error" title={invFailedText} onaction={reload} />
			{:else if investigations.length === 0}
				<CardState
					state="empty"
					title="No auto-investigations"
					message="NetTap investigates critical alerts on its own and shows what it found here."
					icon="search"
				/>
			{:else}
				{#if failedChecks.has('investigations')}
					<p class="notice is-error"><Icon name="warn" />{invFailedText}</p>
				{/if}
				<ul class="inv-list">
					{#each investigations as inv, i (`inv-${i}`)}
						<li class="inv">
							<button
								class="inv-head"
								type="button"
								aria-expanded={expandedInvestigation === i}
								onclick={() => (expandedInvestigation = expandedInvestigation === i ? null : i)}
							>
								<SeverityPill level={levelOf(inv.alert.severity_label) ?? 'info'} />
								<span class="inv-main">
									<span class="inv-title">{inv.alert.signature}</span>
									<span class="mono dim">{inv.alert.source_ip} → {inv.alert.destination_ip}</span>
								</span>
								<Icon name="chevdown" class={expandedInvestigation === i ? 'inv-chev open' : 'inv-chev'} />
							</button>
							{#if expandedInvestigation === i}
								<div class="inv-body">
									{#if inv.sections.source_profile}
										{@const p = inv.sections.source_profile}
										<section>
											<h4 class="eyebrow">Source host profile</h4>
											<dl class="facts">
												<dt>IP</dt><dd class="mono">{p.ip}</dd>
												<!-- OLD CODE START (I14: the daemon counts only connections this host started, and the bytes it sent in them)
												<dt>Connections (24h)</dt><dd class="num">{formatNumber(Number(p.connection_count_24h) || 0)}</dd>
												<dt>Unique destinations</dt><dd class="num">{Number(p.unique_destinations) || 0}</dd>
												<dt>Bytes (24h)</dt><dd class="num">{formatBytes(Number(p.total_bytes_24h) || 0)}</dd>
												OLD CODE END -->
												<dt>Connections it started (24h)</dt><dd class="num">{formatNumber(Number(p.connection_count_24h) || 0)}</dd>
												<dt>Unique destinations</dt><dd class="num">{Number(p.unique_destinations) || 0}</dd>
												<dt>Bytes it sent in them (24h)</dt><dd class="num">{formatBytes(Number(p.total_bytes_24h) || 0)}</dd>
												{#if p.protocols}<dt>Protocols</dt><dd class="mono">{list(p.protocols)}</dd>{/if}
												{#if p.top_ports}<dt>Top ports</dt><dd class="mono">{list(p.top_ports)}</dd>{/if}
											</dl>
										</section>
									{/if}
									{#if inv.sections.destination_profile}
										{@const p = inv.sections.destination_profile}
										<section>
											<h4 class="eyebrow">Destination host profile</h4>
											<dl class="facts">
												<dt>IP</dt><dd class="mono">{p.ip}</dd>
												<!-- OLD CODE START (I14: the daemon counts only connections this host started, and the bytes it sent in them)
												<dt>Connections (24h)</dt><dd class="num">{formatNumber(Number(p.connection_count_24h) || 0)}</dd>
												<dt>Unique destinations</dt><dd class="num">{Number(p.unique_destinations) || 0}</dd>
												<dt>Bytes (24h)</dt><dd class="num">{formatBytes(Number(p.total_bytes_24h) || 0)}</dd>
												OLD CODE END -->
												<dt>Connections it started (24h)</dt><dd class="num">{formatNumber(Number(p.connection_count_24h) || 0)}</dd>
												<dt>Unique destinations</dt><dd class="num">{Number(p.unique_destinations) || 0}</dd>
												<dt>Bytes it sent in them (24h)</dt><dd class="num">{formatBytes(Number(p.total_bytes_24h) || 0)}</dd>
											</dl>
										</section>
									{/if}
									{#if inv.sections.connection_history}
										{@const h = inv.sections.connection_history}
										<section>
											<h4 class="eyebrow">Connection history (7d)</h4>
											<dl class="facts">
												<dt>Total connections</dt><dd class="num">{formatNumber(Number(h.total_connections_7d) || 0)}</dd>
												<dt>Total bytes</dt><dd class="num">{formatBytes(Number(h.total_bytes_7d) || 0)}</dd>
												<dt>First seen</dt><dd>{formatTimestamp(String(h.first_seen ?? ''))}</dd>
												<dt>Last seen</dt><dd>{formatTimestamp(String(h.last_seen ?? ''))}</dd>
											</dl>
										</section>
									{/if}
									<div class="todo inv-todo"><b>What to do</b>{inv.recommendation}</div>
								</div>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</Card>
	</div>
{/if}

<style>
	/* Layout glue the system lacks */
	.brief-headline { font: 500 var(--text-lg)/1.3 var(--font-display); color: var(--text-1); text-wrap: balance; }
	.brief-sub { margin: var(--sp-1) 0 var(--sp-4); color: var(--text-2); font-size: var(--text-sm); }
	.note { margin-top: var(--sp-3); color: var(--text-3); font-size: var(--text-xs); }
	.notice { margin-bottom: var(--sp-3); }
	.confidence { display: inline-grid; grid-template-columns: 60px auto; gap: var(--sp-2); align-items: center; }

	.kill-chains { display: flex; flex-direction: column; gap: var(--sp-4); }
	.kill-chain + .kill-chain { border-top: 1px solid var(--line); padding-top: var(--sp-4); }
	.kc-head { display: flex; align-items: center; gap: var(--sp-3); margin-bottom: var(--sp-3); }
	.kc-ip { font-size: var(--text-md); font-weight: 600; color: var(--text-1); }
	.kc-stages { list-style: none; margin: 0 0 var(--sp-3); padding: 0; }
	.kc-text { margin-bottom: var(--sp-3); color: var(--text-2); font-size: var(--text-sm); }

	.inv-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--sp-2); }
	.inv { border: 1px solid var(--line); border-radius: var(--r-md); }
	.inv-head {
		width: 100%; display: grid; grid-template-columns: auto minmax(0, 1fr) 16px; gap: var(--sp-3); align-items: center;
		padding: var(--sp-3); border: 0; border-radius: var(--r-md); background: none; color: var(--text-1);
		text-align: left; cursor: pointer; font: inherit;
	}
	.inv-head:hover { background: var(--row-hover); }
	.inv-main { display: flex; flex-direction: column; min-width: 0; font-size: var(--text-sm); }
	.inv-title { font-weight: 700; overflow-wrap: anywhere; }
	.inv-head :global(.inv-chev) { width: 16px; height: 16px; color: var(--text-3); transition: transform var(--dur-fast); }
	.inv-head :global(.inv-chev.open) { transform: rotate(180deg); }
	.inv-body {
		display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: var(--sp-5);
		padding: var(--sp-4); border-top: 1px solid var(--line);
	}
	.inv-body .eyebrow { margin-bottom: var(--sp-2); }
	/* system.css breaks .facts values anywhere; in these three narrow columns an IP split mid-address (NET-192).
	   break-word keeps a value whole and breaks it only when it can't fit a line on its own. */
	.inv-body .facts dd { overflow-wrap: break-word; }
	.inv-todo { grid-column: 1 / -1; }

	@media (prefers-reduced-motion: reduce) {
		.inv-head :global(.inv-chev) { transition: none; }
	}
	/* NET-192 PR 4: the threat score's explanation, under its level */
	.score-how { margin-top: var(--sp-2); font-size: var(--text-xs); color: var(--text-3); }
	.score-how summary { cursor: pointer; color: var(--text-2); }
	.score-how p { margin: var(--sp-2) 0 0; }
</style>
