<script lang="ts">
	/**
	 * Device Intelligence Dashboard v2
	 *
	 * Sections:
	 *   1. Identity hero (device tile, name, chips, facts, time range)
	 *   2. KPIs (traffic, upload share, connections, alerts)
	 *   3. Bandwidth over time + risk score ring with its factors
	 *   4. Smart alerts, traffic categories and top services
	 *   5. Network detail (top destinations, DNS activity, top ports)
	 *   6. Recent connections (protocol filter, server-sorted, rows open a drawer)
	 */

	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { onDestroy, untrack } from 'svelte';
	import IPAddress from '$components/IPAddress.svelte';
	import { domainHref, lanPolicy, lanStatus } from '$lib/stores/lan';
	import ConnectionDrawer from '$components/ConnectionDrawer.svelte';
	import {
		getDeviceDetail,
		getDeviceConnections,
		getDeviceCategories,
		getDevicePorts,
		getDeviceRiskScore,
	} from '$api/devices';
	import { getSmartAlerts, suppressAlert } from '$api/alerts';
	// OLD CODE: import { getSystemHealth, nothingFound, type SystemHealth } from '$api/system'; (review L7)
	import { nothingFound } from '$api/system';
	import { HEALTH_CHECKING, readHealth, type HealthCheck } from '$lib/utils/read-health';
	import { loadFailed } from '$lib/utils/load-failed';
	import { likelyType, osBasis, typeBasis } from '$lib/utils/device-guess';
	import { ipv6LeftOutText } from '$lib/utils/ipv6-coverage';
	import { formatBytes, formatCompactNumber as formatNumber } from '$lib/api/logs';
	import { TableSort } from '$lib/utils/table-sort.svelte';
	import { connectionDurationMs } from '$lib/utils/connection-duration';
	import { smartLevel, type SeverityLevel } from '$lib/utils/severity';
	// OLD CODE: import { alertsHrefForSignature, logsHrefForQuery, type DrillWindow } from '$lib/utils/drilldown'; (slice 2b-1: smart alerts link by their key)
	import { chartTime as timeLabel, DRILL_RANGES, logsHrefForQuery, NO_EXACT_ALERT_LIST, rangeWindow, smartAlertHref, startRange, withCount, type DrillRangeValue, type DrillWindow } from '$lib/utils/drilldown';
	import { formatTime } from '$lib/utils/time';
	import { registerPageRefresh, outcome, createLoadGuard, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import type { DeviceConnectionSort } from '$api/devices';
	import type { SmartAlert } from '$api/alerts';
	import type { RegistryDevice } from '$api/devices-registry';
	import DeviceCustomise from '$components/DeviceCustomise.svelte';
	import LiveBandwidthCard from '$components/LiveBandwidthCard.svelte';
	import type {
		DeviceDetail,
		DeviceConnection,
		DeviceCategory,
		DeviceDestination,
		DeviceDNSQuery,
		DevicePort,
		// DeviceAlert removed — using SmartAlert from alerts.ts instead
		RiskFactor,
	} from '$api/devices';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import BarList from '$lib/components/ui/BarList.svelte';
	import Meter from '$lib/components/ui/Meter.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import DeviceTile from '$lib/components/ui/DeviceTile.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { ENCRYPTED_DNS_NOTE } from '$lib/api/dns';
	import { captureMode, initCaptureMode } from '$lib/stores/captureMode';
	import AutoRefreshButton from '$lib/components/ui/AutoRefreshButton.svelte';
	import AreaChart, { type AreaSeries } from '$lib/components/ui/charts/AreaChart.svelte';
	import Ring from '$lib/components/ui/charts/Ring.svelte';

	// OLD CODE START — 2026-11-03 UI redesign: emoji by OS; the tile shows the device type's system icon
	// const DEVICE_ICONS: Record<string, string> = {
	// 	ios: '\u{1F4F1}', android: '\u{1F4F1}', windows: '\u{1F4BB}', macos: '\u{1F4BB}',
	// 	linux: '\u{1F5A5}', chromeos: '\u{1F4BB}', default: '\u{1F4E1}',
	// };
	// OLD CODE END

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let deviceIp = $derived(decodeURIComponent(($page.params as Record<string, string>).ip ?? ''));

	// Core data
	let loading = $state(true);
	let device = $state<DeviceDetail | null>(null);
	let categories = $state<DeviceCategory[]>([]);
	let smartAlerts = $state<SmartAlert[]>([]);
	let smartAlertsTotal = $state(0);
	let smartAlertsFailed = $state(false);
	/** NET-228: the system health, for the pipeline state beside an empty alert list; null until it loads or when it failed */
	// OLD CODE: let health = $state<SystemHealth | null>(null); let healthFailed = $state(false); (review L7: one health helper for the loaders; its failure marks only the lines that read it)
	let healthCheck = $state<HealthCheck>(HEALTH_CHECKING);
	// groups, not rule matches: suppressed and context groups are left out of this list
	const noGroups = $derived(
		nothingFound('No alert groups to review for this device in this period', healthCheck.health, healthCheck.failed, "Can't tell if this device has any alert to review"),
	);
	let alertsExpanded = $state(false);
	const ALERTS_COLLAPSED_COUNT = 3;
	// OLD CODE START — review L10: shown under every chart, and "count twice … counts once" read as a contradiction
	// // NET-226 follow-up: a router on one cable passes a routed flow twice; Zeek keeps one record with both legs' bytes
	// const INTER_VLAN_NOTE =
	// 	'Traffic your router routes between two of your VLANs can be seen on both, so its bytes count twice here; each connection counts once.';
	// OLD CODE END
	/** A router on one cable passes a routed flow twice, and Zeek keeps one record with both legs' bytes. */
	function interVlanNote(n: number): string {
		return `${formatNumber(n)} of its connections ${n === 1 ? 'was' : 'were'} with another of your subnets. If your router carries that traffic over the link NetTap watches, NetTap sees both legs of each one, so their bytes count twice in these figures.`;
	}
	let suppressFailedId = $state<number | null>(null);

	// Remove the row only once the daemon confirms; suppressAlert throws on failure
	async function suppressSmartAlert(sa: SmartAlert) {
		try {
			await suppressAlert(sa.signature_id, deviceIp);
			smartAlerts = smartAlerts.filter((a) => a !== sa);
			suppressFailedId = null;
		} catch {
			suppressFailedId = sa.signature_id;
		}
	}
	let ports = $state<DevicePort[]>([]);
	/** NET-160 slice 2a: the device, window and range the ports and smart alerts on screen were counted over (set when each lands, so an in-flight refresh can't move a link) */
	type CountWindow = DrillWindow & { ip: string; range: RangeKey };
	let portsWindow = $state<CountWindow | null>(null);
	let smartAlertsWindow = $state<CountWindow | null>(null);
	let riskScore = $state(0);
	let riskLevel = $state('low');
	let riskFactors = $state<RiskFactor[]>([]);

	// #96: a failed section says so instead of "No ... data", a risk of 0 LOW, or "Device not found"
	let deviceFailed = $state(false);
	let categoriesFailed = $state(false);
	let portsFailed = $state(false);
	let riskFailed = $state(false);
	/** a risk score has loaded for this device and range (riskScore 0 is otherwise a placeholder) */
	let riskLoaded = $state(false);
	let connectionsFailed = $state(false);
	/** ip|range of the figures on screen (not reactive: only the loader reads it) */
	let loadedView = '';

	// NET-201: Rename and Change picture, as on the MAC page. Saves are kept per MAC, so a detail
	// read before a save (a refresh, a range change) gets the save laid over it, not the old name.
	/** Bumped by every finished save; a load remembers the value it began at. */
	let editRev = 0;
	/** The last finished save per MAC (lower case), with the editRev it got. */
	const edits = new Map<string, { rev: number; saved: RegistryDevice }>();
	/** MACs (lower case) with a save still running: one at a time, even when a range change remounts the panel. */
	const savingMacs = new Set<string>();

	/** The detail with one save's owner fields, shaped as the daemon's present() shapes an IP row. */
	function withOwner(d: DeviceDetail, saved: RegistryDevice): DeviceDetail {
		// the name the network gives it: the hostname, unless an owner's name already replaced it
		const original = d.custom_name ? (d.discovered_name ?? null) : d.hostname;
		return {
			...d,
			custom_name: saved.custom_name ?? null,
			icon: saved.icon ?? null,
			picture: saved.picture ?? null,
			hostname: saved.custom_name ?? original,
			discovered_name: saved.custom_name ? original : undefined,
		};
	}

	/** Run one name or picture save for the device on screen; a failure throws to DeviceCustomise. */
	async function customise(action: (mac: string) => Promise<RegistryDevice>): Promise<void> {
		const mac = device?.mac;
		if (!mac) throw new Error('This page is still loading the device. Try again in a moment.');
		const key = mac.toLowerCase();
		if (savingMacs.has(key)) throw new Error('A change to this device is still saving. Try again in a moment.');
		savingMacs.add(key);
		try {
			const saved = await action(mac);
			editRev += 1;
			edits.set(key, { rev: editRev, saved });
			if (device?.mac?.toLowerCase() === key) device = withOwner(device, saved);
		} finally {
			savingMacs.delete(key);
		}
	}

	// OLD CODE START — 2026-11-03 UI redesign: these wrappers wrote their failure flags after an await,
	// outside the load guard; the loader now settles every request and writes only while current
	// async function getDeviceCategories(ip: string, s: { from: string; to: string }): Promise<{ categories: DeviceCategory[] }> {
	// 	try {
	// 		const res = await fetchDeviceCategories(ip, s);
	// 		categoriesFailed = false;
	// 		return res;
	// 	} catch {
	// 		categoriesFailed = true;
	// 		return { categories };
	// 	}
	// }
	// async function getDevicePorts(ip: string, s: { from: string; to: string }): Promise<{ ports: DevicePort[] }> {
	// 	try {
	// 		const res = await fetchDevicePorts(ip, s);
	// 		portsFailed = false;
	// 		return res;
	// 	} catch {
	// 		portsFailed = true;
	// 		return { ports };
	// 	}
	// }
	// OLD CODE END

	// Connections
	let connections = $state<DeviceConnection[]>([]);
	let connectionsLoading = $state(false);
	let connectionsPage = $state(1);
	let connectionsTotalPages = $state(0);
	let connectionsTotal = $state(0);
	const connectionsPageSize = 25;
	let protoFilter = $state('all');
	const PROTO_OPTIONS = ['all', 'tcp', 'udp', 'icmp'].map((p) => ({ value: p, label: p === 'all' ? 'All' : p.toUpperCase() }));

	// UI state
	let autoRefresh = $state(false);

	// #87: the range pills had no handlers, so every request used the daemon's 24 h default
	// OLD CODE: const RANGE_HOURS = { '24h': 24, '7d': 168, '30d': 720 } as const; (NET-192 PR 4: Home's five ranges)
	// OLD CODE START — NET-196: the app's one list (DRILL_RANGES) and lookups in it
	// const RANGE_HOURS = { '1h': 1, '6h': 6, '24h': 24, '7d': 168, '30d': 720 } as const;
	// type RangeKey = keyof typeof RANGE_HOURS;
	// const RANGE_KEYS = Object.keys(RANGE_HOURS) as RangeKey[];
	// const RANGE_OPTIONS = RANGE_KEYS.map((key) => ({ value: key, label: key }));
	// // OLD CODE: const RANGE_LABEL: Record<RangeKey, string> = { '24h': 'Last 24 hours', '7d': 'Last 7 days', '30d': 'Last 30 days' }; (NET-192 PR 4)
	// const RANGE_LABEL: Record<RangeKey, string> = { '1h': 'Last hour', '6h': 'Last 6 hours', '24h': 'Last 24 hours', '7d': 'Last 7 days', '30d': 'Last 30 days' };
	// OLD CODE END
	type RangeKey = DrillRangeValue;
	const RANGE_OPTIONS = DRILL_RANGES.map((r) => ({ value: r.value, label: r.label }));
	const rangeOf = (key: RangeKey) => DRILL_RANGES.find((r) => r.value === key)!;
	/** The window as a KPI note says it ("Last 7 days"); card subtitles use the list's lower-case words. */
	const RANGE_LABEL = Object.fromEntries(DRILL_RANGES.map((r) => [r.value, r.words.charAt(0).toUpperCase() + r.words.slice(1)])) as Record<RangeKey, string>;
	// OLD CODE: let range = $state<RangeKey>('24h'); (NET-195: Settings › Display's default, read where the range starts)
	let range = $state<RangeKey>(startRange('24h'));
	// The window of the last fetch; connection pages reuse it so paging doesn't slide in time
	let span = $state<{ from: string; to: string }>({ from: '', to: '' });

	// OLD CODE START — NET-196: the window ending now is rangeWindow, over the list's hours
	// function rangeSpan(key: RangeKey): { from: string; to: string } {
	// 	const to = new Date();
	// 	const from = new Date(to.getTime() - RANGE_HOURS[key] * 3_600_000);
	// 	return { from: from.toISOString(), to: to.toISOString() };
	// }
	// OLD CODE END
	const rangeSpan = (key: RangeKey) => rangeWindow(rangeOf(key).hours);
	let selectedConnection = $state<Record<string, unknown> | null>(null);
	let drawerOpen = $state(false);

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	let isOnline = $derived(device?.last_seen ? (Date.now() - new Date(device.last_seen).getTime()) < 5 * 60 * 1000 : false);
	let statusLabel = $derived(isOnline ? 'Online' : device?.last_seen ? (Date.now() - new Date(device.last_seen).getTime() < 60 * 60 * 1000 ? 'Idle' : 'Offline') : 'Unknown');

	// OLD CODE START — NET-226: the originator's bytes, on connections the device started only
	// let origBytes = $derived(device?.orig_bytes ?? 0);
	// let respBytes = $derived(device?.resp_bytes ?? 0);
	// OLD CODE END
	let uploadBytes = $derived(device?.upload_bytes ?? 0);
	let downloadBytes = $derived(device?.download_bytes ?? 0);
	let totalBytes = $derived(device?.total_bytes ?? 0);
	let uploadRatio = $derived(totalBytes > 0 ? Math.round((uploadBytes / totalBytes) * 100) : 0);
	// OLD CODE START — 2026-11-03 UI redesign: green/amber/red text; colour is reserved for data and severity
	// let uploadRatioColor = $derived(uploadRatio < 40 ? 'var(--green)' : uploadRatio < 70 ? 'var(--amber)' : 'var(--red)');
	// OLD CODE END
	// OLD CODE START — NET-158: "Normal" up to 40% while the risk factor (risk_scoring.py) calls
	// 10% slightly elevated and 30% elevated
	// let uploadRatioLabel = $derived(uploadRatio < 40 ? 'Normal' : uploadRatio < 70 ? 'Elevated' : 'High');
	// OLD CODE END
	// OLD CODE: const uploadShare = $derived(totalBytes > 0 ? origBytes / totalBytes : 0); (NET-226)
	const uploadShare = $derived(totalBytes > 0 ? uploadBytes / totalBytes : 0);
	// OLD CODE START — NET-209: risk words on the data exfiltration factor's thresholds; that factor is gone
	// // the data exfiltration factor's thresholds on the unrounded share, so the KPI and the risk card agree
	// let uploadRatioLabel = $derived(uploadShare < 0.1 ? 'Normal' : uploadShare < 0.3 ? 'Slightly elevated' : uploadShare < 0.5 ? 'Elevated' : 'High');
	// OLD CODE END
	// NET-209: the share describes the traffic; it no longer scores, so it gets no risk word
	let uploadRatioLabel = $derived(uploadShare < 0.35 ? 'Mostly download' : uploadShare < 0.65 ? 'Balanced' : 'Mostly upload');

	// OLD CODE START — 2026-11-03 UI redesign: TimeSeriesChart / DualSeriesChart data; the AreaChart takes series
	// let chartData = $derived(device?.bandwidth_series?.map((p) => ({ time: p.timestamp, value: p.bytes })) ?? []);
	// let dualChartData = $derived(
	// 	device?.bandwidth_series?.map((p) => ({ time: p.timestamp, download: p.download_bytes ?? p.bytes, upload: p.upload_bytes ?? 0 })) ?? [],
	// );
	// OLD CODE END
	const bandwidth = $derived(device?.bandwidth_series ?? []);

	// Dual-series chart data (DL/UL split)
	let hasDualSeries = $derived(
		device?.bandwidth_series?.some((p) => p.download_bytes != null) ?? false,
	);

	const chartSeries = $derived.by((): AreaSeries[] =>
		hasDualSeries
			? [
					{ key: 'down', label: 'Download', colour: 1, points: bandwidth.map((p) => ({ t: p.timestamp, v: p.download_bytes ?? p.bytes })) },
					{ key: 'up', label: 'Upload', colour: 2, points: bandwidth.map((p) => ({ t: p.timestamp, v: p.upload_bytes ?? 0 })) },
				]
			: [{ key: 'total', label: 'Traffic', colour: 1, points: bandwidth.map((p) => ({ t: p.timestamp, v: p.bytes })) }],
	);
	// the busiest bucket, marked on the chart and named in its label
	const busiest = $derived(bandwidth.reduce((best, p, i) => (p.bytes > (bandwidth[best]?.bytes ?? -1) ? i : best), -1));

	// OLD CODE START — 2026-11-03 UI redesign: first_seen is the first record in the chosen range, so every
	// device read NEW in the 24 h view; the badge is gone and the fact says "in range"
	// let isNewDevice = $derived(device?.first_seen ? (Date.now() - new Date(device.first_seen).getTime()) < 24 * 60 * 60 * 1000 : false);
	// OLD CODE END

	// OLD CODE START — 2026-11-03 UI redesign: the half-circle gauge; the system's Ring draws the score
	// let riskArcPath = $derived.by(() => {
	// 	const angle = Math.min(riskScore / 100, 1) * 180;
	// 	const rad = (angle * Math.PI) / 180;
	// 	const endX = 60 - 50 * Math.cos(rad);
	// 	const endY = 65 - 50 * Math.sin(rad);
	// 	const largeArc = angle > 180 ? 1 : 0;
	// 	return `M 10 65 A 50 50 0 ${largeArc} 1 ${endX} ${endY}`;
	// });
	// let lastUpdatedText = $derived.by(() => { … });  (the top bar shows "Updated")
	// OLD CODE END

	const RISK_LEVELS: readonly string[] = ['critical', 'high', 'medium', 'low'];
	const riskSeverity = $derived(RISK_LEVELS.includes(riskLevel) ? (riskLevel as SeverityLevel) : null);

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	// OLD CODE START — 2026-11-03 UI redesign: fetchAll goes through the page refresh contract
	// (PLAN.md §5.5): it awaits the connections too, writes only while its load is current, and
	// reports ok / partial / failed. The fetch itself (same requests, same window) is unchanged.
	// async function fetchAll() {
	// 	loading = true;
	// 	span = rangeSpan(range);
	// 	const view = `${deviceIp}|${range}`;
	// 	if (view !== loadedView) { device = null; categories = []; ports = []; riskLoaded = false; }
	// 	try {
	// 		const [deviceRes, catRes, smartRes, portRes, riskRes] = await Promise.all([
	// 			getDeviceDetail(deviceIp, span).catch(() => null),
	// 			getDeviceCategories(deviceIp, span),
	// 			getSmartAlerts({ device_ip: deviceIp, limit: 10, ...span }).catch(() => null),
	// 			getDevicePorts(deviceIp, span),
	// 			getDeviceRiskScore(deviceIp, span).catch(() => null),
	// 		]);
	// 		if (deviceRes) { device = deviceRes.device; loadedView = view; }
	// 		deviceFailed = deviceRes === null;
	// 		categories = catRes.categories;
	// 		smartAlerts = smartRes?.alerts ?? [];
	// 		smartAlertsTotal = smartRes?.total ?? 0;
	// 		smartAlertsFailed = smartRes === null;
	// 		ports = portRes.ports;
	// 		if (riskRes) { riskScore = riskRes.score; riskLevel = riskRes.level; riskFactors = riskRes.factors; riskLoaded = true; }
	// 		riskFailed = riskRes === null;
	// 		if (deviceRes) lastUpdated = new Date();
	// 	} catch {
	// 		device = null;
	// 		deviceFailed = true;
	// 	} finally {
	// 		loading = false;
	// 	}
	// 	fetchConnections(1);
	// }
	// OLD CODE END
	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		// NET-225: the risk card's bridge-mode label; asks again if the startup request failed
		void initCaptureMode();
		const ip = deviceIp;
		const r = range;
		const s = rangeSpan(range);
		const view = `${ip}|${range}`;
		if (!ip) return 'skipped';
		const rev = editRev;
		loading = true;
		span = s;
		// A refresh of the same view keeps its last good figures; another view must not show them
		if (view !== loadedView) {
			device = null;
			categories = [];
			ports = [];
			riskLoaded = false;
		}
		const connectionsLoad = fetchConnections(1, s, ip);
		// OLD CODE: const results = await Promise.allSettled([ …, getSystemHealth()]); (review L7: the health beside them, outside the page's own results)
		const [results, checked] = await Promise.all([
			Promise.allSettled([
				getDeviceDetail(ip, s),
				getDeviceCategories(ip, s),
				getSmartAlerts({ device_ip: ip, limit: 10, ...s }),
				getDevicePorts(ip, s),
				getDeviceRiskScore(ip, s),
			]),
			readHealth(),
		]);
		if (!guard.current(g)) return 'skipped';
		// OLD CODE: const [deviceRes, catRes, smartRes, portRes, riskRes] = results; (NET-228: + the health)
		// OLD CODE: const [deviceRes, catRes, smartRes, portRes, riskRes, healthRes] = results; (review L7)
		const [deviceRes, catRes, smartRes, portRes, riskRes] = results;
		// OLD CODE: health = healthRes.status === 'fulfilled' ? healthRes.value : null; healthFailed = healthRes.status === 'rejected'; (review L7)
		healthCheck = checked;

		// #96: a failed detail is not "Device not found"; a refresh keeps the last one
		if (deviceRes.status === 'fulfilled') {
			// OLD CODE: device = deviceRes.value.device; (NET-201: a save that finished since this load began is laid over it)
			const d = deviceRes.value.device;
			const edit = d.mac ? edits.get(d.mac.toLowerCase()) : undefined;
			device = edit && edit.rev > rev ? withOwner(d, edit.saved) : d;
			loadedView = view;
		}
		deviceFailed = deviceRes.status === 'rejected';
		if (catRes.status === 'fulfilled') categories = catRes.value.categories;
		categoriesFailed = catRes.status === 'rejected';
		// #96: a failed alert lookup marks its card only, not the whole device page
		smartAlerts = smartRes.status === 'fulfilled' ? smartRes.value.alerts : [];
		smartAlertsTotal = smartRes.status === 'fulfilled' ? smartRes.value.total : 0;
		smartAlertsFailed = smartRes.status === 'rejected';
		smartAlertsWindow = { ...s, ip, range: r };
		// OLD CODE: if (portRes.status === 'fulfilled') ports = portRes.value.ports; (slice 2a: the ports keep the window they were counted over)
		if (portRes.status === 'fulfilled') {
			ports = portRes.value.ports;
			portsWindow = { ...s, ip, range: r };
		}
		portsFailed = portRes.status === 'rejected';
		// #96: a failed risk score never reads as 0, LOW
		if (riskRes.status === 'fulfilled') {
			riskScore = riskRes.value.score;
			riskLevel = riskRes.value.level;
			riskFactors = riskRes.value.factors;
			riskLoaded = true;
		}
		riskFailed = riskRes.status === 'rejected';
		loading = false;

		const connectionsRes = await connectionsLoad;
		if (!guard.current(g)) return 'skipped';
		return outcome([...results, connectionsRes]);
	}

	// OLD CODE START — 2026-11-03 UI redesign: the hand-built tables' sorts; DataTable sorts every column
	// const destSort = new TableSort<'ip' | 'bytes' | 'connections'>('bytes');
	// const dnsSort = new TableSort<'domain' | 'count'>('count');
	// const portSort = new TableSort<'port' | 'service' | 'connections'>('connections');
	// function sortConnections(key: DeviceConnectionSort) {
	// 	connSort.toggle(key);
	// 	fetchConnections(1);
	// }
	// OLD CODE END
	// Recent Connections sorts on the daemon, so a sort covers every page of results, not just the one shown (#140)
	const connSort = new TableSort<DeviceConnectionSort>('time');

	function sortConnections(key: string, dir: 'asc' | 'desc') {
		connSort.key = key as DeviceConnectionSort;
		connSort.dir = dir;
		fetchConnections(1);
	}

	// Paging and sorting start their own connection loads; a newer one drops an older one's reply
	const connGuard = createLoadGuard();

	async function fetchConnections(
		pageNum: number = 1,
		s: { from: string; to: string } = span,
		ip: string = deviceIp,
	): Promise<PromiseSettledResult<unknown>> {
		const g = connGuard.begin();
		connectionsLoading = true;
		const [res] = await Promise.allSettled([
			getDeviceConnections(ip, {
				...s,
				page: pageNum,
				size: connectionsPageSize,
				sort: connSort.key,
				order: connSort.dir,
				// NET-158: filtered on the daemon, so the total and the pager count the same rows
				proto: protoFilter === 'all' ? undefined : protoFilter,
			}),
		]);
		if (!connGuard.current(g)) return res;
		if (res.status === 'fulfilled') {
			connections = res.value.connections;
			connectionsPage = res.value.page;
			connectionsTotalPages = res.value.total_pages;
			connectionsTotal = res.value.total;
		} else {
			// rows are specific to this page of results, so they are not kept as stale
			connections = [];
			connectionsTotalPages = 0;
		}
		connectionsFailed = res.status === 'rejected';
		connectionsLoading = false;
		return res;
	}

	const refresh = registerPageRefresh(load);
	onDestroy(() => {
		refresh.unregister();
		connGuard.invalidate();
	});

	$effect(() => {
		void deviceIp; // reload for another device
		void range; // refetch when the range changes
		// the loader writes and reads state; untracked so those writes can't rerun this effect
		untrack(() => refresh.run());
	});

	// NET-209: the daemon has no device for an address off the LAN (404), so show its address page; null (policy not loaded) stays
	$effect(() => {
		if (lanStatus($lanPolicy, deviceIp) === false) void goto(`/address/${encodeURIComponent(deviceIp)}`, { replaceState: true });
	});

	// The page's own 30 s auto refresh, through the same contract so "Updated" stays honest
	const AUTO_REFRESH_MS = 30_000;
	$effect(() => {
		if (!autoRefresh) return;
		const timer = setInterval(() => refresh.runIfIdle(), AUTO_REFRESH_MS);
		return () => clearInterval(timer);
	});

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	// OLD CODE START — 2026-11-06 (NET-166): a copy of formatBytes in $lib/api/logs, 1024-based under decimal labels; the shared one is decimal
	// function formatBytes(bytes: number): string {
	// 	if (bytes === 0) return '0 B';
	// 	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	// 	const i = Math.floor(Math.log(bytes) / Math.log(1024));
	// 	return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
	// }
	// OLD CODE END

	// OLD CODE START — one compact format for the app (NET-192 PR 4): formatCompactNumber in $lib/api/logs
	// function formatNumber(n: number): string {
	// 	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
	// 	if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
	// 	return n.toLocaleString();
	// }
	// OLD CODE END

	// OLD CODE START — the browser's locale printed "Nov 6" (NET-192 PR 4: formatTime)
	// function formatDate(dateStr: string): string {
	// 	if (!dateStr) return '—';
	// 	try { return new Date(dateStr).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); } catch { return dateStr; }
	// }
	// OLD CODE END
	const formatDate = (dateStr: string) => formatTime(dateStr, 'short');

	function timeAgo(dateStr: string): string {
		if (!dateStr) return '—';
		const diffMs = Date.now() - new Date(dateStr).getTime();
		const mins = Math.floor(diffMs / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h ago`;
		return `${Math.floor(hours / 24)}d ago`;
	}

	/** A chart time, with the detail the window's length calls for (utils/drilldown.ts chartTime). */
	// OLD CODE START — the browser's locale ("07:00 PM"), and only the day at 7 d (NET-192 PR 4: the shared chartTime)
	// function chartTime(t: number | string): string {
	// 	const d = new Date(t);
	// 	return range === '24h'
	// 		? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
	// 		: d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
	// }
	// OLD CODE END
	// OLD CODE: const chartTime = (t: number | string) => timeLabel(t, RANGE_HOURS[range]); (NET-196)
	const chartTime = (t: number | string) => timeLabel(t, rangeOf(range).hours);

	function chartTip(i: number): string {
		const p = bandwidth[i];
		if (!p) return '';
		return hasDualSeries
			? `${chartTime(p.timestamp)} · ↓ ${formatBytes(p.download_bytes ?? p.bytes)} · ↑ ${formatBytes(p.upload_bytes ?? 0)}`
			: `${chartTime(p.timestamp)} · ${formatBytes(p.bytes)}`;
	}

	const chartLabel = $derived(
		busiest >= 0
			? `Busiest at ${chartTime(bandwidth[busiest].timestamp)}, with ${formatBytes(bandwidth[busiest].bytes)} transferred`
			: 'No traffic in this range',
	);

	function getField(obj: Record<string, unknown>, path: string): unknown {
		const parts = path.split('.');
		let current: unknown = obj;
		for (const part of parts) {
			if (current == null || typeof current !== 'object') return undefined;
			current = (current as Record<string, unknown>)[part];
		}
		return current;
	}

	function asString(val: unknown): string {
		if (Array.isArray(val)) return String(val[0] ?? '');
		if (typeof val === 'string') return val;
		if (val != null) return String(val);
		return '';
	}

	// OLD CODE START — #144: event.start/end are epoch-ms text on Malcolm 26.x, so every row read "--"
	// function formatDuration(startVal: unknown, endVal: unknown): string {
	// 	const s = asString(startVal);
	// 	const e = asString(endVal);
	// 	if (!s || !e) return '--';
	// 	const diffMs = new Date(e).getTime() - new Date(s).getTime();
	// 	if (isNaN(diffMs) || diffMs < 0) return '--';
	// OLD CODE END
	function formatDuration(conn: Record<string, unknown>): string {
		const diffMs = connectionDurationMs(conn);
		if (diffMs === null) return '—';
		if (diffMs < 1000) return `${Math.round(diffMs)}ms`;
		const sec = diffMs / 1000;
		if (sec < 60) return `${sec.toFixed(1)}s`;
		// OLD CODE START — split before rounding, so 30 min 59.6 s read "30m 60s"
		// return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`;
		// OLD CODE END
		const total = Math.round(sec);
		return `${Math.floor(total / 60)}m ${total % 60}s`;
	}

	// OLD CODE START — 2026-11-03 UI redesign: colours for the gauge and badges; SeverityPill carries colour, shape and word
	// function riskColor(level: string): string {
	// 	if (level === 'critical') return 'var(--sev-critical)';
	// 	if (level === 'high') return 'var(--sev-high)';
	// 	if (level === 'medium') return 'var(--sev-medium)';
	// 	if (level === 'low') return 'var(--sev-low)';
	// 	return 'var(--ok)';
	// }
	// function sevLabel(sev: number): string { … }   (unused)
	// function sevClass(sev: number): string { … }   (unused)
	// OLD CODE END

	// OLD CODE START — the same mapping now lives once in $lib/utils/severity
	// /** Smart alert severity (1 critical … 4 low, 5 info), as the old badge classes read it. */
	// function smartLevel(sev: number): SeverityLevel {
	// 	if (sev <= 1) return 'critical';
	// 	if (sev === 2) return 'high';
	// 	if (sev === 3) return 'medium';
	// 	if (sev === 4) return 'low';
	// 	return 'info';
	// }
	// OLD CODE END

	const factorLabel = (name: string) => name.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());

	function openDrawer(conn: Record<string, unknown>) {
		selectedConnection = conn;
		drawerOpen = true;
	}

	function closeDrawer() {
		drawerOpen = false;
		selectedConnection = null;
	}

	// OLD CODE START — NET-158: filtered only the 25 rows on screen, while the total and pager
	// counted every protocol; the daemon filters now (fetchConnections sends proto)
	// // Filter connections by protocol (client-side)
	// let filteredConnections = $derived.by(() => {
	// 	if (protoFilter === 'all') return connections;
	// 	return connections.filter((c) => {
	// 		const proto = asString(getField(c, 'network.transport')).toLowerCase();
	// 		return proto === protoFilter;
	// 	});
	// });
	// OLD CODE END
	// the rows of one server-sorted page, keyed by position so a missing _id can't collide
	interface ConnRow {
		conn: DeviceConnection;
		key: string;
	}
	const connectionRows = $derived(connections.map((conn, i): ConnRow => ({ conn, key: `${String(conn._id)}-${i}` })));

	/** The bytes the device downloaded (dl) or uploaded (ul) on a session, from its own side. */
	function deviceBytes(conn: DeviceConnection, way: 'dl' | 'ul'): number {
		// the originator's (source) bytes are the device's upload on sessions it started, and
		// its download on sessions it answered
		const side = (conn.direction === 'in') === (way === 'dl') ? 'source' : 'destination';
		const legacy = side === 'source' ? 'client' : 'server';
		return Number(asString(getField(conn, `${side}.bytes`) ?? getField(conn, `${legacy}.bytes`))) || 0;
	}
	const selectedKey = $derived(connectionRows.find((r) => r.conn === selectedConnection)?.key);

	const dnsRows = $derived(
		(device?.dns_queries ?? [])
			.filter((d) => !d.domain.includes('._tcp.') && !d.domain.includes('._udp.') && !d.domain.endsWith('.arpa'))
			.slice(0, 10),
	);
	const pager = $derived(
		connectionsTotal > 0
			? {
					page: connectionsPage,
					pageCount: connectionsTotalPages,
					total: connectionsTotal,
					from: (connectionsPage - 1) * connectionsPageSize + 1,
					to: Math.min(connectionsPage * connectionsPageSize, connectionsTotal),
					onpage: (p: number) => fetchConnections(p),
				}
			: undefined,
	);
	// "1.2 GB" as the KPI's value and unit
	const trafficParts = $derived(formatBytes(totalBytes).split(' '));

	// Every column sorts (design system); the cell snippets are at the top of the markup
	const destColumns: Column<DeviceDestination>[] = [
		{ key: 'ip', label: 'Destination', cell: destCell },
		{ key: 'bytes', label: 'Data', numeric: true, cell: destBytesCell },
		{ key: 'connections', label: 'Conn', numeric: true, cell: destConnCell },
	];
	const dnsColumns: Column<DeviceDNSQuery>[] = [
		{ key: 'domain', label: 'Domain', cell: domainCell },
		{ key: 'count', label: 'Lookups', numeric: true, cell: countCell },
	];
	const portColumns: Column<DevicePort>[] = [
		{ key: 'port', label: 'Port', cell: portCell },
		{ key: 'service', label: 'Service', cell: serviceCell },
		{ key: 'connections', label: 'Conn', numeric: true, cell: portConnCell },
	];
	// keys are the daemon's sort names: the table only reports the sort, the daemon applies it
	const connectionColumns: Column<ConnRow>[] = [
		{ key: 'time', label: 'Time', cell: timeCell },
		// NET-158: sessions go both ways; DL and UL are the device's own
		{ key: 'direction', label: 'Direction', cell: directionCell },
		{ key: 'destination', label: 'Destination', cell: connDestCell },
		{ key: 'proto', label: 'Proto', cell: protoCell },
		{ key: 'service', label: 'Service', cell: svcCell },
		{ key: 'duration', label: 'Duration', numeric: true, cell: durationCell },
		{ key: 'dl', label: 'DL', numeric: true, cell: dlCell },
		{ key: 'ul', label: 'UL', numeric: true, cell: ulCell },
	];
