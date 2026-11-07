<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	// OLD CODE: import { byteSize, compareValues } from '$lib/utils/table-sort.svelte'; (NET-166: index sizes arrive in bytes)
	import { compareValues } from '$lib/utils/table-sort.svelte';
	// NET-166: the shared formatter prints 0 as "0 B"; this page's own prints '--' for 0, which its KPIs rely on
	import { formatBytes as sharedFormatBytes } from '$lib/api/logs';
	import { createLoadGuard, registerPageRefresh, type LoadGuard, type LoadResult, outcome } from '$lib/stores/pageRefresh';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Meter from '$lib/components/ui/Meter.svelte';
	import Pipeline, { type PipelineStage } from '$lib/components/ui/Pipeline.svelte';
	import StatStrip from '$lib/components/ui/StatStrip.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { getBridgeHealth } from '$api/bridge.js';
	// OLD CODE: import { …, formatLossPct, packetsLost, LOSS_SCOPE } (NET-167: loss figures read the daemon's loss_window)
	import { getCaptureStats, getCaptureMode, getCaptureHealth, formatLossPct, lossWords, LOSS_SCOPE, type LossWords } from '$api/capture';
	import { getSystemHealth, getStorageStatus } from '$api/system.js';
	import {
		getOpenSearchCluster,
		getOpenSearchIndices,
		getOpenSearchTemplates,
		getLogstashStats,
		getLogstashPipelines
	} from '$api/infrastructure';
	import type { OpenSearchCluster, OpenSearchIndex, LogstashStats, LogstashPipeline } from '$api/infrastructure';
	import type { BridgeHealth } from '$api/bridge.js';
	import type { CaptureMode, CaptureStatsResponse, CaptureHealthResponse } from '$api/capture';
	import type { SystemHealth, StorageStatus } from '$api/system.js';
	import {
		getUnifiStatus,
		getUnifiDevices,
		getUnifiNetworks,
		getUnifiWifi,
		getUnifiFirewall,
		getUnifiDnsPolicies,
		getUnifiWans,
		getUnifiVpn,
	} from '$api/unifi';
	import type {
		UnifiStatus,
		UnifiDevice,
		UnifiNetwork,
		UnifiWifi,
		UnifiFirewall,
		DnsPolicy,
		UnifiWan,
		UnifiVpnTunnel,
		FirewallPolicy,
	} from '$api/unifi';
	import { loadFailed } from '$lib/utils/load-failed';
	import { getTrafficSummary } from '$api/traffic';
	import { getAlertCount } from '$api/alerts';

	// OLD CODE START — the topology's click-to-open detail panels and the page Refresh button are gone: every
	// stage card is always shown, and the top bar's Refresh runs the page loader
	// // ─── Node type for topology ─────────────────────────────────
	// type NodeId = 'bridge' | 'capture' | 'zeek' | 'suricata' | 'filebeat' | 'logstash' | 'opensearch';
	//
	// // ─── Reactive state ─────────────────────────────────────────
	// let selectedNode = $state<NodeId | null>(null);
	// let loading = $state(false);
	// OLD CODE END

	// Data state
	let bridgeHealth = $state<BridgeHealth | null>(null);
	let captureStats = $state<CaptureStatsResponse | null>(null);
	let captureMode = $state<CaptureMode | null>(null);
	let captureHealth = $state<CaptureHealthResponse | null>(null);
	// a mirror box has no bridge: the first pipeline node is the mirror (SPAN) port instead
	const isMirror = $derived(captureMode?.mode === 'mirror');
	// nor does a DHCP gateway box: its first node is the LAN port it routes and captures on
	const isGateway = $derived(captureMode?.mode === 'dhcp_gateway');
	const portName = $derived(isGateway ? 'Gateway port' : 'Mirror port');
	let systemHealth = $state<SystemHealth | null>(null);
	let storageStatus = $state<StorageStatus | null>(null);
	let cluster = $state<OpenSearchCluster | null>(null);
	let indices = $state<OpenSearchIndex[]>([]);
	let templates = $state<unknown[]>([]);
	let logstashStats = $state<LogstashStats | null>(null);
	// S8: events into Logstash per second between two polls (events_in counts since Logstash
	// started); null until there are two readings, or after Logstash restarts
	let eventsInRate = $state<number | null>(null);
	let lastEventsIn: { count: number; at: number } | null = null;
	let logstashPipelines = $state<LogstashPipeline[]>([]);
	let showTemplates = $state(false);
	// #96: sources whose last request failed; their figures are the last good reading or '--'
	let failedSources = $state<Record<string, boolean>>({});
	const failedNames = $derived(
		Object.keys(failedSources).filter(
			// a mirror or gateway box shows no bridge, so its bridge health is not news
			(name) => failedSources[name] && !(name === 'bridge health' && (isMirror || isGateway)),
		),
	);

	/** Apply a settled result: keep the old value on failure and record which source failed. */
	function settle<T>(name: string, result: PromiseSettledResult<T>, apply: (value: T) => void) {
		if (result.status === 'fulfilled') apply(result.value);
		failedSources = { ...failedSources, [name]: result.status === 'rejected' };
	}

	// UniFi integration state
	let unifiStatus = $state<UnifiStatus | null>(null);
	let unifiDevices = $state<UnifiDevice[]>([]);
	let unifiNetworks = $state<UnifiNetwork[]>([]);
	let unifiWifi = $state<UnifiWifi[]>([]);
	let unifiFirewall = $state<UnifiFirewall>({ policies: [], zones: [] });
	let unifiDnsPolicies = $state<DnsPolicy[]>([]);
	let unifiWans = $state<UnifiWan[]>([]);
	let unifiVpn = $state<UnifiVpnTunnel[]>([]);
	let unifiLoading = $state(false);
	// #96: UniFi reads that failed on the last poll, keyed by what the card calls them
	let unifiFailed = $state<Record<string, boolean>>({});

	/** A UniFi figure, or '—' when its read failed and there is no earlier reading to show. */
	function unifiCount(what: string, n: number): number | string {
		return unifiFailed[what] && n === 0 ? '—' : n;
	}

	const unifiPostureNotes = $derived(
		(
			[
				['firewall policies', unifiFirewall.policies.length + unifiFirewall.zones.length],
				['DNS policies', unifiDnsPolicies.length],
				['VPN tunnels', unifiVpn.length],
				['WAN interfaces', unifiWans.length],
			] as const
		)
			.filter(([what]) => unifiFailed[what])
			.map(([what, n]) => loadFailed(what, n > 0)),
	);

	// Zeek/Suricata throughput (computed from event counts over 5-min window)
	let zeekEventsPerSec = $state<number | null>(null);
	let suricataAlertsPerSec = $state<number | null>(null);

	// ─── Helpers ────────────────────────────────────────────────
	function formatBytes(bytes: number | null | undefined): string {
		if (bytes == null || !isFinite(bytes) || bytes <= 0) return '--';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		// OLD CODE START — 2026-11-06 (NET-166): 1024-based under decimal labels
		// const i = Math.floor(Math.log(bytes) / Math.log(1024));
		// const val = bytes / Math.pow(1024, i);
		// OLD CODE END
		const i = Math.floor(Math.log(bytes) / Math.log(1000));
		const val = bytes / Math.pow(1000, i);
		return `${val.toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
	}

	/** S12: the daemon's measured bytes per second; '--' on the first sample or after a reset. */
	function byteRate(perSec: number | null | undefined): string {
		if (perSec == null) return '--';
		return perSec > 0 ? `${formatBytes(perSec)}/s` : '0 B/s';
	}

	function formatNumber(n: number | null | undefined): string {
		if (n == null || !isFinite(n)) return '--';
		return n.toLocaleString();
	}

	function formatDate(d: string | null | undefined): string {
		if (!d) return '--';
		try { return new Date(d).toLocaleDateString(); } catch { return '--'; }
	}

	function formatUptime(seconds: number): string {
		if (!seconds || seconds <= 0) return '--';
		const d = Math.floor(seconds / 86400);
		const h = Math.floor((seconds % 86400) / 3600);
		const m = Math.floor((seconds % 3600) / 60);
		if (d > 0) return `${d}d ${h}h`;
		if (h > 0) return `${h}h ${m}m`;
		return `${m}m`;
	}

	// OLD CODE START — health dots and heap colours: states are the system's .res marks and the Pipeline strip now
	// function healthDotClass(status: string | null | undefined): string {
	// 	if (!status) return '';
	// 	const s = status.toLowerCase();
	// 	if (s === 'green' || s === 'up' || s === 'normal' || s === 'running' || s === 'healthy') return 'green';
	// 	if (s === 'yellow' || s === 'degraded') return 'yellow';
	// 	return 'red';
	// }
	//
	// function heapColor(percent: number): string {
	// 	if (percent > 85) return 'var(--red)';
	// 	if (percent > 70) return 'var(--amber)';
	// 	return 'var(--green)';
	// }
	// OLD CODE END

	// ─── Data fetching ──────────────────────────────────────────
	// OLD CODE START — #96: the getters faked zeros/"red"/"down" on failure and one failure
	// blanked its whole group; they now throw, so each result is settled on its own
	// async function fetchBridgeAndCapture() {
	// 	try {
	// 		const [bh, cs, cm, ch] = await Promise.all([
	// 			getBridgeHealth(),
	// 			getCaptureStats(),
	// 			getCaptureMode().catch(() => null),
	// 			getCaptureHealth(),
	// 		]);
	// 		bridgeHealth = bh;
	// 		captureStats = cs;
	// 		if (cm) captureMode = cm;
	// 		captureHealth = ch;
	// 	} catch { /* swallow — individual calls have their own fallbacks */ }
	// }
	//
	// async function fetchLogstash() {
	// 	try {
	// 		const [stats, pipelines] = await Promise.all([
	// 			getLogstashStats(),
	// 			getLogstashPipelines(),
	// 		]);
	// 		logstashStats = stats;
	// 		logstashPipelines = pipelines;
	// 	} catch { /* swallow */ }
	// }
	//
	// async function fetchOpenSearch() {
	// 	try {
	// 		const [cl, idx, tmpl] = await Promise.all([
	// 			getOpenSearchCluster(),
	// 			getOpenSearchIndices(),
	// 			getOpenSearchTemplates(),
	// 		]);
	// 		cluster = cl;
	// 		indices = idx?.indices ?? [];
	// 		templates = Array.isArray(tmpl) ? tmpl : [];
	// 	} catch { /* swallow */ }
	// }
	//
	// async function fetchStorage() {
	// 	try {
	// 		const [health, storage] = await Promise.all([
	// 			getSystemHealth(),
	// 			getStorageStatus(),
	// 		]);
	// 		systemHealth = health;
	// 		storageStatus = storage;
	// 	} catch { /* swallow */ }
	// }
	// OLD CODE END
	// OLD CODE START — the page refresh contract (PLAN §5.5): each poll group now loads under its own guard
	// and reports what answered, so polling, the top bar's Refresh and "Updated" share one loader
	// async function fetchBridgeAndCapture() {
	// 	const [bh, cs, cm, ch] = await Promise.allSettled([
	// 		getBridgeHealth(),
	// 		getCaptureStats(),
	// 		getCaptureMode(),
	// 		getCaptureHealth(),
	// 	]);
	// 	settle('bridge health', bh, (v) => (bridgeHealth = v));
	// 	settle('capture counters', cs, (v) => (captureStats = v));
	// 	settle('capture mode', cm, (v) => (captureMode = v));
	// 	settle('capture health', ch, (v) => (captureHealth = v));
	// }
	//
	// async function fetchLogstash() {
	// 	const [stats, pipelines] = await Promise.allSettled([getLogstashStats(), getLogstashPipelines()]);
	// 	settle('Logstash stats', stats, (v) => (logstashStats = v));
	// 	if (pipelines.status === 'fulfilled') logstashPipelines = pipelines.value;
	// }
	//
	// async function fetchOpenSearch() {
	// 	const [cl, idx, tmpl] = await Promise.allSettled([
	// 		getOpenSearchCluster(),
	// 		getOpenSearchIndices(),
	// 		getOpenSearchTemplates(),
	// 	]);
	// 	settle('OpenSearch cluster', cl, (v) => (cluster = v));
	// 	settle('OpenSearch indices', idx, (v) => (indices = v?.indices ?? []));
	// 	if (tmpl.status === 'fulfilled') templates = Array.isArray(tmpl.value) ? tmpl.value : [];
	// }
	//
	// async function fetchStorage() {
	// 	const [health, storage] = await Promise.allSettled([getSystemHealth(), getStorageStatus()]);
	// 	settle('system health', health, (v) => (systemHealth = v));
	// 	settle('storage', storage, (v) => (storageStatus = v));
	// }
	// OLD CODE END

	// OLD CODE START — the daemon doesn't read "now-5m", so it answered for 24 h and Zeek showed
	// 1,601 evt/s (a day of connections / 300 s) for ~5/s; Suricata read d.total, which the count
	// reply nests under counts, so it always said 0; Math.round turned 0.8 alerts/s into 1
	// async function fetchToolRates() {
	// 	const WINDOW_SECS = 300; // 5-minute window
	// 	try {
	// 		// Zeek events (connection count from traffic summary)
	// 		const zeekRes = await fetch('/api/traffic/summary?from=now-5m&to=now');
	// 		if (zeekRes.ok) {
	// 			const d = await zeekRes.json();
	// 			const count = d.connection_count ?? d.total_connections ?? 0;
	// 			zeekEventsPerSec = count > 0 ? Math.round(count / WINDOW_SECS) : 0;
	// 		}
	// 	} catch { /* swallow */ }
	// 	try {
	// 		// Suricata alerts (total count from alerts API)
	// 		const suriRes = await fetch('/api/alerts/count?from=now-5m&to=now');
	// 		if (suriRes.ok) {
	// 			const d = await suriRes.json();
	// 			const count = d.total ?? 0;
	// 			suricataAlertsPerSec = count > 0 ? Math.round(count / WINDOW_SECS) : 0;
	// 		}
	// 	} catch { /* swallow */ }
	// }
	// OLD CODE END
	// OLD CODE START — the page refresh contract (PLAN §5.5); the rates moved into loadPipeline and UniFi into
	// loadUnifi, unchanged but for the load guard
	// async function fetchToolRates() {
	// 	const WINDOW_SECS = 300; // 5-minute window
	// 	const to = new Date();
	// 	const range = { from: new Date(to.getTime() - WINDOW_SECS * 1000).toISOString(), to: to.toISOString() };
	// 	const perSec = (count: number) => Math.round((count / WINDOW_SECS) * 10) / 10;
	// 	const [conns, alerts] = await Promise.allSettled([getTrafficSummary(range), getAlertCount(range)]);
	// 	// a failed read keeps the last rate (or '--' before the first)
	// 	if (conns.status === 'fulfilled') zeekEventsPerSec = perSec(conns.value.connection_count);
	// 	if (alerts.status === 'fulfilled') suricataAlertsPerSec = perSec(alerts.value.counts.total);
	// }
	//
	// async function fetchUnifi() {
	// 	// OLD CODE START — #96: a failed status read showed "Connect your UniFi controller" and one failed
	// 	// list blanked them all; the getters now throw, so each read is settled and shown on its own card
	// 	// try {
	// 	// 	const status = await getUnifiStatus();
	// 	// 	unifiStatus = status;
	// 	// 	if (!status.configured) return;
	// 	// 	unifiLoading = true;
	// 	// 	const [devices, networks, wifi, firewall, dnsPolicies, wans, vpn] = await Promise.all([
	// 	// 		getUnifiDevices(),
	// 	// 		getUnifiNetworks(),
	// 	// 		getUnifiWifi(),
	// 	// 		getUnifiFirewall(),
	// 	// 		getUnifiDnsPolicies(),
	// 	// 		getUnifiWans(),
	// 	// 		getUnifiVpn(),
	// 	// 	]);
	// 	// 	unifiDevices = devices;
	// 	// 	unifiNetworks = networks;
	// 	// 	unifiWifi = wifi;
	// 	// 	unifiFirewall = firewall;
	// 	// 	unifiDnsPolicies = dnsPolicies;
	// 	// 	unifiWans = wans;
	// 	// 	unifiVpn = vpn;
	// 	// } catch { /* swallow */ }
	// 	// unifiLoading = false;
	// 	// OLD CODE END
	// 	let status: UnifiStatus;
	// 	try {
	// 		status = await getUnifiStatus();
	// 	} catch {
	// 		// keep the last status (and the cards it shows); the banner says it is stale
	// 		unifiFailed = { ...unifiFailed, 'the UniFi status': true };
	// 		return;
	// 	}
	// 	unifiStatus = status;
	// 	unifiFailed = { ...unifiFailed, 'the UniFi status': false };
	// 	if (!status.configured) return;
	// 	unifiLoading = true;
	// 	const [devices, networks, wifi, firewall, dnsPolicies, wans, vpn] = await Promise.allSettled([
	// 		getUnifiDevices(),
	// 		getUnifiNetworks(),
	// 		getUnifiWifi(),
	// 		getUnifiFirewall(),
	// 		getUnifiDnsPolicies(),
	// 		getUnifiWans(),
	// 		getUnifiVpn(),
	// 	]);
	// 	if (devices.status === 'fulfilled') unifiDevices = devices.value;
	// 	if (networks.status === 'fulfilled') unifiNetworks = networks.value;
	// 	if (wifi.status === 'fulfilled') unifiWifi = wifi.value;
	// 	if (firewall.status === 'fulfilled') unifiFirewall = firewall.value;
	// 	if (dnsPolicies.status === 'fulfilled') unifiDnsPolicies = dnsPolicies.value;
	// 	if (wans.status === 'fulfilled') unifiWans = wans.value;
	// 	if (vpn.status === 'fulfilled') unifiVpn = vpn.value;
	// 	unifiFailed = {
	// 		'the UniFi status': false,
	// 		'UniFi devices': devices.status === 'rejected',
	// 		networks: networks.status === 'rejected',
	// 		'WiFi networks': wifi.status === 'rejected',
	// 		'firewall policies': firewall.status === 'rejected',
	// 		'DNS policies': dnsPolicies.status === 'rejected',
	// 		'WAN interfaces': wans.status === 'rejected',
	// 		'VPN tunnels': vpn.status === 'rejected',
	// 	};
	// 	unifiLoading = false;
	// }
	//
	// async function fetchAll() {
	// 	loading = true;
	// 	await Promise.all([
	// 		fetchBridgeAndCapture(),
	// 		fetchLogstash(),
	// 		fetchOpenSearch(),
	// 		fetchStorage(),
	// 		fetchToolRates(),
	// 		fetchUnifi(),
	// 	]);
	// 	loading = false;
	// }
	// OLD CODE END

	// ─── Poll groups (page refresh contract, PLAN §5.5) ─────────
	// Each group keeps its old cadence and has its own load guard, so a slow OpenSearch reply is
	// never superseded (and starved) by the bridge's 10 s tick, and nothing writes after unmount
	type GroupKey = 'capture' | 'pipeline' | 'unifi' | 'storage';
	type Settled = PromiseSettledResult<unknown>;
	const GROUPS: GroupKey[] = ['capture', 'pipeline', 'unifi', 'storage'];
	const PERIOD_MS: Record<GroupKey, number> = { capture: 10_000, pipeline: 15_000, unifi: 30_000, storage: 60_000 };
	const TICK_MS = 5_000;
	const guards: Record<GroupKey, LoadGuard> = {
		capture: createLoadGuard(),
		pipeline: createLoadGuard(),
		unifi: createLoadGuard(),
		storage: createLoadGuard(),
	};
	const startedAt: Record<GroupKey, number> = { capture: -Infinity, pipeline: -Infinity, unifi: -Infinity, storage: -Infinity };
	const inFlight = new Set<GroupKey>();

	/** Bridge health and the capture counters, mode and health. Null when a newer load took over. */
	async function loadCapture(gen: number): Promise<Settled[] | null> {
		const results = await Promise.allSettled([getBridgeHealth(), getCaptureStats(), getCaptureMode(), getCaptureHealth()]);
		if (!guards.capture.current(gen)) return null;
		const [bh, cs, cm, ch] = results;
		settle('bridge health', bh, (v) => (bridgeHealth = v));
		settle('capture counters', cs, (v) => (captureStats = v));
		settle('capture mode', cm, (v) => (captureMode = v));
		settle('capture health', ch, (v) => (captureHealth = v));
		return results;
	}

	/** Logstash, OpenSearch and the Zeek and Suricata rates over the last 5 minutes. */
	async function loadPipeline(gen: number): Promise<Settled[] | null> {
		const WINDOW_SECS = 300; // 5-minute window
		const to = new Date();
		const range = { from: new Date(to.getTime() - WINDOW_SECS * 1000).toISOString(), to: to.toISOString() };
		const perSec = (count: number) => Math.round((count / WINDOW_SECS) * 10) / 10;
		const [stats, pipelines, cl, idx, tmpl, conns, alerts] = await Promise.allSettled([
			getLogstashStats(),
			getLogstashPipelines(),
			getOpenSearchCluster(),
			getOpenSearchIndices(),
			getOpenSearchTemplates(),
			getTrafficSummary(range),
			getAlertCount(range),
		]);
		if (!guards.pipeline.current(gen)) return null;
		settle('Logstash stats', stats, (v) => (logstashStats = v));
		if (stats.status === 'fulfilled' && stats.value) {
			const now = { count: stats.value.events_in, at: performance.now() };
			const prev = lastEventsIn;
			eventsInRate = prev && now.count >= prev.count && now.at > prev.at ? (now.count - prev.count) / ((now.at - prev.at) / 1000) : null;
			lastEventsIn = now;
		}
		if (pipelines.status === 'fulfilled') logstashPipelines = pipelines.value;
		settle('OpenSearch cluster', cl, (v) => (cluster = v));
		settle('OpenSearch indices', idx, (v) => (indices = v?.indices ?? []));
		if (tmpl.status === 'fulfilled') templates = Array.isArray(tmpl.value) ? tmpl.value : [];
		// a failed rate read keeps the last rate (or '--' before the first)
		if (conns.status === 'fulfilled') zeekEventsPerSec = perSec(conns.value.connection_count);
		if (alerts.status === 'fulfilled') suricataAlertsPerSec = perSec(alerts.value.counts.total);
		// the pipelines and templates getters answer [] when they fail, so they can't count
		return [stats, cl, idx, conns, alerts];
	}

	/** System health (uptime) and disk use. */
	async function loadStorage(gen: number): Promise<Settled[] | null> {
		const results = await Promise.allSettled([getSystemHealth(), getStorageStatus()]);
		if (!guards.storage.current(gen)) return null;
		const [health, storage] = results;
		settle('system health', health, (v) => (systemHealth = v));
		settle('storage', storage, (v) => (storageStatus = v));
		return results;
	}

	/** The UniFi status, and its lists once a controller is configured. */
	async function loadUnifi(gen: number): Promise<Settled[] | null> {
		const [statusResult] = await Promise.allSettled([getUnifiStatus()]);
		if (!guards.unifi.current(gen)) return null;
		// an older load that went stale mid-lists returned without clearing this
		unifiLoading = false;
		if (statusResult.status === 'rejected') {
			// keep the last status (and the cards it shows); the notice says it is stale
			unifiFailed = { ...unifiFailed, 'the UniFi status': true };
			return [statusResult];
		}
		const status = statusResult.value;
		unifiStatus = status;
		unifiFailed = { ...unifiFailed, 'the UniFi status': false };
		if (!status.configured) return [statusResult];
		unifiLoading = true;
		const lists = await Promise.allSettled([
			getUnifiDevices(),
			getUnifiNetworks(),
			getUnifiWifi(),
			getUnifiFirewall(),
			getUnifiDnsPolicies(),
			getUnifiWans(),
			getUnifiVpn(),
		]);
		if (!guards.unifi.current(gen)) return null;
		const [devices, networks, wifi, firewall, dnsPolicies, wans, vpn] = lists;
		if (devices.status === 'fulfilled') unifiDevices = devices.value;
		if (networks.status === 'fulfilled') unifiNetworks = networks.value;
		if (wifi.status === 'fulfilled') unifiWifi = wifi.value;
		if (firewall.status === 'fulfilled') unifiFirewall = firewall.value;
		if (dnsPolicies.status === 'fulfilled') unifiDnsPolicies = dnsPolicies.value;
		if (wans.status === 'fulfilled') unifiWans = wans.value;
		if (vpn.status === 'fulfilled') unifiVpn = vpn.value;
		unifiFailed = {
			'the UniFi status': false,
			'UniFi devices': devices.status === 'rejected',
			networks: networks.status === 'rejected',
			'WiFi networks': wifi.status === 'rejected',
			'firewall policies': firewall.status === 'rejected',
			'DNS policies': dnsPolicies.status === 'rejected',
			'WAN interfaces': wans.status === 'rejected',
			'VPN tunnels': vpn.status === 'rejected',
		};
		unifiLoading = false;
		return [statusResult, ...lists];
	}

	const LOADERS: Record<GroupKey, (gen: number) => Promise<Settled[] | null>> = {
		capture: loadCapture,
		pipeline: loadPipeline,
		unifi: loadUnifi,
		storage: loadStorage,
	};

	async function runGroup(key: GroupKey): Promise<Settled[] | null> {
		const gen = guards[key].begin();
		startedAt[key] = Date.now();
		inFlight.add(key);
		try {
			return await LOADERS[key](gen);
		} finally {
			// a newer load of this group owns the flag now
			if (guards[key].current(gen)) inFlight.delete(key);
		}
	}

	// true only while the poll timer calls refresh.run(); every other call starts all groups
	let timerTick = false;

	/**
	 * The page loader. A timer tick starts the groups that are due and not already in flight; the
	 * first load and the top bar's Refresh start them all. The result covers the requests it started.
	 */
	async function load(): Promise<LoadResult> {
		const now = Date.now();
		const due = timerTick
			? GROUPS.filter((k) => !inFlight.has(k) && now - startedAt[k] >= PERIOD_MS[k] - TICK_MS / 2)
			: GROUPS;
		if (due.length === 0) return 'skipped';
		const outcomes = await Promise.all(due.map((k) => runGroup(k)));
		if (outcomes.every((o) => o === null)) return 'skipped';
		const settled = outcomes.flatMap((o) => o ?? []);
		// OLD CODE START — counted by hand; outcome() in pageRefresh is the shared rule
		// const failed = settled.filter((r) => r.status === 'rejected').length;
		// return failed === 0 ? 'ok' : failed === settled.length ? 'failed' : 'partial';
		// OLD CODE END
		return outcome(settled);
	}

	// the groups' own guards gate every write, so the loader doesn't take the shared guard
	const refresh = registerPageRefresh(load);

	// OLD CODE START — always-visible stage cards replace the node selection, and DataTable (which sorts every
	// column, with the same comparisons as sortValue) replaces the hand-rolled sorts
	// // ─── Node selection ─────────────────────────────────────────
	// function selectNode(node: NodeId) {
	// 	selectedNode = selectedNode === node ? null : node;
	// }
	//
	// function closeDetail() {
	// 	selectedNode = null;
	// }
	//
	// // ─── Sort state — Index table ───────────────────────────────
	// type IndexSortKey = 'health' | 'index' | 'docs' | 'pri_size' | 'total_size' | 'created';
	// let indexSortKey = $state<IndexSortKey>('index');
	// let indexSortDir = $state<'asc' | 'desc'>('asc');
	//
	// function toggleIndexSort(key: IndexSortKey) {
	// 	if (indexSortKey === key) { indexSortDir = indexSortDir === 'asc' ? 'desc' : 'asc'; }
	// 	else { indexSortKey = key; indexSortDir = 'asc'; }
	// }
	//
	// function indexSortIndicator(key: IndexSortKey): string {
	// 	if (indexSortKey !== key) return '';
	// 	return indexSortDir === 'asc' ? ' \u2191' : ' \u2193';
	// }
	//
	// // red is worst, so the first (descending) click puts it on top
	// const HEALTH_RANK: Record<string, number> = { red: 2, yellow: 1, green: 0 };
	//
	// let sortedIndices = $derived.by(() => {
	// 	if (!Array.isArray(indices) || indices.length === 0) return indices;
	// 	const list = [...indices];
	// 	list.sort((a, b) => {
	// 		let cmp = 0;
	// 		switch (indexSortKey) {
	// 			// OLD CODE START — sizes compared as text ("100mb" above "1.2gb") and health alphabetically
	// 			// case 'health': cmp = (a.health || '').localeCompare(b.health || ''); break;
	// 			// case 'index': cmp = (a.index ?? '').localeCompare(b.index ?? ''); break;
	// 			// case 'docs': cmp = (Number(a.docs_count) || 0) - (Number(b.docs_count) || 0); break;
	// 			// case 'pri_size': cmp = (a.pri_store_size ?? '').localeCompare(b.pri_store_size ?? ''); break;
	// 			// case 'total_size': cmp = (a.store_size ?? '').localeCompare(b.store_size ?? ''); break;
	// 			// case 'created': cmp = (a.creation_date ?? '').localeCompare(b.creation_date ?? ''); break;
	// 			// OLD CODE END
	// 			case 'health': cmp = (HEALTH_RANK[a.health] ?? -1) - (HEALTH_RANK[b.health] ?? -1); break;
	// 			case 'index': cmp = compareValues(a.index ?? '', b.index ?? ''); break;
	// 			case 'docs': cmp = (Number(a.docs_count) || 0) - (Number(b.docs_count) || 0); break;
	// 			case 'pri_size': cmp = (byteSize(a.pri_store_size) ?? -1) - (byteSize(b.pri_store_size) ?? -1); break;
	// 			case 'total_size': cmp = (byteSize(a.store_size) ?? -1) - (byteSize(b.store_size) ?? -1); break;
	// 			case 'created': cmp = compareValues(a.creation_date ?? '', b.creation_date ?? ''); break;
	// 		}
	// 		return indexSortDir === 'asc' ? cmp : -cmp;
	// 	});
	// 	return list;
	// });
	//
	// // ─── Sort state — Pipeline table ────────────────────────────
	// type PipelineSortKey = 'name' | 'events_in' | 'events_out' | 'duration';
	// let pipelineSortKey = $state<PipelineSortKey>('name');
	// let pipelineSortDir = $state<'asc' | 'desc'>('asc');
	//
	// function togglePipelineSort(key: PipelineSortKey) {
	// 	if (pipelineSortKey === key) { pipelineSortDir = pipelineSortDir === 'asc' ? 'desc' : 'asc'; }
	// 	else { pipelineSortKey = key; pipelineSortDir = 'asc'; }
	// }
	//
	// function pipelineSortIndicator(key: PipelineSortKey): string {
	// 	if (pipelineSortKey !== key) return '';
	// 	return pipelineSortDir === 'asc' ? ' \u2191' : ' \u2193';
	// }
	//
	// let sortedPipelines = $derived.by(() => {
	// 	if (logstashPipelines.length === 0) return logstashPipelines;
	// 	const list = [...logstashPipelines];
	// 	list.sort((a, b) => {
	// 		let cmp = 0;
	// 		switch (pipelineSortKey) {
	// 			// OLD CODE START — text order put pipeline 10 before 9
	// 			// case 'name': cmp = (a.id ?? '').localeCompare(b.id ?? ''); break;
	// 			// OLD CODE END
	// 			case 'name': cmp = compareValues(a.id ?? '', b.id ?? ''); break;
	// 			case 'events_in': cmp = (a.events_in ?? 0) - (b.events_in ?? 0); break;
	// 			case 'events_out': cmp = (a.events_out ?? 0) - (b.events_out ?? 0); break;
	// 			case 'duration': cmp = (a.duration_in_millis ?? 0) - (b.duration_in_millis ?? 0); break;
	// 		}
	// 		return pipelineSortDir === 'asc' ? cmp : -cmp;
	// 	});
	// 	return list;
	// });
	//
	// // ─── Sort state — Templates table ───────────────────────────
	// type TemplateSortKey = 'name' | 'patterns' | 'order';
	// let templateSortKey = $state<TemplateSortKey>('name');
	// let templateSortDir = $state<'asc' | 'desc'>('asc');
	//
	// function toggleTemplateSort(key: TemplateSortKey) {
	// 	if (templateSortKey === key) { templateSortDir = templateSortDir === 'asc' ? 'desc' : 'asc'; }
	// 	else { templateSortKey = key; templateSortDir = 'asc'; }
	// }
	//
	// function templateSortIndicator(key: TemplateSortKey): string {
	// 	if (templateSortKey !== key) return '';
	// 	return templateSortDir === 'asc' ? ' \u2191' : ' \u2193';
	// }
	//
	// let sortedTemplates = $derived.by(() => {
	// 	if (!Array.isArray(templates) || templates.length === 0) return templates;
	// 	const list = [...templates] as any[];
	// 	list.sort((a, b) => {
	// 		let cmp = 0;
	// 		switch (templateSortKey) {
	// 			// OLD CODE START — text order instead of reading order for numbers in names
	// 			// case 'name': cmp = (a.name ?? '').localeCompare(b.name ?? ''); break;
	// 			// case 'patterns':
	// 			// 	cmp = String(Array.isArray(a.index_patterns) ? a.index_patterns.join(', ') : a.index_patterns ?? '')
	// 			// 		.localeCompare(String(Array.isArray(b.index_patterns) ? b.index_patterns.join(', ') : b.index_patterns ?? ''));
	// 			// 	break;
	// 			// OLD CODE END
	// 			case 'name': cmp = compareValues(a.name ?? '', b.name ?? ''); break;
	// 			case 'patterns':
	// 				cmp = compareValues(
	// 					String(Array.isArray(a.index_patterns) ? a.index_patterns.join(', ') : a.index_patterns ?? ''),
	// 					String(Array.isArray(b.index_patterns) ? b.index_patterns.join(', ') : b.index_patterns ?? '')
	// 				);
	// 				break;
	// 			case 'order': cmp = (a.order ?? a.priority ?? 0) - (b.order ?? b.priority ?? 0); break;
	// 		}
	// 		return templateSortDir === 'asc' ? cmp : -cmp;
	// 	});
	// 	return list;
	// });
	//
	// // ─── Sort state — UniFi Devices table ──────────────────────
	// type UnifiDeviceSortKey = 'name' | 'model' | 'ipAddress' | 'state' | 'firmwareVersion';
	// let unifiDeviceSortKey = $state<UnifiDeviceSortKey>('name');
	// let unifiDeviceSortDir = $state<'asc' | 'desc'>('asc');
	//
	// function toggleUnifiDeviceSort(key: UnifiDeviceSortKey) {
	// 	if (unifiDeviceSortKey === key) { unifiDeviceSortDir = unifiDeviceSortDir === 'asc' ? 'desc' : 'asc'; }
	// 	else { unifiDeviceSortKey = key; unifiDeviceSortDir = 'asc'; }
	// }
	//
	// function unifiDeviceSortIndicator(key: UnifiDeviceSortKey): string {
	// 	if (unifiDeviceSortKey !== key) return '';
	// 	return unifiDeviceSortDir === 'asc' ? ' \u2191' : ' \u2193';
	// }
	//
	// let sortedUnifiDevices = $derived.by(() => {
	// 	if (unifiDevices.length === 0) return unifiDevices;
	// 	const list = [...unifiDevices];
	// 	list.sort((a, b) => {
	// 		let cmp = 0;
	// 		switch (unifiDeviceSortKey) {
	// 			// OLD CODE START — text order put 192.168.1.10 before 192.168.1.9 and firmware 7.10 before 7.9
	// 			// case 'name': cmp = (a.name ?? '').localeCompare(b.name ?? ''); break;
	// 			// case 'model': cmp = (a.model ?? '').localeCompare(b.model ?? ''); break;
	// 			// case 'ipAddress': cmp = (a.ipAddress ?? '').localeCompare(b.ipAddress ?? ''); break;
	// 			// case 'state': cmp = (a.state ?? '').localeCompare(b.state ?? ''); break;
	// 			// case 'firmwareVersion': cmp = (a.firmwareVersion ?? '').localeCompare(b.firmwareVersion ?? ''); break;
	// 			// OLD CODE END
	// 			case 'name': cmp = compareValues(a.name ?? '', b.name ?? ''); break;
	// 			case 'model': cmp = compareValues(a.model ?? '', b.model ?? ''); break;
	// 			case 'ipAddress': cmp = compareValues(a.ipAddress ?? '', b.ipAddress ?? ''); break;
	// 			case 'state': cmp = compareValues(a.state ?? '', b.state ?? ''); break;
	// 			case 'firmwareVersion': cmp = compareValues(a.firmwareVersion ?? '', b.firmwareVersion ?? ''); break;
	// 		}
	// 		return unifiDeviceSortDir === 'asc' ? cmp : -cmp;
	// 	});
	// 	return list;
	// });
	// OLD CODE END

	// ─── Table columns (DataTable sorts every column) ───────────
	// red is worst, so the first (descending) click puts it on top
	const HEALTH_RANK: Record<string, number> = { red: 2, yellow: 1, green: 0 };

	interface IndexTemplate {
		name?: string;
		index_patterns?: string[] | string;
		order?: number | string;
		priority?: number | string;
	}
	const templatePatterns = (t: IndexTemplate) =>
		Array.isArray(t.index_patterns) ? t.index_patterns.join(', ') : (t.index_patterns ?? '');
	const templateRows = $derived(templates as IndexTemplate[]);

	const indexColumns: Column<OpenSearchIndex>[] = [
		{ key: 'health', label: 'Health', sortValue: (i) => HEALTH_RANK[i.health] ?? -1, cell: indexHealthCell },
		{ key: 'index', label: 'Index name', cell: indexNameCell },
		{ key: 'docs', label: 'Docs', numeric: true, sortValue: (i) => Number(i.docs_count) || 0, cell: indexDocsCell },
		// OLD CODE START — 2026-11-06 (NET-166): sizes were OpenSearch's text, parsed back to 1024-based bytes
		// { key: 'pri_size', label: 'Primary size', numeric: true, sortValue: (i) => byteSize(i.pri_store_size) ?? -1, cell: priSizeCell },
		// { key: 'total_size', label: 'Total size', numeric: true, sortValue: (i) => byteSize(i.store_size) ?? -1, cell: totalSizeCell },
		// OLD CODE END
		// bytes; an unknown (null) size sorts last both ways
		{ key: 'pri_size', label: 'Primary size', numeric: true, sortValue: (i) => i.pri_store_size, cell: priSizeCell },
		{ key: 'total_size', label: 'Total size', numeric: true, sortValue: (i) => i.store_size, cell: totalSizeCell },
	];

	const pipelineColumns: Column<LogstashPipeline>[] = [
		{ key: 'id', label: 'Pipeline', sortValue: (p) => p.id ?? '', cell: pipelineIdCell },
		{ key: 'events_in', label: 'Events in', numeric: true, sortValue: (p) => p.events_in ?? 0, cell: eventsInCell },
		{ key: 'events_out', label: 'Events out', numeric: true, sortValue: (p) => p.events_out ?? 0, cell: eventsOutCell },
		{ key: 'duration', label: 'Duration', numeric: true, sortValue: (p) => p.duration_in_millis ?? 0, cell: durationCell },
	];

	const templateColumns: Column<IndexTemplate>[] = [
		{ key: 'name', label: 'Name', sortValue: (t) => t.name ?? '', cell: templateNameCell },
		{ key: 'patterns', label: 'Index patterns', sortValue: templatePatterns, cell: templatePatternsCell },
		{ key: 'order', label: 'Order', numeric: true, sortValue: (t) => t.order ?? t.priority ?? 0, cell: templateOrderCell },
	];

	const unifiDeviceColumns: Column<UnifiDevice>[] = [
		{ key: 'name', label: 'Name', sortValue: (d) => d.name ?? '', cell: deviceNameCell },
		{ key: 'type', label: 'Type', sortValue: (d) => unifiDeviceType(d), cell: deviceTypeCell },
		{ key: 'model', label: 'Model', sortValue: (d) => d.model ?? '', cell: deviceModelCell },
		{ key: 'ipAddress', label: 'IP', sortValue: (d) => d.ipAddress ?? '', cell: deviceIpCell },
		{ key: 'state', label: 'Status', sortValue: (d) => d.state ?? '', cell: deviceStateCell },
		{ key: 'firmwareVersion', label: 'Firmware', sortValue: (d) => d.firmwareVersion ?? '', cell: deviceFirmwareCell },
	];

	/** The network's management type: the official API's `management`, not in the typed fields. */
	const networkType = (n: UnifiNetwork) => String(n.management ?? '');
	const networkEnabled = (n: UnifiNetwork) => n.enabled !== false;
	const networkColumns: Column<UnifiNetwork>[] = [
		{ key: 'name', label: 'Name', sortValue: (n) => n.name ?? '', cell: networkNameCell },
		{ key: 'vlanId', label: 'VLAN ID', numeric: true, cell: networkVlanCell },
		{ key: 'type', label: 'Type', sortValue: networkType, cell: networkTypeCell },
		{ key: 'status', label: 'Status', sortValue: (n) => (networkEnabled(n) ? 'Enabled' : 'Disabled'), cell: networkStatusCell },
	];

	/** "2.4 / 5 GHz" from the official API's frequency list, or the legacy band field. */
	function wifiBand(ssid: UnifiWifi): string {
		const freqs = ssid.broadcastingFrequenciesGHz;
		if (Array.isArray(freqs) && freqs.length > 0) return `${[...freqs].sort((a: number, b: number) => a - b).join(' / ')} GHz`;
		return ssid.band || '--';
	}
	const wifiSecurity = (ssid: UnifiWifi) =>
		(ssid.securityConfiguration as { type?: string } | undefined)?.type || ssid.security || '';
	const wifiColumns: Column<UnifiWifi>[] = [
		{ key: 'name', label: 'SSID', sortValue: (s) => s.name ?? '', cell: wifiNameCell },
		{ key: 'band', label: 'Band', sortValue: wifiBand, cell: wifiBandCell },
		{ key: 'security', label: 'Security', sortValue: wifiSecurity, cell: wifiSecurityCell },
		{ key: 'enabled', label: 'Enabled', sortValue: (s) => (s.enabled !== false ? 'Yes' : 'No'), cell: wifiEnabledCell },
	];

	const policyAction = (p: FirewallPolicy) => (typeof p.action === 'object' ? p.action?.type : p.action) || '';
	const policyColumns: Column<FirewallPolicy>[] = [
		{ key: 'name', label: 'Policy', sortValue: (p) => p.name || p.id, cell: policyNameCell },
		{ key: 'action', label: 'Action', sortValue: policyAction, cell: policyActionCell },
		{ key: 'enabled', label: 'Enabled', sortValue: (p) => (p.enabled ? 'Active' : 'Disabled'), cell: policyEnabledCell },
	];

	/** WAN interfaces and VPN tunnels share one shape: name, type and status. */
	type Link = UnifiWan | UnifiVpnTunnel;
	const wanColumns: Column<UnifiWan>[] = [
		{ key: 'name', label: 'Name', sortValue: (l) => l.name ?? '', cell: linkNameCell },
		{ key: 'type', label: 'Type', sortValue: (l) => l.type ?? '', cell: linkTypeCell },
		{ key: 'status', label: 'Status', sortValue: (l) => l.status ?? '', cell: wanStatusCell },
	];
	const vpnColumns: Column<UnifiVpnTunnel>[] = [
		{ key: 'name', label: 'Name', sortValue: (l) => l.name ?? '', cell: linkNameCell },
		{ key: 'type', label: 'Type', sortValue: (l) => l.type ?? '', cell: linkTypeCell },
		{ key: 'status', label: 'Status', sortValue: (l) => l.status ?? '', cell: vpnStatusCell },
	];

	// ─── Helpers — UniFi ────────────────────────────────────────
	function unifiDeviceType(device: UnifiDevice): string {
		const m = (device.model || '').toLowerCase();
		const n = (device.name || '').toLowerCase();
		// Check gateway by model name FIRST — UDM/USG/UXG are gateways even
		// though their features array may include "switching"
		if (m.includes('udm') || m.includes('usg') || m.includes('uxg') || m.includes('gateway') || n.includes('udm')) return 'Gateway';
		// Then check features array (official API returns string[])
		const feats = Array.isArray(device.features) ? device.features : [];
		if (feats.includes('accessPoint')) return 'AP';
		if (feats.includes('switching')) return 'Switch';
		if (m.includes('u6') || m.includes('u7') || m.includes('uap') || m.includes('u5') || m.startsWith('ua')) return 'AP';
		if (m.includes('usw') || m.includes('us-') || m.includes('switch')) return 'Switch';
		return 'Device';
	}

	// OLD CODE START — the type tag in the Type column names the device; the per-row icons are gone
	// function unifiDeviceIcon(device: UnifiDevice): string {
	// 	const type = unifiDeviceType(device);
	// 	if (type === 'AP') return 'wifi';
	// 	if (type === 'Switch') return 'switch';
	// 	if (type === 'Gateway') return 'gateway';
	// 	return 'device';
	// }
	// OLD CODE END

	// ─── Derived stats for quick stats bar ──────────────────────
	let eventsPerSec = $derived.by(() => {
		if (!logstashStats) return 0;
		// If we have events_in but no rate, show events_in as a proxy
		return logstashStats.events_in;
	});

	let diskUsedPercent = $derived.by(() => {
		return storageStatus?.disk_usage_percent ?? 0;
	});

	// OLD CODE START — fell back to the primary shard count, which is not an index count (#39)
	// let indexCount = $derived.by(() => {
	// 	return indices.length || cluster?.active_primary_shards || 0;
	// });
	// OLD CODE END
	let indexCount = $derived(indices.length);
	// System pages count data indices only (OpenSearch's own ".…" indices are skipped), so show the split
	let dataIndexCount = $derived(indices.filter((i) => !i.index.startsWith('.')).length);

	let latencyMs = $derived.by(() => {
		// OLD CODE START — latency_us is null when not measured
		// if (!bridgeHealth || bridgeHealth.latency_us <= 0) return 0;
		// OLD CODE END
		if (!bridgeHealth || bridgeHealth.latency_us == null || bridgeHealth.latency_us <= 0) return 0;
		return bridgeHealth.latency_us / 1000;
	});

	// OLD CODE START — NET-167: cumulative counters the managers read as 0 on error; a burst days ago
	// never left these figures
	// let dropRate = $derived.by(() => {
	// 	return captureStats?.drop_rate_pct ?? 0;
	// });
	// // S9: kernel drops + NIC misses, the count every loss figure on the page reads
	// let lost = $derived(captureStats ? packetsLost(captureStats) : 0);
	// OLD CODE END
	// NET-167: the loss figures come from the latest capture-stats request only. A failed refresh keeps
	// the other counters (settle's keep-last-good) but must not leave the old "last 58 min" standing.
	const statsRefreshFailed = $derived(failedSources['capture counters'] === true);
	const LOSS_REFRESH_FAILED: LossWords = { status: 'unknown', detail: "Couldn't refresh the loss figures", pct: null };
	const loss = $derived(!captureStats ? null : statsRefreshFailed ? LOSS_REFRESH_FAILED : lossWords(captureStats.loss_window));
	/** The validated count since the counters last reset, with its rate only when there is one. */
	const cumulativeLoss = $derived.by(() => {
		const c = statsRefreshFailed ? null : captureStats?.loss_window.cumulative;
		if (!c) return null;
		if (c.drop_rate_pct == null) return { text: formatNumber(c.lost), tone: 'none' as const };
		return {
			text: `${formatNumber(c.lost)} · ${formatLossPct(c.drop_rate_pct, c.lost)}`,
			tone: c.drop_rate_pct < 1 ? ('ok' as const) : ('medium' as const),
		};
	});

	// OLD CODE START — 2026-11-06 (S4): fell back to the bridge's time since its last state change,
	// shown as "NetTap up"
	// let uptimeSeconds = $derived.by(() => {
	// 	return systemHealth?.uptime ?? bridgeHealth?.uptime_seconds ?? 0;
	// });
	// OLD CODE END
	let uptimeSeconds = $derived(systemHealth?.uptime ?? 0);

	// ─── Logstash heap derived ──────────────────────────────────
	let heapPercent = $derived.by(() => {
		if (!logstashStats || logstashStats.heap_max_bytes <= 0) return 0;
		return (logstashStats.heap_used_bytes / logstashStats.heap_max_bytes) * 100;
	});

	// ─── Capture pipeline strip ─────────────────────────────────
	// A stage's state comes from its own reading: none yet is unknown, never "Running"
	const NO_READING = 'No reading';
	type StageState = Pick<PipelineStage, 'status' | 'detail'>;

	/** "not_configured" → "Not configured". */
	function cap(text: string): string {
		const words = text.replace(/_/g, ' ');
		return words.charAt(0).toUpperCase() + words.slice(1);
	}

	function portStage(): StageState {
		if (!captureHealth) return { status: 'unknown', detail: NO_READING };
		const link = `${captureHealth.capture_interface || captureMode?.interface || ''} ${captureHealth.link_up ? 'up' : 'down'}`;
		if (!captureHealth.link_up) return { status: 'failing', detail: link };
		return captureHealth.status === 'normal'
			? { status: 'ok', detail: link }
			: { status: 'failing', detail: `${link} · ${cap(captureHealth.status ?? 'unknown')}` };
	}

	function bridgeStage(): StageState {
		if (!bridgeHealth) return { status: 'unknown', detail: NO_READING };
		const links = `WAN ${bridgeHealth.wan_link ? 'up' : 'down'} · LAN ${bridgeHealth.lan_link ? 'up' : 'down'}`;
		const state = (bridgeHealth.bridge_state ?? 'unknown').replace(/_/g, ' ');
		return { status: bridgeHealth.bridge_state === 'up' ? 'ok' : 'failing', detail: `br0 ${state} · ${links}` };
	}

	/** NET-167: loss over 0.1 % can turn an ok capture stage failing, never the reverse. */
	function captureStage(): StageState {
		const own = captureOwnStage();
		return own.status === 'ok' && loss?.status === 'failing' ? { ...own, status: 'failing' } : own;
	}

	/** The stage from its own reading: bypass, promiscuous off or no reading decide it whatever the loss says. */
	function captureOwnStage(): StageState {
		// OLD CODE: ` · ${dropRate.toFixed(2)}% dropped` (S9: kernel drops only, and a tiny loss read 0.00%)
		// OLD CODE: ` · ${formatLossPct(dropRate, lost)} lost` (NET-167: since the counters reset, not recent)
		const drop = loss ? ` · ${loss.detail}` : '';
		if (isMirror || isGateway) {
			if (!captureHealth) return { status: 'unknown', detail: NO_READING + drop };
			return captureHealth.promisc_enabled
				? { status: 'ok', detail: `Promiscuous${drop}` }
				: { status: 'failing', detail: `Not promiscuous${drop}` };
		}
		if (!bridgeHealth) return { status: 'unknown', detail: NO_READING + drop };
		return bridgeHealth.bypass_active
			? { status: 'failing', detail: `Bypass${drop}` }
			: { status: 'ok', detail: `Promiscuous${drop}` };
	}

	function rateStage(rate: number | null, unit: string): StageState {
		if (rate == null) return { status: 'unknown', detail: NO_READING };
		// logs arriving in the last 5 minutes prove the stage runs; none proves nothing
		return { status: rate > 0 ? 'ok' : 'unknown', detail: `${formatNumber(rate)} ${unit}` };
	}

	// OLD CODE START — 2026-11-06 (S8): "Shipping" from Logstash's events-since-start counter, which
	// stays above 0 long after shipping stops
	// function filebeatStage(): StageState {
	// 	if (!logstashStats) return { status: 'unknown', detail: NO_READING };
	// 	return logstashStats.events_in > 0
	// 		? { status: 'ok', detail: `Shipping · ${formatNumber(logstashStats.events_in)} events` }
	// 		: { status: 'failing', detail: 'Idle' };
	// }
	// OLD CODE END
	function filebeatStage(): StageState {
		if (!logstashStats) return { status: 'unknown', detail: NO_READING };
		if (eventsInRate == null) return { status: 'unknown', detail: 'Measuring…' };
		// events arriving between two polls prove shipping; none proves nothing (rateStage's rule)
		return eventsInRate > 0
			? { status: 'ok', detail: `Shipping · ${formatEventRate(eventsInRate)} into Logstash` }
			: { status: 'unknown', detail: 'No new events since the last check' };
	}

	const formatEventRate = (rate: number) => `${rate < 10 ? rate.toFixed(1) : formatNumber(Math.round(rate))} events/s`;

	function logstashStage(): StageState {
		if (!logstashStats) return { status: 'unknown', detail: NO_READING };
		return { status: 'ok', detail: `Processing · heap ${heapPercent.toFixed(0)}%` };
	}

	function opensearchStage(): StageState {
		if (!cluster?.status) return { status: 'unknown', detail: NO_READING };
		const count = indices.length > 0 ? ` · ${indices.length} indices` : '';
		return { status: cluster.status === 'green' ? 'ok' : 'failing', detail: cap(cluster.status) + count };
	}

	const stages = $derived<PipelineStage[]>([
		isMirror || isGateway
			? { key: 'port', label: portName, ...portStage() }
			: { key: 'bridge', label: 'Bridge', ...bridgeStage() },
		{ key: 'capture', label: 'Capture', ...captureStage() },
		{ key: 'zeek', label: 'Zeek', ...rateStage(zeekEventsPerSec, 'conn/s') },
		{ key: 'suricata', label: 'Suricata', ...rateStage(suricataAlertsPerSec, 'alerts/s') },
		{ key: 'filebeat', label: 'Filebeat', ...filebeatStage() },
		{ key: 'logstash', label: 'Logstash', ...logstashStage() },
		{ key: 'opensearch', label: 'OpenSearch', ...opensearchStage() },
	]);

	const pipelineSub = $derived(
		uptimeSeconds > 0
			? `Health of each stage, checked every 10 to 15 s · appliance up ${formatUptime(uptimeSeconds)}`
			: 'Health of each stage, checked every 10 to 15 s',
	);

	const captureSub = $derived(
		captureMode?.mode === 'mirror'
			? 'Mirror (SPAN) mode'
			: captureMode?.mode === 'dhcp_gateway'
				? `DHCP gateway on ${captureMode.interface || 'the LAN port'}`
				: 'Promiscuous mode on br0 · bridge capture',
	);

	const opensearchSub = $derived(
		!cluster
			? 'Cluster status unknown'
			: failedSources['OpenSearch indices']
				? "Single-node cluster; its index list couldn't be loaded"
				: `Single-node cluster with ${indices.length} active indices`,
	);

	/** The source hasn't answered yet (no success and no failure recorded). */
	const pending = (name: string) => failedSources[name] === undefined;
	/** A health word's tone for the .res mark: normal, degraded, anything else. */
	const healthTone = (status: string | undefined) =>
		status === 'normal' || status === 'green' ? 'ok' : status === 'degraded' || status === 'yellow' ? 'medium' : 'high';

	// OLD CODE START — the hand-drawn SVG topology is replaced by the Pipeline strip
	// // ─── SVG connection drawing ─────────────────────────────────
	// const NS = 'http://www.w3.org/2000/svg';
	//
	// function nodeRight(id: string): { x: number; y: number } {
	// 	const wrapper = document.querySelector('.topology-wrapper');
	// 	const el = document.getElementById(id);
	// 	if (!wrapper || !el) return { x: 0, y: 0 };
	// 	const wr = wrapper.getBoundingClientRect();
	// 	const er = el.getBoundingClientRect();
	// 	return { x: er.right - wr.left, y: er.top - wr.top + er.height / 2 };
	// }
	//
	// function nodeLeft(id: string): { x: number; y: number } {
	// 	const wrapper = document.querySelector('.topology-wrapper');
	// 	const el = document.getElementById(id);
	// 	if (!wrapper || !el) return { x: 0, y: 0 };
	// 	const wr = wrapper.getBoundingClientRect();
	// 	const er = el.getBoundingClientRect();
	// 	return { x: er.left - wr.left, y: er.top - wr.top + er.height / 2 };
	// }
	//
	// function bezier(from: { x: number; y: number }, to: { x: number; y: number }): string {
	// 	const dx = (to.x - from.x) * 0.45;
	// 	return `M ${from.x},${from.y} C ${from.x + dx},${from.y} ${to.x - dx},${to.y} ${to.x},${to.y}`;
	// }
	//
	// function drawConn(svg: Element, from: { x: number; y: number }, to: { x: number; y: number }, lineClass: string, particleClass: string, speed: string) {
	// 	const d = bezier(from, to);
	// 	const line = document.createElementNS(NS, 'path');
	// 	line.setAttribute('d', d);
	// 	line.setAttribute('class', `conn-line ${lineClass}`);
	// 	svg.appendChild(line);
	// 	const particles = document.createElementNS(NS, 'path');
	// 	particles.setAttribute('d', d);
	// 	particles.setAttribute('class', `conn-particles ${particleClass} speed-${speed}`);
	// 	svg.appendChild(particles);
	// }
	//
	// function drawConnections() {
	// 	const svg = document.getElementById('connSvg');
	// 	if (!svg) return;
	// 	while (svg.firstChild) svg.removeChild(svg.firstChild);
	//
	// 	const wrapper = document.querySelector('.topology-wrapper');
	// 	if (!wrapper) return;
	// 	const wr = wrapper.getBoundingClientRect();
	// 	svg.setAttribute('viewBox', `0 0 ${wr.width} ${wr.height}`);
	// 	(svg as HTMLElement).style.width = `${wr.width}px`;
	// 	(svg as HTMLElement).style.height = `${wr.height}px`;
	//
	// 	drawConn(svg, nodeRight('node-bridge'), nodeLeft('node-capture'), 'conn-cyan', 'conn-cyan-p', 'fast');
	// 	drawConn(svg, nodeRight('node-capture'), nodeLeft('node-zeek'), 'conn-green', 'conn-green-p', 'fast');
	// 	drawConn(svg, nodeRight('node-capture'), nodeLeft('node-suricata'), 'conn-red', 'conn-red-p', 'normal');
	// 	drawConn(svg, nodeRight('node-zeek'), nodeLeft('node-filebeat'), 'conn-green', 'conn-green-p', 'fast');
	// 	drawConn(svg, nodeRight('node-suricata'), nodeLeft('node-filebeat'), 'conn-red', 'conn-red-p', 'slow');
	// 	drawConn(svg, nodeRight('node-filebeat'), nodeLeft('node-logstash'), 'conn-cyan', 'conn-cyan-p', 'normal');
	// 	drawConn(svg, nodeRight('node-logstash'), nodeLeft('node-opensearch'), 'conn-cyan', 'conn-cyan-p', 'fast');
	// }
	// OLD CODE END

	// ─── Lifecycle & auto-polling ───────────────────────────────
	// Grafana is off by default (compose profile "grafana"); link it only when it answers
	let grafanaUp = $state(false);

	// OLD CODE START — one poll timer through the page loader (it keeps the four cadences); with every stage card
	// shown there is no detail panel for Escape to close, and no topology to redraw on resize
	// onMount(() => {
	// 	// A logged-out request is redirected to the login page (HTML, 200), so check the JSON
	// 	fetch('/grafana/api/health')
	// 		.then((r) => (r.ok ? r.json() : null))
	// 		.then((j) => (grafanaUp = j?.database === 'ok'))
	// 		.catch(() => (grafanaUp = false));
	// 	fetchAll();
	// 	// cleared on unmount: it touches `document`, which is gone once the page is torn down
	// 	const drawTimer = setTimeout(drawConnections, 100);
	// 	return () => clearTimeout(drawTimer);
	// });
	//
	// // Auto-poll with $effect
	// $effect(() => {
	// 	// Bridge + capture: every 10s
	// 	const bridgeInterval = setInterval(fetchBridgeAndCapture, 10_000);
	// 	// Logstash + OpenSearch: every 15s
	// 	const logstashInterval = setInterval(() => { fetchLogstash(); fetchOpenSearch(); fetchToolRates(); }, 15_000);
	// 	// Storage: every 60s
	// 	const storageInterval = setInterval(fetchStorage, 60_000);
	// 	// UniFi: every 30s
	// 	const unifiInterval = setInterval(fetchUnifi, 30_000);
	//
	// 	// Redraw connections on resize
	// 	const handleResize = () => drawConnections();
	// 	window.addEventListener('resize', handleResize);
	//
	// 	// Escape to close detail
	// 	const handleKeydown = (e: KeyboardEvent) => { if (e.key === 'Escape') closeDetail(); };
	// 	document.addEventListener('keydown', handleKeydown);
	//
	// 	return () => {
	// 		clearInterval(bridgeInterval);
	// 		clearInterval(logstashInterval);
	// 		clearInterval(storageInterval);
	// 		clearInterval(unifiInterval);
	// 		window.removeEventListener('resize', handleResize);
	// 		document.removeEventListener('keydown', handleKeydown);
	// 	};
	// });
	// OLD CODE END
	onMount(() => {
		// A logged-out request is redirected to the login page (HTML, 200), so check the JSON
		fetch('/grafana/api/health')
			.then((r) => (r.ok ? r.json() : null))
			.then((j) => (grafanaUp = j?.database === 'ok'))
			.catch(() => (grafanaUp = false));
		void refresh.run();
		// one tick for the four cadences; the loader starts the groups that are due
		const timer = setInterval(() => {
			timerTick = true;
			void refresh.run(); // reads timerTick before its first await
			timerTick = false;
		}, TICK_MS);
		return () => clearInterval(timer);
	});

	onDestroy(() => {
		refresh.unregister();
		for (const key of GROUPS) guards[key].invalidate();
	});
</script>

<svelte:head>
	<title>Infrastructure | NetTap</title>
</svelte:head>

<!-- A state word with its mark (the system's .res: ok dot, medium square, high triangle) -->
{#snippet word(text: string, tone: 'ok' | 'medium' | 'high' | 'none')}
	<span class={['res', tone === 'ok' && 'is-live', tone === 'medium' && 'is-medium', tone === 'high' && 'is-high']}
		>{text}</span
	>
{/snippet}

{#snippet diskFoot()}
	<Meter value={diskUsedPercent} label="Disk used" />
{/snippet}

<!-- Table cells -->
{#snippet indexHealthCell(i: OpenSearchIndex)}
	{#if i.health}{@render word(cap(i.health), healthTone(i.health))}{:else}--{/if}
{/snippet}
{#snippet indexNameCell(i: OpenSearchIndex)}<span class="mono">{i.index ?? '--'}</span>{/snippet}
{#snippet indexDocsCell(i: OpenSearchIndex)}{formatNumber(Number(i.docs_count))}{/snippet}
<!-- OLD CODE START — 2026-11-06 (NET-166): printed OpenSearch's rounded 1024-based text ("512kb")
{#snippet priSizeCell(i: OpenSearchIndex)}<span class="mono">{i.pri_store_size ?? '--'}</span>{/snippet}
{#snippet totalSizeCell(i: OpenSearchIndex)}<span class="mono">{i.store_size ?? '--'}</span>{/snippet}
OLD CODE END -->
{#snippet priSizeCell(i: OpenSearchIndex)}<span class="mono">{i.pri_store_size == null ? '--' : sharedFormatBytes(i.pri_store_size)}</span>{/snippet}
{#snippet totalSizeCell(i: OpenSearchIndex)}<span class="mono">{i.store_size == null ? '--' : sharedFormatBytes(i.store_size)}</span>{/snippet}

{#snippet pipelineIdCell(p: LogstashPipeline)}<span class="mono">{p.id ?? '--'}</span>{/snippet}
{#snippet eventsInCell(p: LogstashPipeline)}{formatNumber(p.events_in)}{/snippet}
{#snippet eventsOutCell(p: LogstashPipeline)}{formatNumber(p.events_out)}{/snippet}
{#snippet durationCell(p: LogstashPipeline)}{formatNumber(p.duration_in_millis)} ms{/snippet}

{#snippet templateNameCell(t: IndexTemplate)}<span class="mono">{t.name ?? '--'}</span>{/snippet}
{#snippet templatePatternsCell(t: IndexTemplate)}<span class="mono">{templatePatterns(t) || '--'}</span>{/snippet}
{#snippet templateOrderCell(t: IndexTemplate)}{t.order ?? t.priority ?? '--'}{/snippet}

{#snippet deviceNameCell(d: UnifiDevice)}{d.name || 'Unnamed'}{/snippet}
{#snippet deviceTypeCell(d: UnifiDevice)}<span class="tag">{unifiDeviceType(d)}</span>{/snippet}
{#snippet deviceModelCell(d: UnifiDevice)}<span class="mono">{d.model || '--'}</span>{/snippet}
{#snippet deviceIpCell(d: UnifiDevice)}<span class="mono">{d.ipAddress || '--'}</span>{/snippet}
{#snippet deviceStateCell(d: UnifiDevice)}
	{#if d.state === 'ONLINE'}{@render word('Online', 'ok')}{:else}{@render word(d.state || 'Unknown', 'high')}{/if}
{/snippet}
{#snippet deviceFirmwareCell(d: UnifiDevice)}
	<span class="mono">{d.firmwareVersion || '--'}</span>
	{#if d.firmwareUpdatable}<span class="chip is-warn">Update</span>{/if}
{/snippet}

{#snippet networkNameCell(n: UnifiNetwork)}{n.name || '--'}{/snippet}
{#snippet networkVlanCell(n: UnifiNetwork)}<span class="mono">{n.vlanId ?? '--'}</span>{/snippet}
{#snippet networkTypeCell(n: UnifiNetwork)}<span class="tag">{networkType(n) || '--'}</span>{/snippet}
{#snippet networkStatusCell(n: UnifiNetwork)}
	{@render word(networkEnabled(n) ? 'Enabled' : 'Disabled', networkEnabled(n) ? 'ok' : 'high')}
{/snippet}

{#snippet wifiNameCell(s: UnifiWifi)}{s.name || '--'}{/snippet}
{#snippet wifiBandCell(s: UnifiWifi)}<span class="mono">{wifiBand(s)}</span>{/snippet}
{#snippet wifiSecurityCell(s: UnifiWifi)}
	{@const sec = wifiSecurity(s).toLowerCase()}
	{@render word(
		wifiSecurity(s).replace(/_/g, ' ') || '--',
		sec.includes('wpa3') || sec.includes('wpa2') ? 'ok' : sec ? 'medium' : 'none',
	)}
{/snippet}
{#snippet wifiEnabledCell(s: UnifiWifi)}
	{@render word(s.enabled !== false ? 'Yes' : 'No', s.enabled !== false ? 'ok' : 'high')}
{/snippet}

{#snippet policyNameCell(p: FirewallPolicy)}{p.name || p.id}{/snippet}
{#snippet policyActionCell(p: FirewallPolicy)}
	{@const action = policyAction(p).toLowerCase()}
	{@render word(
		policyAction(p) || '--',
		action === 'drop' || action === 'reject' ? 'high' : action === 'allow' || action === 'accept' ? 'ok' : 'none',
	)}
{/snippet}
{#snippet policyEnabledCell(p: FirewallPolicy)}
	{@render word(p.enabled ? 'Active' : 'Disabled', p.enabled ? 'ok' : 'none')}
{/snippet}

{#snippet linkNameCell(l: Link)}{l.name || '--'}{/snippet}
{#snippet linkTypeCell(l: Link)}<span class="mono">{l.type || '--'}</span>{/snippet}
{#snippet wanStatusCell(l: Link)}
	{@const s = l.status?.toLowerCase()}
	{#if s === 'connected' || s === 'online'}{@render word(l.status, 'ok')}{:else}{@render word(l.status || 'Unknown', 'high')}{/if}
{/snippet}
{#snippet vpnStatusCell(l: Link)}
	{@const s = l.status?.toLowerCase()}
	{#if s === 'connected' || s === 'established'}{@render word(l.status, 'ok')}{:else}{@render word(l.status || 'Unknown', 'medium')}{/if}
{/snippet}

<div class="page-head">
	<div>
		<h1 class="page-title">Infrastructure</h1>
		<p class="page-sub">How traffic moves from capture to storage, checked every 10 to 60 seconds</p>
	</div>
</div>

{#if failedNames.length > 0}
	<div class="notice is-warn" role="status">
		<Icon name="warn" /><span>Couldn't load {failedNames.join(', ')}: those figures show the last reading or "--".</span>
	</div>
{/if}

<div class="grid">
	<!-- NET-192: the Capture pipeline card moved below the KPI row (page recipe: KPIs first) -->
	<KpiCard
		class="c-3"
		label="Disk used"
		icon="nas"
		value={diskUsedPercent > 0 ? diskUsedPercent.toFixed(1) : '--'}
		unit={diskUsedPercent > 0 ? '%' : undefined}
		foot={diskUsedPercent > 0 ? diskFoot : undefined}
	/>
	<KpiCard
		class="c-3"
		label="Indices"
		icon="logs"
		value={indexCount > 0 ? indexCount : '--'}
		sub={indexCount > 0 ? `${dataIndexCount} data · ${indexCount - dataIndexCount} system` : undefined}
	/>
	<!-- OLD CODE START — 2026-11-06 (S9): kernel drops only, rounded to 0.00, no scope
	<KpiCard class="c-3" label="Drop rate" icon="pcap" value={captureStats ? dropRate.toFixed(2) : '--'} unit={captureStats ? '%' : undefined} />
	OLD CODE END -->
	<!-- OLD CODE START — NET-167: the cumulative rate, labelled with LOSS_SCOPE
	<KpiCard class="c-3" label="Packet loss" icon="pcap" value={captureStats ? formatLossPct(dropRate, lost) : '--'} sub={captureStats ? LOSS_SCOPE : undefined} />
	OLD CODE END -->
	<!-- a percentage only when the window has one: zero arrivals or no window never reads 0% -->
	<KpiCard class="c-3" label="Packet loss" icon="pcap" value={loss?.pct ?? '--'} sub={loss?.detail} />
	{#if bridgeHealth && bridgeHealth.latency_us == null}
		<!-- OLD CODE: value="Not measured" sub={bridgeHealth.latency_note || undefined} (NET-192: the words wrapped at figure size) -->
		<KpiCard class="c-3" label="Latency" icon="live" value="—" sub={bridgeHealth.latency_note || 'Not measured'} />
	{:else}
		<KpiCard
			class="c-3"
			label="Latency"
			icon="live"
			value={latencyMs > 0 ? latencyMs.toFixed(1) : '--'}
			unit={latencyMs > 0 ? 'ms' : undefined}
		/>
	{/if}

	<Card title="Capture pipeline" sub={pipelineSub} class="c-12">
		<div class="pipe-wrap"><Pipeline {stages} /></div>
	</Card>

	<!-- The capture point: a mirror (SPAN) port or the DHCP gateway's LAN port, else the br0 bridge -->
	{#if isMirror || isGateway}
		<Card
			title={portName}
			sub={isGateway
				? 'Devices get their address and gateway from NetTap, which routes their traffic to the router and captures it'
				: "Receives a copy of the switch port's traffic (SPAN); NetTap is not in the traffic path"}
			class="c-6"
		>
			{#if captureHealth}
				{@const ch = captureHealth}
				<dl class="facts flush">
					<dt>Interface</dt>
					<dd class="mono">{ch.capture_interface || captureMode?.interface || '--'}</dd>
					<dt>Link</dt>
					<dd>{@render word(ch.link_up ? 'Connected' : 'Disconnected', ch.link_up ? 'ok' : 'high')}</dd>
					<dt>Promiscuous mode</dt>
					<dd>{@render word(ch.promisc_enabled ? 'Yes' : 'No', ch.promisc_enabled ? 'ok' : 'high')}</dd>
					{#if isGateway}
						<dt>Routing</dt>
						<dd>{@render word(ch.routing_active ? 'On' : 'Off', ch.routing_active ? 'ok' : 'medium')}</dd>
						<dt>DHCP server</dt>
						<dd>{@render word(ch.dhcp_server_running ? 'Running' : 'Stopped', ch.dhcp_server_running ? 'ok' : 'medium')}</dd>
						<dt>Leases</dt>
						<dd class="num">{ch.lease_count ?? '--'}</dd>
						<dt>Subnet</dt>
						<dd class="mono">{ch.subnet ?? '--'}</dd>
					{:else}
						<dt>IP on mirror port</dt>
						<!-- #96: has_ip is null when the daemon couldn't run the IP check -->
						<dd>
							{#if ch.has_ip === true}{@render word('Yes (should have none)', 'high')}
							{:else if ch.has_ip === false}{@render word('None', 'ok')}
							{:else if ch.has_ip === null}Couldn't check
							{:else}--{/if}
						</dd>
					{/if}
					<dt>Status</dt>
					<dd>{#if ch.status}{@render word(cap(ch.status), healthTone(ch.status))}{:else}--{/if}</dd>
					{#if !isGateway}
						<dt>Management port</dt>
						<dd class="mono">{ch.management_interface ?? '--'}</dd>
					{/if}
				</dl>
				{#if ch.issues?.length}
					<div class="notice is-warn card-note" role="status">
						<Icon name="warn" />
						<ul class="issues">
							{#each ch.issues as issue (issue)}<li>{issue}</li>{/each}
						</ul>
					</div>
				{/if}
			{:else if pending('capture health')}
				<CardState state="loading" title="Loading the capture port" />
			{:else}
				<CardState state="error" title={loadFailed('the capture port status')} onaction={() => void refresh.run()} />
			{/if}
		</Card>
	{:else}
		<Card title="Bridge" sub="br0 · Linux software bridge with promiscuous capture" class="c-6">
			{#if bridgeHealth}
				{@const bh = bridgeHealth}
				<dl class="facts flush">
					<dt>Bridge state</dt>
					<dd>
						{#if bh.bridge_state === 'up'}{@render word('Up', 'ok')}
						{:else if bh.bridge_state}{@render word(cap(bh.bridge_state), 'high')}
						{:else}--{/if}
					</dd>
					<dt>WAN carrier</dt>
					<dd>{@render word(bh.wan_link ? 'Connected' : 'Disconnected', bh.wan_link ? 'ok' : 'high')}</dd>
					<dt>LAN carrier</dt>
					<dd>{@render word(bh.lan_link ? 'Connected' : 'Disconnected', bh.lan_link ? 'ok' : 'high')}</dd>
					<dt>Latency</dt>
					<dd>
						{#if bh.latency_us == null}<span title={bh.latency_note || undefined}>Not measured</span>
						{:else if bh.latency_us > 0}<span class="num">{(bh.latency_us / 1000).toFixed(1)} ms</span>
						{:else}--{/if}
					</dd>
					<!-- OLD CODE: RX/TX traffic = formatBytes(bh.rx_bytes_delta), bytes over an unstated interval (S12) -->
					<dt>RX rate</dt>
					<dd class="num">{byteRate(bh.rx_bytes_per_sec)}</dd>
					<dt>TX rate</dt>
					<dd class="num">{byteRate(bh.tx_bytes_per_sec)}</dd>
					<dt>Promiscuous mode</dt>
					<dd>{bh.bypass_active ? 'No (bypass)' : 'Yes'}</dd>
					<dt>Bypass mode</dt>
					<dd>{bh.bypass_active ? 'Active' : 'Inactive'}</dd>
				</dl>
			{:else if pending('bridge health')}
				<CardState state="loading" title="Loading the bridge" />
			{:else}
				<CardState state="error" title={loadFailed('the bridge status')} onaction={() => void refresh.run()} />
			{/if}
		</Card>
	{/if}

	<Card title="Packet capture" sub={captureSub} class="c-6">
		{#if captureStats || captureMode}
			<dl class="facts flush">
				<dt>Capture mode</dt>
				<dd>{captureMode?.mode === 'mirror' ? 'Mirror' : captureMode?.mode === 'dhcp_gateway' ? 'DHCP gateway' : 'Bridge'}</dd>
				<dt>Interface</dt>
				<!-- a DHCP gateway box has no br0 to fall back to (CR-247) -->
				<dd class="mono">
					{captureStats?.capture_interface || captureMode?.interface || (captureMode?.mode === 'dhcp_gateway' ? '--' : 'br0')}
				</dd>
				<dt>RX packets</dt>
				<dd class="num">{formatNumber(captureStats?.rx_packets)}</dd>
				<dt>TX packets</dt>
				<dd class="num">{formatNumber(captureStats?.tx_packets)}</dd>
				<!-- OLD CODE: Drop rate = `${dropRate.toFixed(2)}%` (S9: kernel drops only) -->
				<!-- OLD CODE START — NET-167: the managers' rx_* counters, which read 0 when unreadable
				<dt title={LOSS_SCOPE}>Packets lost</dt>
				<dd>{#if captureStats}{@render word(`${formatNumber(lost)} · ${formatLossPct(dropRate, lost)}`, dropRate < 1 ? 'ok' : 'medium')}{:else}--{/if}</dd>
				OLD CODE END -->
				<dt title={LOSS_SCOPE}>Packets lost since the counters reset</dt>
				<dd>{#if cumulativeLoss}{@render word(cumulativeLoss.text, cumulativeLoss.tone)}{:else}Unavailable{/if}</dd>
				<dt>Link speed</dt>
				<dd class="num">
					{captureStats && captureStats.link_speed_mbps > 0 ? `${formatNumber(captureStats.link_speed_mbps)} Mbps` : '--'}
				</dd>
			</dl>
		{:else if pending('capture counters') || pending('capture mode')}
			<CardState state="loading" title="Loading the capture counters" />
		{:else}
			<CardState state="error" title={loadFailed('the packet counters')} onaction={() => void refresh.run()} />
		{/if}
	</Card>

	<Card title="Zeek network analyser" sub="Structured metadata logs · conn, dns, http, tls, files, dhcp, smtp" class="c-4">
		<dl class="facts flush">
			<dt>Connections per second</dt>
			<dd class="num">{zeekEventsPerSec != null ? formatNumber(zeekEventsPerSec) : '--'}</dd>
			<dt>Window</dt>
			<dd>Last 5 minutes</dd>
			<dt>Log types</dt>
			<dd class="mono">conn, dns, http, tls, files, dhcp</dd>
			<dt>Output</dt>
			<dd class="mono">JSON logs → Filebeat</dd>
		</dl>
	</Card>

	<Card title="Suricata IDS" sub="Signature and anomaly-based intrusion detection" class="c-4">
		<dl class="facts flush">
			<dt>Alerts per second</dt>
			<dd class="num">{suricataAlertsPerSec != null ? formatNumber(suricataAlertsPerSec) : '--'}</dd>
			<dt>Window</dt>
			<dd>Last 5 minutes</dd>
			<dt>Ruleset</dt>
			<dd>ET Open</dd>
			<dt>Output</dt>
			<dd class="mono">eve.json → Filebeat</dd>
		</dl>
	</Card>

	<Card title="Filebeat log shipper" sub="Watches the Zeek and Suricata logs and ships them to Logstash" class="c-4">
		{#if logstashStats}
			<!-- OLD CODE START — 2026-11-06 (S8): Logstash's events-since-start as throughput, "Shipping" whenever above 0
			{@const shipping = logstashStats.events_in > 0}
				<dd class="num">{shipping ? `${formatNumber(logstashStats.events_in)} events` : '--'}</dd>
				<dd>{@render word(shipping ? 'Shipping' : 'Idle', shipping ? 'ok' : 'medium')}</dd>
			OLD CODE END -->
			{@const shipping = eventsInRate != null && eventsInRate > 0}
			<dl class="facts flush">
				<dt>Into Logstash</dt>
				<dd class="num">{eventsInRate == null ? 'Measuring…' : formatEventRate(eventsInRate)}</dd>
				<dt>Output</dt>
				<dd class="mono">logstash:5044</dd>
				<dt>Protocol</dt>
				<dd>Beats (TCP)</dd>
				<dt>Status</dt>
				<dd>{@render word(shipping ? 'Shipping' : eventsInRate == null ? 'Measuring…' : 'No new events', shipping ? 'ok' : 'medium')}</dd>
			</dl>
		{:else if pending('Logstash stats')}
			<CardState state="loading" title="Loading Filebeat" />
		{:else}
			<CardState state="error" title={loadFailed('the shipping figures')} onaction={() => void refresh.run()} />
		{/if}
	</Card>

	<Card title="Logstash pipeline" sub="Log enrichment, GeoIP and hostname resolution" class="c-5">
		{#if logstashStats}
			{@const ls = logstashStats}
			<dl class="facts flush">
				<!-- OLD CODE: "Events in/out/filtered" with no window (S8: they count since Logstash started) -->
				<dt>Events in since start</dt>
				<dd class="num">{formatNumber(ls.events_in)}</dd>
				<dt>Events out since start</dt>
				<dd class="num">{formatNumber(ls.events_out)}</dd>
				<dt>Events filtered since start</dt>
				<dd class="num">{formatNumber(ls.events_filtered)}</dd>
				<dt>CPU load</dt>
				<dd class="num">{ls.cpu_percent}%</dd>
			</dl>
			<div class="heap">
				<div class="heap-k"><span>JVM heap used</span><b class="num">{heapPercent.toFixed(1)}%</b></div>
				<Meter value={heapPercent} label="JVM heap used" />
				<span class="dim">{formatBytes(ls.heap_used_bytes)} used · {formatBytes(ls.heap_max_bytes)} max</span>
			</div>
			{#if logstashPipelines.length > 0}
				<div class="card-note">
					<DataTable
						columns={pipelineColumns}
						rows={logstashPipelines}
						ariaLabel="Logstash pipelines"
						rowKey={(p) => p.id}
						initialSort={{ key: 'id', dir: 'asc' }}
					/>
				</div>
			{/if}
		{:else if pending('Logstash stats')}
			<CardState state="loading" title="Loading Logstash" />
		{:else}
			<CardState state="error" title={loadFailed('the pipeline figures')} onaction={() => void refresh.run()} />
		{/if}
	</Card>

	<Card title="OpenSearch cluster" sub={opensearchSub} class="c-7">
		{#if cluster}
			{@const cl = cluster}
			<dl class="facts flush">
				<dt>Cluster status</dt>
				<dd>{#if cl.status}{@render word(cap(cl.status), healthTone(cl.status))}{:else}--{/if}</dd>
				<dt>Total docs</dt>
				<dd class="num">{formatNumber(cl.total_docs)}</dd>
				<dt>Data size</dt>
				<dd class="num">{formatBytes(cl.total_data_size_bytes)}</dd>
				<dt>Active shards</dt>
				<dd class="num">{formatNumber(cl.active_shards)}</dd>
			</dl>
			{#if indices.length > 0}
				<div class="card-note">
					<DataTable
						columns={indexColumns}
						rows={indices}
						ariaLabel="OpenSearch indices"
						rowKey={(i) => i.index}
						initialSort={{ key: 'index', dir: 'asc' }}
					/>
				</div>
			{:else if failedSources['OpenSearch indices'] === false}
				<p class="dim card-note">No indices yet. OpenSearch creates them once logs arrive.</p>
			{/if}
			{#if templateRows.length > 0}
				<div class="card-note">
					<button class="btn" type="button" aria-expanded={showTemplates} onclick={() => (showTemplates = !showTemplates)}>
						<Icon name="chevdown" class={showTemplates ? 'chev' : ''} />Templates<span class="tag">{templateRows.length}</span>
					</button>
					{#if showTemplates}
						<div class="card-note">
							<DataTable
								columns={templateColumns}
								rows={templateRows}
								ariaLabel="Index templates"
								rowKey={(t) => t.name ?? ''}
								initialSort={{ key: 'name', dir: 'asc' }}
							/>
						</div>
					{/if}
				</div>
			{/if}
		{:else if pending('OpenSearch cluster')}
			<CardState state="loading" title="Loading the cluster" />
		{:else}
			<CardState state="error" title={loadFailed('the cluster status')} onaction={() => void refresh.run()} />
		{/if}
	</Card>

	<Card title="Other tools" sub="Each opens in a new tab" class="c-12">
		<ul class="svc-list">
			<li>
				<a class="link" href="/dashboards/" target="_blank" rel="noopener">OpenSearch Dashboards</a>
				<span>Native query and visualisation</span>
			</li>
			{#if grafanaUp}
				<li>
					<a class="link" href="/grafana/" target="_blank" rel="noopener">Grafana</a>
					<span>Advanced dashboards and graphs</span>
				</li>
			{/if}
			<li>
				<a class="link" href="/cyberchef/" target="_blank" rel="noopener">CyberChef</a>
				<span>Data decoding and transformation</span>
			</li>
		</ul>
	</Card>
</div>

<!-- UniFi integration -->
{#if unifiFailed['the UniFi status']}
	<div class="notice is-warn" role="status">
		<Icon name="warn" /><span>{loadFailed('the UniFi status', unifiStatus !== null)}</span>
	</div>
{/if}
{#if unifiStatus && !unifiStatus.configured}
	<div class="grid">
		<Card title="UniFi network integration" sub="Devices, networks and security policies from your UniFi controller" class="c-12">
			<CardState
				state="empty"
				icon="infra"
				title="UniFi isn't connected"
				message="Connect your UniFi controller to view network devices, security policies, and infrastructure topology."
				href="/settings"
				actionLabel="Configure UniFi"
			/>
		</Card>
	</div>
{:else if unifiStatus?.configured}
	{#if unifiStatus.last_error}
		<div class="notice is-error" role="alert">
			<Icon name="warn" /><span><b>UniFi error:</b> {unifiStatus.last_error}</span>
		</div>
	{/if}

	<div class="grid">
		<Card title="UniFi devices" sub="Gateways, switches and access points the controller manages" class="c-12">
			{#snippet actions()}
				<span class="chip">{unifiCount('UniFi devices', unifiDevices.length)} device{unifiDevices.length !== 1 ? 's' : ''}</span>
			{/snippet}
			{#if unifiFailed['UniFi devices'] && unifiDevices.length > 0}
				<div class="notice is-warn card-gap" role="status"><Icon name="warn" /><span>{loadFailed('UniFi devices', true)}</span></div>
			{/if}
			{#if unifiLoading && unifiDevices.length === 0}
				<CardState state="loading" title="Loading UniFi devices" />
			{:else if unifiDevices.length === 0}
				{#if unifiFailed['UniFi devices']}
					<CardState state="error" title={loadFailed('UniFi devices')} onaction={() => void refresh.run()} />
				{:else}
					<CardState state="empty" title="No UniFi devices found" message="Check your UniFi controller connection." />
				{/if}
			{:else}
				<DataTable
					columns={unifiDeviceColumns}
					rows={unifiDevices}
					ariaLabel="UniFi devices"
					rowKey={(d) => d.id}
					initialSort={{ key: 'name', dir: 'asc' }}
				/>
			{/if}
		</Card>

		<Card title="Networks" sub="Networks and VLANs on the controller" class="c-6">
			{#snippet actions()}<span class="chip">{unifiCount('networks', unifiNetworks.length)}</span>{/snippet}
			{#if unifiFailed.networks && unifiNetworks.length > 0}
				<div class="notice is-warn card-gap" role="status"><Icon name="warn" /><span>{loadFailed('networks', true)}</span></div>
			{/if}
			{#if unifiLoading && unifiNetworks.length === 0}
				<CardState state="loading" title="Loading networks" />
			{:else if unifiNetworks.length === 0}
				{#if unifiFailed.networks}
					<CardState state="error" title={loadFailed('networks')} onaction={() => void refresh.run()} />
				{:else}
					<CardState state="empty" title="No networks found" />
				{/if}
			{:else}
				<DataTable columns={networkColumns} rows={unifiNetworks} ariaLabel="Networks" rowKey={(n) => n.id} />
			{/if}
		</Card>

		<Card title="WiFi networks" sub="Wireless networks the controller broadcasts" class="c-6">
			{#snippet actions()}<span class="chip">{unifiCount('WiFi networks', unifiWifi.length)}</span>{/snippet}
			{#if unifiFailed['WiFi networks'] && unifiWifi.length > 0}
				<div class="notice is-warn card-gap" role="status"><Icon name="warn" /><span>{loadFailed('WiFi networks', true)}</span></div>
			{/if}
			{#if unifiLoading && unifiWifi.length === 0}
				<CardState state="loading" title="Loading WiFi networks" />
			{:else if unifiWifi.length === 0}
				{#if unifiFailed['WiFi networks']}
					<CardState state="error" title={loadFailed('WiFi networks')} onaction={() => void refresh.run()} />
				{:else}
					<CardState state="empty" title="No WiFi networks found" />
				{/if}
			{:else}
				<DataTable columns={wifiColumns} rows={unifiWifi} ariaLabel="WiFi networks" rowKey={(s) => s.id} />
			{/if}
		</Card>

		<Card title="Security posture" sub="Policies and tunnels configured on the controller" class="c-12">
			<StatStrip
				stats={[
					{ key: 'policies', label: 'Firewall policies', value: String(unifiCount('firewall policies', unifiFirewall.policies.length)) },
					{ key: 'zones', label: 'Firewall zones', value: String(unifiCount('firewall policies', unifiFirewall.zones.length)) },
					{ key: 'dns', label: 'DNS policies', value: String(unifiCount('DNS policies', unifiDnsPolicies.length)) },
					{ key: 'vpn', label: 'VPN tunnels', value: String(unifiCount('VPN tunnels', unifiVpn.length)) },
				]}
			/>
			{#each unifiPostureNotes as note (note)}
				<div class="notice is-warn card-note" role="status"><Icon name="warn" /><span>{note}</span></div>
			{/each}
			{#if unifiFirewall.policies.length > 0}
				<div class="card-note">
					<h3 class="eyebrow">Firewall policies</h3>
					<DataTable columns={policyColumns} rows={unifiFirewall.policies} ariaLabel="Firewall policies" rowKey={(p) => p.id} />
				</div>
			{/if}
		</Card>

		{#if unifiWans.length > 0}
			<Card title="WAN interfaces" sub="Internet uplinks on the gateway" class="c-6">
				{#snippet actions()}<span class="chip">{unifiWans.length}</span>{/snippet}
				<DataTable columns={wanColumns} rows={unifiWans} ariaLabel="WAN interfaces" rowKey={(w) => w.id} />
			</Card>
		{/if}
		{#if unifiVpn.length > 0}
			<Card title="VPN tunnels" sub="Site-to-site and remote-access tunnels" class="c-6">
				{#snippet actions()}<span class="chip">{unifiVpn.length}</span>{/snippet}
				<DataTable columns={vpnColumns} rows={unifiVpn} ariaLabel="VPN tunnels" rowKey={(t) => t.id} />
			</Card>
		{/if}
	</div>
{/if}

<style>
	/* Seven stages fit one row on wide screens; the system's 3- and 2-column rules take over below 1100 px */
	@container app (min-width: 1101px) {
		.pipe-wrap :global(.pipe) { grid-template-columns: repeat(7, minmax(0, 1fr)); }
	}
	.facts.flush { border-top: 0; padding-top: 0; }
	.card-note { margin-top: var(--sp-4); }
	.card-gap { margin-bottom: var(--sp-4); }
	.issues { margin: 0; padding-left: var(--sp-4); }
	.heap { display: flex; flex-direction: column; gap: var(--sp-2); margin-top: var(--sp-4); font-size: var(--text-xs); }
	.heap-k { display: flex; justify-content: space-between; gap: var(--sp-3); font-size: var(--text-sm); color: var(--text-2); }
	.heap-k b { color: var(--text-1); }
	.eyebrow { margin-bottom: var(--sp-2); }
	.svc-list { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: var(--sp-4); }
	.svc-list li { display: flex; flex-direction: column; gap: var(--sp-1); font-size: var(--text-xs); color: var(--text-2); }
	.svc-list .link { font-size: var(--text-sm); }
</style>