</script>

{#snippet destCell(d: DeviceDestination)}<span class="mono"><IPAddress ip={d.ip} /></span>{/snippet}
{#snippet destBytesCell(d: DeviceDestination)}{formatBytes(d.bytes)}{/snippet}
{#snippet destConnCell(d: DeviceDestination)}{formatNumber(d.connections)}{/snippet}
<!-- OLD CODE START: {#snippet domainCell(q: DeviceDNSQuery)}<span class="mono trunc" title={q.domain}>{q.domain}</span>{/snippet} (NET-160: not a link) OLD CODE END -->
{#snippet domainCell(q: DeviceDNSQuery)}<a class="mono trunc" href={domainHref(q.domain)} title={q.domain}>{q.domain}</a>{/snippet}
{#snippet countCell(q: DeviceDNSQuery)}{formatNumber(q.count)}{/snippet}
<!-- OLD CODE START: {#snippet portCell(p: DevicePort)}<span class="mono">{p.port}</span>{/snippet} (slice 2a: not a link) OLD CODE END -->
<!-- The port's connections in Log Explorer: the count's own filters, written out, over its window -->
<!-- OLD CODE START (section D: the link carries the port's connection count)
	{#if portsWindow}<a class="mono" href={logsHrefForQuery(['event.provider:zeek', 'event.dataset:conn', `source.ip:"${portsWindow.ip}"`, `destination.port:${p.port}`], portsWindow, portsWindow.range)}>{p.port}</a>
OLD CODE END -->
{#snippet portCell(p: DevicePort)}
	{#if portsWindow}<a class="mono" href={withCount(logsHrefForQuery(['event.provider:zeek', 'event.dataset:conn', `source.ip:"${portsWindow.ip}"`, `destination.port:${p.port}`], portsWindow, portsWindow.range), p.connections)}>{p.port}</a>
	{:else}<span class="mono">{p.port}</span>{/if}
{/snippet}
{#snippet serviceCell(p: DevicePort)}
	<span class="svc">{p.service}{#if p.suspicious}<span class="chip is-warn"><Icon name="warn" />Suspicious</span>{/if}</span>
{/snippet}
{#snippet portConnCell(p: DevicePort)}{formatNumber(p.connections)}{/snippet}
{#snippet timeCell(r: ConnRow)}
	<!-- OLD CODE: <span class="mono">{range === '24h' ? new Date(…).toLocaleTimeString([], { hour, minute, second }) : new Date(…).toLocaleString([], { month, day, hour, minute })}</span> (NET-192 PR 4: the browser's locale printed "10:37:23 PM") -->
	<!-- OLD CODE: RANGE_HOURS[range] <= 24 (NET-196: the list's hours) -->
	<span class="mono">{formatTime(asString(getField(r.conn, '@timestamp')), rangeOf(range).hours <= 24 ? 'clock' : 'short')}</span>
{/snippet}
<!-- OLD CODE START: {#snippet connDestCell(r: ConnRow)}<span class="mono">{asString(getField(r.conn, 'destination.ip'))}:{asString(getField(r.conn, 'destination.port'))}</span>{/snippet} (slice 2a: the address wasn't a link) OLD CODE END -->
{#snippet connDestCell(r: ConnRow)}
	{@const dst = asString(getField(r.conn, 'destination.ip'))}
	<span class="mono">{#if dst}<IPAddress ip={dst} />{/if}:{asString(getField(r.conn, 'destination.port'))}</span>
{/snippet}
{#snippet protoCell(r: ConnRow)}<span class="tag">{asString(getField(r.conn, 'network.transport'))}</span>{/snippet}
{#snippet svcCell(r: ConnRow)}{asString(getField(r.conn, 'network.protocol')) || asString(getField(r.conn, 'network.transport'))}{/snippet}
<!-- OLD CODE START: <td class="mono td-sm">{formatDuration(getField(conn, 'event.start'), getField(conn, 'event.end'))}</td> OLD CODE END -->
{#snippet durationCell(r: ConnRow)}{formatDuration(r.conn)}{/snippet}
<!-- OLD CODE START — NET-158: on a session the device answered, these showed its upload as DL
{#snippet dlCell(r: ConnRow)}{formatBytes(Number(asString(getField(r.conn, 'destination.bytes') ?? getField(r.conn, 'server.bytes'))) || 0)}{/snippet}
{#snippet ulCell(r: ConnRow)}{formatBytes(Number(asString(getField(r.conn, 'source.bytes') ?? getField(r.conn, 'client.bytes'))) || 0)}{/snippet}
OLD CODE END -->
{#snippet directionCell(r: ConnRow)}<span class="tag">{r.conn.direction === 'in' ? 'In' : 'Out'}</span>{/snippet}
{#snippet dlCell(r: ConnRow)}{formatBytes(deviceBytes(r.conn, 'dl'))}{/snippet}
{#snippet ulCell(r: ConnRow)}{formatBytes(deviceBytes(r.conn, 'ul'))}{/snippet}

<svelte:head>
	<!-- OLD CODE: <title>{device?.unifi_name ?? deviceIp} | Device Intelligence | NetTap</title> (NET-200: the owner's name first) -->
	<title>{device?.custom_name ?? device?.unifi_name ?? deviceIp} | Device Intelligence | NetTap</title>
</svelte:head>

<a class="back" href="/devices"><Icon name="back" />Devices</a>

<!-- Identity hero: the h1 is here in every state, so loading and errors keep the page's heading -->
<article class="card hero">
	<div class="ident">
		<!-- OLD CODE: <DeviceTile size="lg" category={device?.category} /> (NET-200: the owner's picture) -->
		<DeviceTile size="lg" category={device?.category} picture={device?.picture} icon={device?.icon} />
		<div>
			<!-- OLD CODE: <h1 class={['page-title', !device?.unifi_name && 'mono']}>{device?.unifi_name ?? deviceIp}</h1> (NET-200) -->
			<h1 class={['page-title', !(device?.custom_name ?? device?.unifi_name) && 'mono']}>{device?.custom_name ?? device?.unifi_name ?? deviceIp}</h1>
			{#if device}
				<div class="chips">
					<span class={['chip', isOnline && 'is-ok']}>{statusLabel}</span>
					<!-- OLD CODE: {#if device.unifi_name}<span class="chip">UniFi</span>{/if} (NET-200: only when the UniFi name is the one shown) -->
					{#if device.unifi_name && !device.custom_name}<span class="chip">UniFi</span>{/if}
					<!-- OLD CODE: {#if device.os_hint}<span class="chip">{device.os_hint}</span>{/if} (NET-226: a guess shown as fact) -->
					{#if device.category && device.category !== 'unknown'}
						{@const basis = typeBasis(device.category, device.category_basis)}
						<span class="chip">{likelyType(device.category === 'iot' ? 'IoT' : device.category, device.category)}{basis ? ` · ${basis}` : ''}</span>
					{/if}
					{#if device.os_hint}
						{@const basis = osBasis(device.os_basis)}
						<span class="chip">Likely {device.os_hint}{basis ? ` · ${basis}` : ''}</span>
					{/if}
					{#each (device.protocols ?? []).slice(0, 8) as proto (proto)}<span class="tag">{proto}</span>{/each}
				</div>
			{/if}
		</div>
		<div class="head-actions">
			<!-- OLD CODE START — #87: no handlers; 24h was always marked active
			<button class="pill active">24h</button>
			<button class="pill">7d</button>
			<button class="pill">30d</button>
			OLD CODE END -->
			<Pills ariaLabel="Time range" options={RANGE_OPTIONS} bind:value={range} />
			<!-- OLD CODE START — NET-192 PR 4: Home's Auto / Paused button on every page
			<button class="btn" type="button" aria-pressed={autoRefresh} onclick={() => (autoRefresh = !autoRefresh)}>
				<Icon name="refresh" />Auto
			</button>
			OLD CODE END -->
			<AutoRefreshButton on={autoRefresh} seconds={AUTO_REFRESH_MS / 1000} ontoggle={() => (autoRefresh = !autoRefresh)} />
		</div>
	</div>
	{#if device && device.ip}
		<!-- NET-201: the owner's name and picture, as on the MAC page; they are kept by MAC, so a device without one has no buttons -->
		{#if device.mac}
			{@const mac = device.mac}
			<!-- keyed: another device starts with its panels closed -->
			<!-- discovered_name comes only with an owner's name; without one the hostname is the network's name, for the Name hint -->
			{#key mac}<DeviceCustomise device={{ ...device, mac, discovered_name: device.custom_name ? device.discovered_name : device.hostname }} onsave={customise} />{/key}
		{/if}
		<dl class="ident-meta">
			<div><dt class="meta-k">IP address</dt><dd class="meta-v mono">{device.ip}</dd></div>
			<div><dt class="meta-k">MAC</dt><dd class="meta-v mono">{device.mac ?? '—'}</dd></div>
			<div><dt class="meta-k">Vendor</dt><dd class="meta-v">{device.manufacturer ?? '—'}</dd></div>
			<!-- OLD CODE: <dd class="meta-v mono">{device.hostname ?? '—'}</dd> (NET-200: hostname carries the owner's name; the real one stays visible) -->
			<!-- OLD CODE: <dd class="meta-v mono">{device.discovered_name ?? device.hostname ?? '—'}</dd> (NET-201: an owner's name with no discovered name showed as the hostname) -->
			<div><dt class="meta-k">Hostname</dt><dd class="meta-v mono">{device.custom_name ? (device.discovered_name ?? '—') : (device.hostname ?? '—')}</dd></div>
			<div><dt class="meta-k">First seen in range</dt><dd class="meta-v">{formatDate(device.first_seen)}</dd></div>
			<div><dt class="meta-k">Last seen</dt><dd class="meta-v">{timeAgo(device.last_seen)}</dd></div>
		</dl>
	{:else if loading && !device}
		<CardState state="loading" title="Loading device" />
	{:else if deviceFailed && !device}
		<CardState state="error" title={loadFailed(`device ${deviceIp}`)} onaction={() => refresh.run()} />
	{:else}
		<CardState state="empty" icon="devices" title="Device not found: {deviceIp}" actionLabel="Return to devices" href="/devices" />
	{/if}
</article>

{#if device && device.ip}
	{#if deviceFailed}
		<!-- OLD CODE: <p class="note">{loadFailed('this device', true)}</p> (NET-192 PR 4: a stale note is the shared amber notice) -->
		<p class="notice is-warn load-note" role="status"><Icon name="warn" /><span>{loadFailed('this device', true)}</span></p>
	{/if}
	{#if (device.ipv6_left_out ?? 0) > 0 && ipv6LeftOutText(device.ipv6_left_out_reason)}
		<p class="notice is-warn load-note" role="note"><Icon name="warn" /><span>{ipv6LeftOutText(device.ipv6_left_out_reason)}</span></p>
	{/if}

	<div class="grid">
		<!-- OLD CODE: sub="↓ {formatBytes(respBytes)} down · ↑ {formatBytes(origBytes)} up" (NET-226: both sides now, from the device's side) -->
		<KpiCard class="c-3" label="Traffic" icon="bandwidth" value={trafficParts[0]} unit={trafficParts[1]}
			sub="↓ {formatBytes(downloadBytes)} down · ↑ {formatBytes(uploadBytes)} up" note={RANGE_LABEL[range]} />
		<KpiCard class="c-3" label="Upload share" icon="up" value={uploadRatio} unit="%" sub={uploadRatioLabel} note={RANGE_LABEL[range]}>
			{#snippet foot()}<Meter value={uploadRatio} label="Upload share {uploadRatio}%" />{/snippet}
		</KpiCard>
		<!-- NET-226: started and answered, IPv6 included; Recent connections lists this address's IPv4 sessions -->
		<KpiCard class="c-3" label="Connections" icon="connections" value={formatNumber(device.connection_count)}
			sub="{device.ipv6_connections ? `of which ${formatNumber(device.ipv6_connections)} over IPv6 · ` : ''}{formatNumber(device.unique_destinations ?? 0)} unique destinations" note={RANGE_LABEL[range]} />
		<KpiCard class="c-3" label="Alerts" icon="alerts" value={formatNumber(device.alert_count)} sub="Suricata alerts on this device's traffic" note={RANGE_LABEL[range]} />

		<!-- NET-205: counted by this page's IP only; its MAC can be one the address had before -->
		<LiveBandwidthCard key={{ ip: device.ip }} />

		<Card class="c-8" hero col title="Bandwidth over time" sub="Bytes per interval · {RANGE_LABEL[range].toLowerCase()}">
			{#snippet actions()}
				{#if hasDualSeries && busiest >= 0}
					<ul class="legend">
						<li><span class="sw c-d1"></span>Download</li>
						<li><span class="sw c-d2"></span>Upload</li>
					</ul>
				{/if}
			{/snippet}
			{#if busiest >= 0}
				<AreaChart bytes series={chartSeries} formatX={chartTime} formatY={formatBytes} formatTip={chartTip} highlightIndex={busiest} ariaLabel={chartLabel} />
				<!-- OLD CODE: <p class="chart-note">{INTER_VLAN_NOTE}</p> (review L10: only for a device with traffic to another subnet) -->
				{#if device.inter_vlan_connections}<p class="chart-note">{interVlanNote(device.inter_vlan_connections)}</p>{/if}
			{:else}
				<CardState state="empty" icon="bandwidth" title="No traffic in this range" message="The chart fills in once NetTap records traffic from this device." />
			{/if}
		</Card>

		<!-- OLD CODE: title="Risk score" in every mode (NET-225: post-NAT, one address can carry several devices) -->
		<Card class="c-4" title={$captureMode === 'bridge' ? 'Risk score for this address' : 'Risk score'} sub="Out of 100 · higher is riskier · {RANGE_LABEL[range].toLowerCase()}">
			{#if riskLoaded}
				<div class="trust-top">
					<Ring value={riskScore} ariaLabel="Risk score {riskScore} of 100, {riskLevel}" />
					{#if riskSeverity}<SeverityPill level={riskSeverity} />{/if}
				</div>
				{#if $captureMode === 'bridge'}
					<p class="trust-plain">In inline bridge mode this score uses the traffic seen for this address. After your router's IPv4 address translation one address can carry several devices' traffic, so it can't stand for a single device's risk.</p>
				{/if}
				<!-- OLD CODE: <p class="note">{loadFailed('the risk score', true)}</p> (NET-192 PR 4: a stale note is the shared amber notice) -->
				{#if riskFailed}<p class="notice is-warn load-note" role="status"><Icon name="warn" /><span>{loadFailed('the risk score', true)}</span></p>{/if}
				{#if riskFactors.length > 0}
					<ul class="score-rows">
						{#each riskFactors as factor, i (`${factor.name}-${i}`)}
							{@const pct = factor.max > 0 ? (factor.score / factor.max) * 100 : 0}
							<li title={factor.description}>
								<span>{factorLabel(factor.name)}</span><b>{factor.score} / {factor.max}</b>
								<span class="bar-track" aria-hidden="true"><span class="bar-fill c-d1" style:--w="{pct.toFixed(1)}%"></span></span>
							</li>
						{/each}
					</ul>
				{:else}
					<p class="trust-plain">No risk factors reported.</p>
				{/if}
			{:else if riskFailed}
				<CardState state="error" title={loadFailed('the risk score')} onaction={() => refresh.run()} />
			{:else}
				<CardState state="loading" title="Loading the risk score" />
			{/if}
		</Card>

		<Card class="c-8" title="Smart alerts" sub="Grouped by signature · {RANGE_LABEL[range].toLowerCase()}">
			{#snippet actions()}
				<span class="chip">{smartAlertsFailed ? 'check failed' : `${smartAlertsTotal} grouped`}</span>
			{/snippet}
			{#if smartAlerts.length > 0}
				<ul class="sa-list">
					{#each (alertsExpanded ? smartAlerts : smartAlerts.slice(0, ALERTS_COLLAPSED_COUNT)) as sa, i (`${sa.signature_id}-${sa.source_ip}-${i}`)}
						<!-- OLD CODE: {@const exact = smartAlertsWindow ? smartAlertHref(sa.key, smartAlertsWindow, smartAlertsWindow.ip) : null} (NET-191: an activity group opens the activity list) -->
						{@const exact = smartAlertsWindow ? smartAlertHref(sa.key, smartAlertsWindow, smartAlertsWindow.ip, sa.activity) : null}
						<!-- NET-160 slice 2b-1: `exact` is the list holding this ×N, counted for this device over the stored window -->
						<li class="sa">
							<div class="sa-head">
								<SeverityPill level={smartLevel(sa.severity)} />
								<b>{sa.category_label}</b>
								<!-- OLD CODE: <span class="dim num">×{formatNumber(sa.count)}</span> (slice 2b-1: the count wasn't a link) -->
								<!-- OLD CODE: <a class="num" href={exact} …> (section D: the ×N link carries its figure) -->
								{#if exact}
									<a class="num" href={withCount(exact, sa.count)} aria-label="×{formatNumber(sa.count)} alerts: {sa.signature}">×{formatNumber(sa.count)}</a>
								{:else}
									<span class="dim num" title={NO_EXACT_ALERT_LIST}>×{formatNumber(sa.count)}</span>
								{/if}
								<!-- OLD CODE START — NET-228: compute_trend is an absolute rate with no comparison window, so it can't say rising or falling; the assessment states the rate
								{#if sa.trend === 'increasing'}
									<Icon name="up" label="Rising" />
								{:else if sa.trend === 'decreasing'}
									<Icon name="down" label="Falling" />
								{/if}
								OLD CODE END -->
							</div>
							<!-- OLD CODE: <div class="sig wrap">{sa.signature}</div> (slice 2a: not a link) -->
							<!-- OLD CODE: <a class="sig wrap" href={alertsHrefForSignature(sa.signature, smartAlertsWindow ?? undefined, smartAlertsWindow?.ip)}>{sa.signature}</a> (slice 2b-1: the shown name can differ from rule.name, and ip alone listed the device's other pairs) -->
							<!-- OLD CODE: <a class="sig wrap" href={exact}> (section D: same list as the ×N, so the same figure) -->
							{#if exact}
								<a class="sig wrap" href={withCount(exact, sa.count)}>{sa.signature}</a>
							{:else}
								<div class="sig wrap">{sa.signature}</div>
							{/if}
							<div class="mono dim">{sa.source_ip} → {sa.destination_ip}{#if sa.destination_port}:{sa.destination_port}{/if}</div>
							<p class="sa-plain">{sa.assessment}</p>
							<div class="actions">
								<a href="/alerts?ip={encodeURIComponent(deviceIp)}" class="btn">Investigate</a>
								<!-- OLD CODE START — removed the row before the daemon answered; a failed suppress was an unhandled rejection -->
								<!-- <button class="sa-action-btn" onclick={() => { suppressAlert(sa.signature_id, deviceIp); smartAlerts = smartAlerts.filter(a => a !== sa); }}>Suppress</button> -->
								<!-- OLD CODE END -->
								<button class="btn" type="button" onclick={() => suppressSmartAlert(sa)}>Suppress</button>
								{#if suppressFailedId === sa.signature_id}
									<span class="sa-error" role="alert">Suppress failed. Try again.</span>
								{/if}
							</div>
						</li>
					{/each}
				</ul>
				<div class="sa-foot">
					{#if smartAlerts.length > ALERTS_COLLAPSED_COUNT}
						<button class="btn" type="button" onclick={() => (alertsExpanded = !alertsExpanded)}>
							{alertsExpanded ? 'Show less' : `Show ${smartAlerts.length - ALERTS_COLLAPSED_COUNT} more alerts`}
						</button>
					{/if}
					<a href="/alerts?ip={encodeURIComponent(deviceIp)}" class="link">View all alerts<Icon name="back" class="chev" /></a>
				</div>
			{:else if smartAlertsFailed}
				<CardState state="error" title="Couldn't load alerts for this device: the request failed." onaction={() => refresh.run()} />
			{:else}
				<!-- OLD CODE: <CardState state="empty" icon="alerts" title="No actionable alerts for this device." /> (NET-228: read the same with no data arriving) -->
				<CardState state="empty" icon={noGroups.trusted ? 'alerts' : 'warn'} title={noGroups.title} message="{noGroups.detail}." />
			{/if}
		</Card>

		<div class="stack c-4">
			<!-- OLD CODE: sub="Bytes by category · …" (NET-226 follow-up: it reads the connections the device started) -->
			<Card title="Traffic categories" sub="Bytes by category · connections it started · {RANGE_LABEL[range].toLowerCase()}">
				{#if categoriesFailed && categories.length === 0}
					<CardState state="error" title={loadFailed('traffic categories')} onaction={() => refresh.run()} />
				{:else if categories.length === 0}
					<!-- OLD CODE: title="No category data available." -->
					<CardState state="empty" icon="bandwidth" title="No category data for connections it started." />
				{:else}
					<!-- OLD CODE: <p class="note">{loadFailed('traffic categories', true)}</p> (NET-192 PR 4: a stale note is the shared amber notice) -->
					{#if categoriesFailed}<p class="notice is-warn load-note" role="status"><Icon name="warn" /><span>{loadFailed('traffic categories', true)}</span></p>{/if}
					<BarList
						items={categories.map((c, i) => ({
							key: `${c.name}-${i}`,
							label: c.label,
							value: c.total_bytes,
							display: formatBytes(c.total_bytes),
							href: `/traffic/${c.name}`,
						}))}
					/>
				{/if}
			</Card>
			<!-- OLD CODE: sub="Bytes by service · …" (NET-226 follow-up: as Traffic categories) -->
			<Card title="Top services" sub="Bytes by service · connections it started · {RANGE_LABEL[range].toLowerCase()}">
				{#if device.top_services?.length}
					<BarList
						items={device.top_services.map((svc, i) => ({
							key: `${svc.name}-${i}`,
							label: svc.name,
							value: svc.bytes,
							display: formatBytes(svc.bytes),
							detail: `${formatNumber(svc.connections)} connections`,
						}))}
					/>
				{:else}
					<!-- OLD CODE: title="No service data available." -->
					<CardState state="empty" icon="connections" title="No service data for connections it started." />
				{/if}
			</Card>
		</div>

		<!-- OLD CODE: sub="By bytes · …" (NET-226 follow-up: as Traffic categories) -->
		<Card class="c-4" title="Top destinations" sub="By bytes · connections it started · {RANGE_LABEL[range].toLowerCase()}">
			{#if device.top_destinations?.length}
				<DataTable
					ariaLabel="Top destinations"
					rows={device.top_destinations.slice(0, 8)}
					rowKey={(d) => d.ip}
					initialSort={{ key: 'bytes', dir: 'desc' }}
					columns={destColumns}
				/>
			{:else}
				<!-- OLD CODE: title="No destination data." -->
				<CardState state="empty" icon="connections" title="No destination data for connections it started." />
			{/if}
		</Card>

		<Card class="c-4" title="DNS activity" sub="Lookups by domain · {RANGE_LABEL[range].toLowerCase()}">
			{#if dnsRows.length > 0}
				<DataTable ariaLabel="DNS activity" rows={dnsRows} rowKey={(q) => q.domain} initialSort={{ key: 'count', dir: 'desc' }} columns={dnsColumns} />
			{:else}
				<!-- OLD CODE: <CardState state="empty" icon="dns" title="No DNS data." /> (NET-225: DoH and DoT lookups never show) -->
				<CardState state="empty" icon="dns" title="No plain DNS lookups seen." message={ENCRYPTED_DNS_NOTE} />
			{/if}
		</Card>

		<!-- OLD CODE: sub="By connections · …" (NET-226 follow-up: the ports it connected to) -->
		<Card class="c-4" title="Top ports used" sub="By connections · connections it started · {RANGE_LABEL[range].toLowerCase()}">
			{#if portsFailed && ports.length === 0}
				<CardState state="error" title={loadFailed('ports')} onaction={() => refresh.run()} />
			{:else if ports.length === 0}
				<!-- OLD CODE: title="No port data." -->
				<CardState state="empty" icon="connections" title="No port data for connections it started." />
			{:else}
				<!-- OLD CODE: <p class="note">{loadFailed('ports', true)}</p> (NET-192 PR 4: a stale note is the shared amber notice) -->
				{#if portsFailed}<p class="notice is-warn load-note" role="status"><Icon name="warn" /><span>{loadFailed('ports', true)}</span></p>{/if}
				<DataTable ariaLabel="Top ports" rows={ports.slice(0, 8)} rowKey={(p) => p.port} initialSort={{ key: 'connections', dir: 'desc' }} columns={portColumns} />
			{/if}
		</Card>

		<!-- OLD CODE START — NET-158: the list has both directions
		<Card class="c-12" title="Recent connections" sub="Sessions from this device · {RANGE_LABEL[range].toLowerCase()}">
		OLD CODE END -->
		<!-- OLD CODE: sub="Sessions to or from this device · …" (NET-226: the device's IPv6 is in its KPIs, not in this list) -->
		<Card class="c-12" title="Recent connections" sub="Sessions to or from this address · {RANGE_LABEL[range].toLowerCase()}">
			{#snippet actions()}
				<span class="chip">{connectionsFailed ? 'load failed' : `${formatNumber(connectionsTotal)} total`}</span>
			{/snippet}
			<div class="toolbar">
				<Pills ariaLabel="Protocol" options={PROTO_OPTIONS} bind:value={protoFilter} onchange={() => fetchConnections(1)} />
			</div>
			{#if connectionsLoading}
				<CardState state="loading" title="Loading connections" />
			{:else if connectionsFailed}
				<CardState state="error" title={loadFailed('connections')} onaction={() => fetchConnections(connectionsPage)} />
			{:else if connectionRows.length === 0}
				<CardState state="empty" icon="connections" title="No connections in this range" />
			{:else}
				<DataTable
					ariaLabel="Recent connections"
					rows={connectionRows}
					rowKey={(r) => r.key}
					initialSort={{ key: connSort.key, dir: connSort.dir }}
					onsortchange={sortConnections}
					onrowactivate={(r) => openDrawer(r.conn)}
					rowLabel={(r) => `Open connection to ${asString(getField(r.conn, 'destination.ip'))}`}
					{selectedKey}
					{pager}
					columns={connectionColumns}
				/>
			{/if}
			{#snippet foot()}
				<div class="actions">
					<a href="/logs?filter={encodeURIComponent(deviceIp)}" class="link">View in Log Explorer<Icon name="back" class="chev" /></a>
					<a href="/connections?ip={encodeURIComponent(deviceIp)}" class="link">Filter connections<Icon name="back" class="chev" /></a>
				</div>
			{/snippet}
		</Card>
	</div>
{/if}

<!-- Connection Drill-Down Drawer -->
{#if drawerOpen && selectedConnection}
	<ConnectionDrawer connection={selectedConnection} deviceIp={deviceIp} onclose={closeDrawer} />
{/if}

<style>
	/* Layout glue the system lacks */
	.ident-meta > div { min-width: 0; }
	.ident-meta dd { margin: 0; }
	/* OLD CODE: .note { color: var(--text-2); font-size: var(--text-sm); margin-bottom: var(--sp-3); } (NET-192 PR 4: its stale notes are the amber notice) */
	.load-note { margin-bottom: var(--sp-3); }
	.chart-note { color: var(--text-2); font-size: var(--text-sm); margin: var(--sp-3) 0 0; }
	.sa-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--sp-3); }
	.sa { display: flex; flex-direction: column; gap: var(--sp-1); padding: var(--sp-3) var(--sp-4); border-radius: var(--r-md); background: var(--surface-2); border: 1px solid var(--line); }
	.sa-head { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; font-size: var(--text-sm); }
	.sa-plain { color: var(--text-2); font-size: var(--text-sm); }
	.sa .actions { margin-top: var(--sp-2); align-items: center; }
	.sa-error { color: var(--sev-high); font-size: var(--text-xs); font-weight: 600; }
	.sa-foot { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); margin-top: var(--sp-4); flex-wrap: wrap; }
	.svc { display: inline-flex; align-items: center; gap: var(--sp-2); }
</style>
