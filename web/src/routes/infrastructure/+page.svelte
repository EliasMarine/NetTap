<script lang="ts">
	import { onMount } from 'svelte';
	import { getBridgeHealth } from '$api/bridge.js';
	import { getCaptureStats, getCaptureMode } from '$api/capture';
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
	import type { CaptureMode, CaptureStatsResponse } from '$api/capture';
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
	} from '$api/unifi';

	// ─── Node type for topology ─────────────────────────────────
	type NodeId = 'bridge' | 'capture' | 'zeek' | 'suricata' | 'filebeat' | 'logstash' | 'opensearch';

	// ─── Reactive state ─────────────────────────────────────────
	let selectedNode = $state<NodeId | null>(null);
	let loading = $state(false);

	// Data state
	let bridgeHealth = $state<BridgeHealth | null>(null);
	let captureStats = $state<CaptureStatsResponse | null>(null);
	let captureMode = $state<CaptureMode | null>(null);
	let systemHealth = $state<SystemHealth | null>(null);
	let storageStatus = $state<StorageStatus | null>(null);
	let cluster = $state<OpenSearchCluster | null>(null);
	let indices = $state<OpenSearchIndex[]>([]);
	let templates = $state<unknown[]>([]);
	let logstashStats = $state<LogstashStats | null>(null);
	let logstashPipelines = $state<LogstashPipeline[]>([]);
	let showTemplates = $state(false);

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

	// Zeek/Suricata throughput (computed from event counts over 5-min window)
	let zeekEventsPerSec = $state<number | null>(null);
	let suricataAlertsPerSec = $state<number | null>(null);

	// ─── Helpers ────────────────────────────────────────────────
	function formatBytes(bytes: number | null | undefined): string {
		if (bytes == null || !isFinite(bytes) || bytes <= 0) return '--';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		const val = bytes / Math.pow(1024, i);
		return `${val.toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
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

	function healthDotClass(status: string | null | undefined): string {
		if (!status) return '';
		const s = status.toLowerCase();
		if (s === 'green' || s === 'up' || s === 'normal' || s === 'running' || s === 'healthy') return 'green';
		if (s === 'yellow' || s === 'degraded') return 'yellow';
		return 'red';
	}

	function heapColor(percent: number): string {
		if (percent > 85) return 'var(--red)';
		if (percent > 70) return 'var(--amber)';
		return 'var(--green)';
	}

	// ─── Data fetching ──────────────────────────────────────────
	async function fetchBridgeAndCapture() {
		try {
			const [bh, cs, cm] = await Promise.all([
				getBridgeHealth(),
				getCaptureStats(),
				getCaptureMode().catch(() => null),
			]);
			bridgeHealth = bh;
			captureStats = cs;
			if (cm) captureMode = cm;
		} catch { /* swallow — individual calls have their own fallbacks */ }
	}

	async function fetchLogstash() {
		try {
			const [stats, pipelines] = await Promise.all([
				getLogstashStats(),
				getLogstashPipelines(),
			]);
			logstashStats = stats;
			logstashPipelines = pipelines;
		} catch { /* swallow */ }
	}

	async function fetchOpenSearch() {
		try {
			const [cl, idx, tmpl] = await Promise.all([
				getOpenSearchCluster(),
				getOpenSearchIndices(),
				getOpenSearchTemplates(),
			]);
			cluster = cl;
			indices = idx?.indices ?? [];
			templates = Array.isArray(tmpl) ? tmpl : [];
		} catch { /* swallow */ }
	}

	async function fetchStorage() {
		try {
			const [health, storage] = await Promise.all([
				getSystemHealth(),
				getStorageStatus(),
			]);
			systemHealth = health;
			storageStatus = storage;
		} catch { /* swallow */ }
	}

	async function fetchToolRates() {
		const WINDOW_SECS = 300; // 5-minute window
		try {
			// Zeek events (connection count from traffic summary)
			const zeekRes = await fetch('/api/traffic/summary?from=now-5m&to=now');
			if (zeekRes.ok) {
				const d = await zeekRes.json();
				const count = d.connection_count ?? d.total_connections ?? 0;
				zeekEventsPerSec = count > 0 ? Math.round(count / WINDOW_SECS) : 0;
			}
		} catch { /* swallow */ }
		try {
			// Suricata alerts (total count from alerts API)
			const suriRes = await fetch('/api/alerts/count?from=now-5m&to=now');
			if (suriRes.ok) {
				const d = await suriRes.json();
				const count = d.total ?? 0;
				suricataAlertsPerSec = count > 0 ? Math.round(count / WINDOW_SECS) : 0;
			}
		} catch { /* swallow */ }
	}

	async function fetchUnifi() {
		try {
			const status = await getUnifiStatus();
			unifiStatus = status;
			if (!status.configured) return;
			unifiLoading = true;
			const [devices, networks, wifi, firewall, dnsPolicies, wans, vpn] = await Promise.all([
				getUnifiDevices(),
				getUnifiNetworks(),
				getUnifiWifi(),
				getUnifiFirewall(),
				getUnifiDnsPolicies(),
				getUnifiWans(),
				getUnifiVpn(),
			]);
			unifiDevices = devices;
			unifiNetworks = networks;
			unifiWifi = wifi;
			unifiFirewall = firewall;
			unifiDnsPolicies = dnsPolicies;
			unifiWans = wans;
			unifiVpn = vpn;
		} catch { /* swallow */ }
		unifiLoading = false;
	}

	async function fetchAll() {
		loading = true;
		await Promise.all([
			fetchBridgeAndCapture(),
			fetchLogstash(),
			fetchOpenSearch(),
			fetchStorage(),
			fetchToolRates(),
			fetchUnifi(),
		]);
		loading = false;
	}

	// ─── Node selection ─────────────────────────────────────────
	function selectNode(node: NodeId) {
		selectedNode = selectedNode === node ? null : node;
	}

	function closeDetail() {
		selectedNode = null;
	}

	// ─── Sort state — Index table ───────────────────────────────
	type IndexSortKey = 'health' | 'index' | 'docs' | 'pri_size' | 'total_size' | 'created';
	let indexSortKey = $state<IndexSortKey>('index');
	let indexSortDir = $state<'asc' | 'desc'>('asc');

	function toggleIndexSort(key: IndexSortKey) {
		if (indexSortKey === key) { indexSortDir = indexSortDir === 'asc' ? 'desc' : 'asc'; }
		else { indexSortKey = key; indexSortDir = 'asc'; }
	}

	function indexSortIndicator(key: IndexSortKey): string {
		if (indexSortKey !== key) return '';
		return indexSortDir === 'asc' ? ' \u2191' : ' \u2193';
	}

	let sortedIndices = $derived.by(() => {
		if (!Array.isArray(indices) || indices.length === 0) return indices;
		const list = [...indices];
		list.sort((a, b) => {
			let cmp = 0;
			switch (indexSortKey) {
				case 'health': cmp = (a.health || '').localeCompare(b.health || ''); break;
				case 'index': cmp = (a.index ?? '').localeCompare(b.index ?? ''); break;
				case 'docs': cmp = (Number(a.docs_count) || 0) - (Number(b.docs_count) || 0); break;
				case 'pri_size': cmp = (a.pri_store_size ?? '').localeCompare(b.pri_store_size ?? ''); break;
				case 'total_size': cmp = (a.store_size ?? '').localeCompare(b.store_size ?? ''); break;
				case 'created': cmp = (a.creation_date ?? '').localeCompare(b.creation_date ?? ''); break;
			}
			return indexSortDir === 'asc' ? cmp : -cmp;
		});
		return list;
	});

	// ─── Sort state — Pipeline table ────────────────────────────
	type PipelineSortKey = 'name' | 'events_in' | 'events_out' | 'duration';
	let pipelineSortKey = $state<PipelineSortKey>('name');
	let pipelineSortDir = $state<'asc' | 'desc'>('asc');

	function togglePipelineSort(key: PipelineSortKey) {
		if (pipelineSortKey === key) { pipelineSortDir = pipelineSortDir === 'asc' ? 'desc' : 'asc'; }
		else { pipelineSortKey = key; pipelineSortDir = 'asc'; }
	}

	function pipelineSortIndicator(key: PipelineSortKey): string {
		if (pipelineSortKey !== key) return '';
		return pipelineSortDir === 'asc' ? ' \u2191' : ' \u2193';
	}

	let sortedPipelines = $derived.by(() => {
		if (logstashPipelines.length === 0) return logstashPipelines;
		const list = [...logstashPipelines];
		list.sort((a, b) => {
			let cmp = 0;
			switch (pipelineSortKey) {
				case 'name': cmp = (a.id ?? '').localeCompare(b.id ?? ''); break;
				case 'events_in': cmp = (a.events_in ?? 0) - (b.events_in ?? 0); break;
				case 'events_out': cmp = (a.events_out ?? 0) - (b.events_out ?? 0); break;
				case 'duration': cmp = (a.duration_in_millis ?? 0) - (b.duration_in_millis ?? 0); break;
			}
			return pipelineSortDir === 'asc' ? cmp : -cmp;
		});
		return list;
	});

	// ─── Sort state — Templates table ───────────────────────────
	type TemplateSortKey = 'name' | 'patterns' | 'order';
	let templateSortKey = $state<TemplateSortKey>('name');
	let templateSortDir = $state<'asc' | 'desc'>('asc');

	function toggleTemplateSort(key: TemplateSortKey) {
		if (templateSortKey === key) { templateSortDir = templateSortDir === 'asc' ? 'desc' : 'asc'; }
		else { templateSortKey = key; templateSortDir = 'asc'; }
	}

	function templateSortIndicator(key: TemplateSortKey): string {
		if (templateSortKey !== key) return '';
		return templateSortDir === 'asc' ? ' \u2191' : ' \u2193';
	}

	let sortedTemplates = $derived.by(() => {
		if (!Array.isArray(templates) || templates.length === 0) return templates;
		const list = [...templates] as any[];
		list.sort((a, b) => {
			let cmp = 0;
			switch (templateSortKey) {
				case 'name': cmp = (a.name ?? '').localeCompare(b.name ?? ''); break;
				case 'patterns':
					cmp = String(Array.isArray(a.index_patterns) ? a.index_patterns.join(', ') : a.index_patterns ?? '')
						.localeCompare(String(Array.isArray(b.index_patterns) ? b.index_patterns.join(', ') : b.index_patterns ?? ''));
					break;
				case 'order': cmp = (a.order ?? a.priority ?? 0) - (b.order ?? b.priority ?? 0); break;
			}
			return templateSortDir === 'asc' ? cmp : -cmp;
		});
		return list;
	});

	// ─── Sort state — UniFi Devices table ──────────────────────
	type UnifiDeviceSortKey = 'name' | 'model' | 'ipAddress' | 'state' | 'firmwareVersion';
	let unifiDeviceSortKey = $state<UnifiDeviceSortKey>('name');
	let unifiDeviceSortDir = $state<'asc' | 'desc'>('asc');

	function toggleUnifiDeviceSort(key: UnifiDeviceSortKey) {
		if (unifiDeviceSortKey === key) { unifiDeviceSortDir = unifiDeviceSortDir === 'asc' ? 'desc' : 'asc'; }
		else { unifiDeviceSortKey = key; unifiDeviceSortDir = 'asc'; }
	}

	function unifiDeviceSortIndicator(key: UnifiDeviceSortKey): string {
		if (unifiDeviceSortKey !== key) return '';
		return unifiDeviceSortDir === 'asc' ? ' \u2191' : ' \u2193';
	}

	let sortedUnifiDevices = $derived.by(() => {
		if (unifiDevices.length === 0) return unifiDevices;
		const list = [...unifiDevices];
		list.sort((a, b) => {
			let cmp = 0;
			switch (unifiDeviceSortKey) {
				case 'name': cmp = (a.name ?? '').localeCompare(b.name ?? ''); break;
				case 'model': cmp = (a.model ?? '').localeCompare(b.model ?? ''); break;
				case 'ipAddress': cmp = (a.ipAddress ?? '').localeCompare(b.ipAddress ?? ''); break;
				case 'state': cmp = (a.state ?? '').localeCompare(b.state ?? ''); break;
				case 'firmwareVersion': cmp = (a.firmwareVersion ?? '').localeCompare(b.firmwareVersion ?? ''); break;
			}
			return unifiDeviceSortDir === 'asc' ? cmp : -cmp;
		});
		return list;
	});

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

	function unifiDeviceIcon(device: UnifiDevice): string {
		const type = unifiDeviceType(device);
		if (type === 'AP') return 'wifi';
		if (type === 'Switch') return 'switch';
		if (type === 'Gateway') return 'gateway';
		return 'device';
	}

	// ─── Derived stats for quick stats bar ──────────────────────
	let eventsPerSec = $derived.by(() => {
		if (!logstashStats) return 0;
		// If we have events_in but no rate, show events_in as a proxy
		return logstashStats.events_in;
	});

	let diskUsedPercent = $derived.by(() => {
		return storageStatus?.disk_usage_percent ?? 0;
	});

	let indexCount = $derived.by(() => {
		return indices.length || cluster?.active_primary_shards || 0;
	});

	let latencyMs = $derived.by(() => {
		if (!bridgeHealth || bridgeHealth.latency_us <= 0) return 0;
		return bridgeHealth.latency_us / 1000;
	});

	let dropRate = $derived.by(() => {
		return captureStats?.drop_rate_pct ?? 0;
	});

	let uptimeSeconds = $derived.by(() => {
		return systemHealth?.uptime ?? bridgeHealth?.uptime_seconds ?? 0;
	});

	// ─── Logstash heap derived ──────────────────────────────────
	let heapPercent = $derived.by(() => {
		if (!logstashStats || logstashStats.heap_max_bytes <= 0) return 0;
		return (logstashStats.heap_used_bytes / logstashStats.heap_max_bytes) * 100;
	});

	// ─── SVG connection drawing ─────────────────────────────────
	const NS = 'http://www.w3.org/2000/svg';

	function nodeRight(id: string): { x: number; y: number } {
		const wrapper = document.querySelector('.topology-wrapper');
		const el = document.getElementById(id);
		if (!wrapper || !el) return { x: 0, y: 0 };
		const wr = wrapper.getBoundingClientRect();
		const er = el.getBoundingClientRect();
		return { x: er.right - wr.left, y: er.top - wr.top + er.height / 2 };
	}

	function nodeLeft(id: string): { x: number; y: number } {
		const wrapper = document.querySelector('.topology-wrapper');
		const el = document.getElementById(id);
		if (!wrapper || !el) return { x: 0, y: 0 };
		const wr = wrapper.getBoundingClientRect();
		const er = el.getBoundingClientRect();
		return { x: er.left - wr.left, y: er.top - wr.top + er.height / 2 };
	}

	function bezier(from: { x: number; y: number }, to: { x: number; y: number }): string {
		const dx = (to.x - from.x) * 0.45;
		return `M ${from.x},${from.y} C ${from.x + dx},${from.y} ${to.x - dx},${to.y} ${to.x},${to.y}`;
	}

	function drawConn(svg: Element, from: { x: number; y: number }, to: { x: number; y: number }, lineClass: string, particleClass: string, speed: string) {
		const d = bezier(from, to);
		const line = document.createElementNS(NS, 'path');
		line.setAttribute('d', d);
		line.setAttribute('class', `conn-line ${lineClass}`);
		svg.appendChild(line);
		const particles = document.createElementNS(NS, 'path');
		particles.setAttribute('d', d);
		particles.setAttribute('class', `conn-particles ${particleClass} speed-${speed}`);
		svg.appendChild(particles);
	}

	function drawConnections() {
		const svg = document.getElementById('connSvg');
		if (!svg) return;
		while (svg.firstChild) svg.removeChild(svg.firstChild);

		const wrapper = document.querySelector('.topology-wrapper');
		if (!wrapper) return;
		const wr = wrapper.getBoundingClientRect();
		svg.setAttribute('viewBox', `0 0 ${wr.width} ${wr.height}`);
		(svg as HTMLElement).style.width = `${wr.width}px`;
		(svg as HTMLElement).style.height = `${wr.height}px`;

		drawConn(svg, nodeRight('node-bridge'), nodeLeft('node-capture'), 'conn-cyan', 'conn-cyan-p', 'fast');
		drawConn(svg, nodeRight('node-capture'), nodeLeft('node-zeek'), 'conn-green', 'conn-green-p', 'fast');
		drawConn(svg, nodeRight('node-capture'), nodeLeft('node-suricata'), 'conn-red', 'conn-red-p', 'normal');
		drawConn(svg, nodeRight('node-zeek'), nodeLeft('node-filebeat'), 'conn-green', 'conn-green-p', 'fast');
		drawConn(svg, nodeRight('node-suricata'), nodeLeft('node-filebeat'), 'conn-red', 'conn-red-p', 'slow');
		drawConn(svg, nodeRight('node-filebeat'), nodeLeft('node-logstash'), 'conn-cyan', 'conn-cyan-p', 'normal');
		drawConn(svg, nodeRight('node-logstash'), nodeLeft('node-opensearch'), 'conn-cyan', 'conn-cyan-p', 'fast');
	}

	// ─── Lifecycle & auto-polling ───────────────────────────────
	onMount(() => {
		fetchAll();
		setTimeout(drawConnections, 100);
	});

	// Auto-poll with $effect
	$effect(() => {
		// Bridge + capture: every 10s
		const bridgeInterval = setInterval(fetchBridgeAndCapture, 10_000);
		// Logstash + OpenSearch: every 15s
		const logstashInterval = setInterval(() => { fetchLogstash(); fetchOpenSearch(); fetchToolRates(); }, 15_000);
		// Storage: every 60s
		const storageInterval = setInterval(fetchStorage, 60_000);
		// UniFi: every 30s
		const unifiInterval = setInterval(fetchUnifi, 30_000);

		// Redraw connections on resize
		const handleResize = () => drawConnections();
		window.addEventListener('resize', handleResize);

		// Escape to close detail
		const handleKeydown = (e: KeyboardEvent) => { if (e.key === 'Escape') closeDetail(); };
		document.addEventListener('keydown', handleKeydown);

		return () => {
			clearInterval(bridgeInterval);
			clearInterval(logstashInterval);
			clearInterval(storageInterval);
			clearInterval(unifiInterval);
			window.removeEventListener('resize', handleResize);
			document.removeEventListener('keydown', handleKeydown);
		};
	});
</script>

<svelte:head>
	<title>Pipeline Operations Center | NetTap</title>
</svelte:head>

<div class="poc-page">

	<!-- ═══════════════════════════════════════════════════════════
	     HEADER
	     ═══════════════════════════════════════════════════════════ -->
	<header class="page-header">
		<div class="header-left">
			<h1>Pipeline Operations Center</h1>
			<p class="header-subtitle">Real-time data flow monitoring across the NetTap capture pipeline</p>
		</div>
		<div class="header-right">
			<div class="live-badge">
				<span class="live-dot"></span>
				Live &middot; 15s
			</div>
			<button class="btn-refresh" onclick={fetchAll} disabled={loading}>
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<polyline points="23 4 23 10 17 10"></polyline>
					<polyline points="1 20 1 14 7 14"></polyline>
					<path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"></path>
				</svg>
				{loading ? 'Loading...' : 'Refresh'}
			</button>
		</div>
	</header>

	<!-- ═══════════════════════════════════════════════════════════
	     PIPELINE TOPOLOGY (Hero)
	     ═══════════════════════════════════════════════════════════ -->
	<section class="topology-section">
		<div class="topology-wrapper">
			<!-- SVG connections drawn by JS -->
			<svg class="topology-svg-overlay" id="connSvg"></svg>

			<!-- Pipeline Nodes -->
			<div class="pipeline-grid" id="pipelineGrid">

				<!-- Bridge -->
				<div class="pipeline-node" class:active={selectedNode === 'bridge'} data-node="bridge" onclick={() => selectNode('bridge')}>
					<div class="node-card" id="node-bridge">
						<div class="node-icon bridge">
							<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<rect x="2" y="6" width="20" height="12" rx="2"/>
								<line x1="6" y1="10" x2="6" y2="14"/>
								<line x1="18" y1="10" x2="18" y2="14"/>
								<line x1="12" y1="6" x2="12" y2="18"/>
							</svg>
						</div>
						<div class="node-name">Bridge</div>
						<div class="node-health">
							<span class="health-dot {bridgeHealth ? healthDotClass(bridgeHealth.bridge_state) : ''}"></span>
							{bridgeHealth?.bridge_state === 'up' ? 'br0 UP' : bridgeHealth?.bridge_state ?? '--'}
						</div>
						<div class="node-metric">
							WAN <span class="value">{bridgeHealth?.wan_link ? '\u25CF' : '\u25CB'}</span>
							LAN <span class="value">{bridgeHealth?.lan_link ? '\u25CF' : '\u25CB'}</span>
						</div>
					</div>
				</div>

				<!-- Capture -->
				<div class="pipeline-node" class:active={selectedNode === 'capture'} data-node="capture" onclick={() => selectNode('capture')}>
					<div class="node-card" id="node-capture">
						<div class="node-icon capture">
							<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<circle cx="12" cy="12" r="10"/>
								<circle cx="12" cy="12" r="3"/>
								<line x1="12" y1="2" x2="12" y2="6"/>
								<line x1="12" y1="18" x2="12" y2="22"/>
								<line x1="2" y1="12" x2="6" y2="12"/>
								<line x1="18" y1="12" x2="22" y2="12"/>
							</svg>
						</div>
						<div class="node-name">Capture</div>
						<div class="node-health">
							<span class="health-dot {bridgeHealth && !bridgeHealth.bypass_active ? 'green' : 'yellow'}"></span>
							{bridgeHealth?.bypass_active ? 'Bypass' : 'Promiscuous'}
						</div>
						<div class="node-metric">Drop <span class="value">{captureStats ? captureStats.drop_rate_pct.toFixed(2) + '%' : '--'}</span></div>
					</div>
				</div>

				<!-- Zeek (row 1) -->
				<div class="pipeline-node" class:active={selectedNode === 'zeek'} data-node="zeek" onclick={() => selectNode('zeek')}>
					<div class="node-card" id="node-zeek">
						<div class="node-icon zeek">
							<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<circle cx="11" cy="11" r="8"/>
								<line x1="21" y1="21" x2="16.65" y2="16.65"/>
							</svg>
						</div>
						<div class="node-name">Zeek</div>
						<div class="node-health">
							<span class="health-dot green"></span>
							Running
						</div>
						<div class="node-metric"><span class="value">{zeekEventsPerSec != null ? formatNumber(zeekEventsPerSec) : '--'}</span> evt/s</div>
					</div>
				</div>

				<!-- Suricata (row 3) -->
				<div class="pipeline-node" class:active={selectedNode === 'suricata'} data-node="suricata" onclick={() => selectNode('suricata')}>
					<div class="node-card" id="node-suricata">
						<div class="node-icon suricata">
							<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
							</svg>
						</div>
						<div class="node-name">Suricata</div>
						<div class="node-health">
							<span class="health-dot green"></span>
							Running
						</div>
						<div class="node-metric"><span class="value">{suricataAlertsPerSec != null ? formatNumber(suricataAlertsPerSec) : '--'}</span> alerts/s</div>
					</div>
				</div>

				<!-- Filebeat -->
				<div class="pipeline-node" class:active={selectedNode === 'filebeat'} data-node="filebeat" onclick={() => selectNode('filebeat')}>
					<div class="node-card" id="node-filebeat">
						<div class="node-icon filebeat">
							<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
								<polyline points="14 2 14 8 20 8"/>
								<line x1="16" y1="13" x2="8" y2="13"/>
								<line x1="16" y1="17" x2="8" y2="17"/>
							</svg>
						</div>
						<div class="node-name">Filebeat</div>
						<div class="node-health">
							<span class="health-dot {logstashStats && logstashStats.events_in > 0 ? 'green' : 'yellow'}"></span>
							{logstashStats && logstashStats.events_in > 0 ? 'Shipping' : 'Idle'}
						</div>
						<div class="node-metric"><span class="value">{logstashStats ? formatNumber(logstashStats.events_in) : '--'}</span> evt</div>
					</div>
				</div>

				<!-- Logstash -->
				<div class="pipeline-node" class:active={selectedNode === 'logstash'} data-node="logstash" onclick={() => selectNode('logstash')}>
					<div class="node-card" id="node-logstash">
						<div class="node-icon logstash">
							<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
							</svg>
						</div>
						<div class="node-name">Logstash</div>
						<div class="node-health">
							<span class="health-dot {logstashStats ? 'green' : 'yellow'}"></span>
							{logstashStats ? 'Processing' : 'Unknown'}
						</div>
						<div class="node-metric">Heap <span class="value">{logstashStats ? heapPercent.toFixed(0) + '%' : '--'}</span></div>
					</div>
				</div>

				<!-- OpenSearch -->
				<div class="pipeline-node" class:active={selectedNode === 'opensearch'} data-node="opensearch" onclick={() => selectNode('opensearch')}>
					<div class="node-card" id="node-opensearch">
						<div class="node-icon opensearch">
							<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<ellipse cx="12" cy="5" rx="9" ry="3"/>
								<path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
								<path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
							</svg>
						</div>
						<div class="node-name">OpenSearch</div>
						<div class="node-health">
							<span class="health-dot {cluster ? healthDotClass(cluster.status) : ''}"></span>
							{cluster?.status ? cluster.status.charAt(0).toUpperCase() + cluster.status.slice(1) : '--'}
						</div>
						<div class="node-metric"><span class="value">{indices.length || '--'}</span> indices</div>
					</div>
				</div>

			</div>
		</div>
	</section>

	<!-- ═══════════════════════════════════════════════════════════
	     DETAIL PANELS
	     ═══════════════════════════════════════════════════════════ -->

	<!-- Bridge Detail -->
	{#if selectedNode === 'bridge'}
		<div class="detail-panel open">
			<div class="detail-header">
				<div class="detail-header-left">
					<div class="node-icon bridge" style="width:32px;height:32px;">
						<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="6" width="20" height="12" rx="2"/><line x1="12" y1="6" x2="12" y2="18"/></svg>
					</div>
					<div>
						<div class="detail-title">Bridge &mdash; br0</div>
						<div class="detail-subtitle">Linux software bridge with promiscuous capture</div>
					</div>
				</div>
				<button class="btn-close-detail" onclick={closeDetail}>&#10005;</button>
			</div>
			<div class="detail-body">
				<div class="detail-grid">
					<div class="detail-stat">
						<div class="detail-stat-label">Bridge State</div>
						<div class="detail-stat-value {bridgeHealth?.bridge_state === 'up' ? 'green' : 'red'}">
							{bridgeHealth?.bridge_state === 'up' ? 'UP' : bridgeHealth?.bridge_state?.toUpperCase() ?? '--'}
						</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">WAN Carrier</div>
						<div class="detail-stat-value {bridgeHealth?.wan_link ? 'green' : 'red'}">
							{bridgeHealth?.wan_link ? '\u25CF Connected' : '\u25CB Disconnected'}
						</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">LAN Carrier</div>
						<div class="detail-stat-value {bridgeHealth?.lan_link ? 'green' : 'red'}">
							{bridgeHealth?.lan_link ? '\u25CF Connected' : '\u25CB Disconnected'}
						</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Latency</div>
						<div class="detail-stat-value cyan">
							{bridgeHealth && bridgeHealth.latency_us > 0 ? (bridgeHealth.latency_us / 1000).toFixed(1) + ' ms' : '--'}
						</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">RX Traffic</div>
						<div class="detail-stat-value">{formatBytes(bridgeHealth?.rx_bytes_delta)}</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">TX Traffic</div>
						<div class="detail-stat-value">{formatBytes(bridgeHealth?.tx_bytes_delta)}</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Promisc Mode</div>
						<div class="detail-stat-value {bridgeHealth && !bridgeHealth.bypass_active ? 'green' : ''}">
							{bridgeHealth?.bypass_active ? 'No (Bypass)' : 'Yes'}
						</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Bypass Mode</div>
						<div class="detail-stat-value">{bridgeHealth?.bypass_active ? 'Active' : 'Inactive'}</div>
					</div>
				</div>
			</div>
		</div>
	{/if}

	<!-- Capture Detail -->
	{#if selectedNode === 'capture'}
		<div class="detail-panel open">
			<div class="detail-header">
				<div class="detail-header-left">
					<div class="node-icon capture" style="width:32px;height:32px;">
						<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>
					</div>
					<div>
						<div class="detail-title">Packet Capture</div>
						<div class="detail-subtitle">
							{captureMode?.mode === 'mirror' ? 'Mirror / SPAN mode' : 'Promiscuous mode on br0 — Bridge capture'}
						</div>
					</div>
				</div>
				<button class="btn-close-detail" onclick={closeDetail}>&#10005;</button>
			</div>
			<div class="detail-body">
				<div class="detail-grid">
					<div class="detail-stat">
						<div class="detail-stat-label">Capture Mode</div>
						<div class="detail-stat-value">{captureMode?.mode === 'mirror' ? 'Mirror' : 'Bridge'}</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Interface</div>
						<div class="detail-stat-value mono" style="font-size: var(--text-lg)">
							{captureStats?.capture_interface || captureMode?.interface || 'br0'}
						</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">RX Packets</div>
						<div class="detail-stat-value cyan">{formatNumber(captureStats?.rx_packets)}</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">TX Packets</div>
						<div class="detail-stat-value">{formatNumber(captureStats?.tx_packets)}</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Drop Rate</div>
						<div class="detail-stat-value {captureStats && captureStats.drop_rate_pct < 1 ? 'green' : 'amber'}">
							{captureStats ? captureStats.drop_rate_pct.toFixed(2) + '%' : '--'}
						</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Link Speed</div>
						<div class="detail-stat-value">
							{captureStats && captureStats.link_speed_mbps > 0 ? formatNumber(captureStats.link_speed_mbps) + ' Mbps' : '--'}
						</div>
					</div>
				</div>
			</div>
		</div>
	{/if}

	<!-- Zeek Detail -->
	{#if selectedNode === 'zeek'}
		<div class="detail-panel open">
			<div class="detail-header">
				<div class="detail-header-left">
					<div class="node-icon zeek" style="width:32px;height:32px;">
						<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
					</div>
					<div>
						<div class="detail-title">Zeek Network Analyzer</div>
						<div class="detail-subtitle">Structured metadata logs &mdash; conn, dns, http, tls, files, dhcp, smtp</div>
					</div>
				</div>
				<button class="btn-close-detail" onclick={closeDetail}>&#10005;</button>
			</div>
			<div class="detail-body">
				<div class="detail-grid">
					<div class="detail-stat">
						<div class="detail-stat-label">Events / sec</div>
						<div class="detail-stat-value green">--</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Status</div>
						<div class="detail-stat-value green">Running</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Log Types</div>
						<div class="detail-stat-value">conn, dns, http, tls, files, dhcp</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Output</div>
						<div class="detail-stat-value mono" style="font-size: var(--text-base)">JSON logs &rarr; Filebeat</div>
					</div>
				</div>
			</div>
		</div>
	{/if}

	<!-- Suricata Detail -->
	{#if selectedNode === 'suricata'}
		<div class="detail-panel open">
			<div class="detail-header">
				<div class="detail-header-left">
					<div class="node-icon suricata" style="width:32px;height:32px;">
						<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
					</div>
					<div>
						<div class="detail-title">Suricata IDS</div>
						<div class="detail-subtitle">Signature + anomaly-based intrusion detection</div>
					</div>
				</div>
				<button class="btn-close-detail" onclick={closeDetail}>&#10005;</button>
			</div>
			<div class="detail-body">
				<div class="detail-grid">
					<div class="detail-stat">
						<div class="detail-stat-label">Alerts / sec</div>
						<div class="detail-stat-value amber">--</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Status</div>
						<div class="detail-stat-value green">Running</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Ruleset</div>
						<div class="detail-stat-value">ET Open</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Output</div>
						<div class="detail-stat-value mono" style="font-size: var(--text-base)">eve.json &rarr; Filebeat</div>
					</div>
				</div>
			</div>
		</div>
	{/if}

	<!-- Filebeat Detail -->
	{#if selectedNode === 'filebeat'}
		<div class="detail-panel open">
			<div class="detail-header">
				<div class="detail-header-left">
					<div class="node-icon filebeat" style="width:32px;height:32px;">
						<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
					</div>
					<div>
						<div class="detail-title">Filebeat Log Shipper</div>
						<div class="detail-subtitle">Watches Zeek + Suricata log volumes, ships to Logstash</div>
					</div>
				</div>
				<button class="btn-close-detail" onclick={closeDetail}>&#10005;</button>
			</div>
			<div class="detail-body">
				<div class="detail-grid">
					<div class="detail-stat">
						<div class="detail-stat-label">Throughput</div>
						<div class="detail-stat-value cyan">
							{logstashStats && logstashStats.events_in > 0 ? formatNumber(logstashStats.events_in) + ' evt' : '--'}
						</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Output</div>
						<div class="detail-stat-value mono" style="font-size: var(--text-base)">logstash:5044</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Protocol</div>
						<div class="detail-stat-value">Beats (TCP)</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Status</div>
						<div class="detail-stat-value {logstashStats && logstashStats.events_in > 0 ? 'green' : 'amber'}">
							{logstashStats && logstashStats.events_in > 0 ? 'Shipping' : 'Idle'}
						</div>
					</div>
				</div>
			</div>
		</div>
	{/if}

	<!-- Logstash Detail -->
	{#if selectedNode === 'logstash'}
		<div class="detail-panel open">
			<div class="detail-header">
				<div class="detail-header-left">
					<div class="node-icon logstash" style="width:32px;height:32px;">
						<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
					</div>
					<div>
						<div class="detail-title">Logstash Pipeline</div>
						<div class="detail-subtitle">Log enrichment, GeoIP, hostname resolution</div>
					</div>
				</div>
				<button class="btn-close-detail" onclick={closeDetail}>&#10005;</button>
			</div>
			<div class="detail-body">
				<div class="detail-grid">
					<div class="detail-stat">
						<div class="detail-stat-label">Events In</div>
						<div class="detail-stat-value cyan">{formatNumber(logstashStats?.events_in)}</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Events Out</div>
						<div class="detail-stat-value green">{formatNumber(logstashStats?.events_out)}</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Events Filtered</div>
						<div class="detail-stat-value">{formatNumber(logstashStats?.events_filtered)}</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">CPU Load</div>
						<div class="detail-stat-value">{logstashStats ? logstashStats.cpu_percent + '%' : '--'}</div>
					</div>
				</div>

				<!-- JVM Heap Bar -->
				{#if logstashStats}
					<div class="detail-stat" style="margin-bottom: var(--space-lg);">
						<div class="detail-stat-label">JVM Heap Usage &mdash; {heapPercent.toFixed(1)}%</div>
						<div class="heap-bar-container">
							<div
								class="heap-bar-fill"
								style="width: {Math.min(heapPercent, 100)}%; background: linear-gradient(90deg, var(--green), {heapColor(heapPercent)});"
							></div>
						</div>
						<div class="heap-labels">
							<span>{formatBytes(logstashStats.heap_used_bytes)} used</span>
							<span>{formatBytes(logstashStats.heap_max_bytes)} max</span>
						</div>
					</div>
				{/if}

				<!-- Pipeline table -->
				{#if logstashPipelines.length > 0}
					<div class="detail-table-wrapper">
						<table class="detail-table">
							<thead>
								<tr>
									<th>
										<button class="sort-btn" class:active-sort={pipelineSortKey === 'name'} onclick={() => togglePipelineSort('name')}>
											Pipeline{pipelineSortIndicator('name')}
										</button>
									</th>
									<th>
										<button class="sort-btn" class:active-sort={pipelineSortKey === 'events_in'} onclick={() => togglePipelineSort('events_in')}>
											Events In{pipelineSortIndicator('events_in')}
										</button>
									</th>
									<th>
										<button class="sort-btn" class:active-sort={pipelineSortKey === 'events_out'} onclick={() => togglePipelineSort('events_out')}>
											Events Out{pipelineSortIndicator('events_out')}
										</button>
									</th>
									<th>
										<button class="sort-btn" class:active-sort={pipelineSortKey === 'duration'} onclick={() => togglePipelineSort('duration')}>
											Duration{pipelineSortIndicator('duration')}
										</button>
									</th>
								</tr>
							</thead>
							<tbody>
								{#each sortedPipelines as p}
									<tr>
										<td class="mono">{p.id ?? '--'}</td>
										<td class="mono">{formatNumber(p.events_in)}</td>
										<td class="mono">{formatNumber(p.events_out)}</td>
										<td class="mono">{formatNumber(p.duration_in_millis)} ms</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>
		</div>
	{/if}

	<!-- OpenSearch Detail -->
	{#if selectedNode === 'opensearch'}
		<div class="detail-panel open">
			<div class="detail-header">
				<div class="detail-header-left">
					<div class="node-icon opensearch" style="width:32px;height:32px;">
						<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
					</div>
					<div>
						<div class="detail-title">OpenSearch Cluster</div>
						<div class="detail-subtitle">
							{cluster ? `Single-node cluster with ${indices.length} active indices` : 'Cluster status unknown'}
						</div>
					</div>
				</div>
				<button class="btn-close-detail" onclick={closeDetail}>&#10005;</button>
			</div>
			<div class="detail-body">
				<div class="detail-grid">
					<div class="detail-stat">
						<div class="detail-stat-label">Cluster Status</div>
						<div class="detail-stat-value {cluster ? healthDotClass(cluster.status) : ''}">
							{cluster?.status ? cluster.status.charAt(0).toUpperCase() + cluster.status.slice(1) : '--'}
						</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Total Docs</div>
						<div class="detail-stat-value">{cluster ? formatNumber(cluster.total_docs) : '--'}</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Data Size</div>
						<div class="detail-stat-value cyan">{cluster ? formatBytes(cluster.total_data_size_bytes) : '--'}</div>
					</div>
					<div class="detail-stat">
						<div class="detail-stat-label">Active Shards</div>
						<div class="detail-stat-value">{cluster ? formatNumber(cluster.active_shards) : '--'}</div>
					</div>
				</div>

				<!-- Index table -->
				{#if sortedIndices.length > 0}
					<div class="detail-table-wrapper">
						<table class="detail-table">
							<thead>
								<tr>
									<th>
										<button class="sort-btn" class:active-sort={indexSortKey === 'health'} onclick={() => toggleIndexSort('health')}>
											Health{indexSortIndicator('health')}
										</button>
									</th>
									<th>
										<button class="sort-btn" class:active-sort={indexSortKey === 'index'} onclick={() => toggleIndexSort('index')}>
											Index Name{indexSortIndicator('index')}
										</button>
									</th>
									<th>
										<button class="sort-btn" class:active-sort={indexSortKey === 'docs'} onclick={() => toggleIndexSort('docs')}>
											Docs{indexSortIndicator('docs')}
										</button>
									</th>
									<th>
										<button class="sort-btn" class:active-sort={indexSortKey === 'pri_size'} onclick={() => toggleIndexSort('pri_size')}>
											Primary Size{indexSortIndicator('pri_size')}
										</button>
									</th>
									<th>
										<button class="sort-btn" class:active-sort={indexSortKey === 'total_size'} onclick={() => toggleIndexSort('total_size')}>
											Total Size{indexSortIndicator('total_size')}
										</button>
									</th>
								</tr>
							</thead>
							<tbody>
								{#each sortedIndices as idx}
									<tr>
										<td>
											<span class="health-indicator">
												<span class="health-dot {healthDotClass(idx.health)}"></span>
												{idx.health ?? '--'}
											</span>
										</td>
										<td class="mono">{idx.index ?? '--'}</td>
										<td class="mono">{formatNumber(Number(idx.docs_count))}</td>
										<td class="mono">{idx.pri_store_size ?? '--'}</td>
										<td class="mono">{idx.store_size ?? '--'}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}

				<!-- Templates (collapsible) -->
				{#if Array.isArray(templates) && templates.length > 0}
					<div class="templates-section">
						<button class="templates-toggle" onclick={() => showTemplates = !showTemplates}>
							<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" class="chevron" class:rotated={showTemplates}>
								<polyline points="9 18 15 12 9 6" />
							</svg>
							Templates
							<span class="badge badge-muted">{templates.length}</span>
						</button>
						{#if showTemplates}
							<div class="detail-table-wrapper" style="margin-top: var(--space-md);">
								<table class="detail-table">
									<thead>
										<tr>
											<th>
												<button class="sort-btn" class:active-sort={templateSortKey === 'name'} onclick={() => toggleTemplateSort('name')}>
													Name{templateSortIndicator('name')}
												</button>
											</th>
											<th>
												<button class="sort-btn" class:active-sort={templateSortKey === 'patterns'} onclick={() => toggleTemplateSort('patterns')}>
													Index Patterns{templateSortIndicator('patterns')}
												</button>
											</th>
											<th>
												<button class="sort-btn" class:active-sort={templateSortKey === 'order'} onclick={() => toggleTemplateSort('order')}>
													Order{templateSortIndicator('order')}
												</button>
											</th>
										</tr>
									</thead>
									<tbody>
										{#each sortedTemplates as tmpl}
											<tr>
												<td class="mono">{tmpl.name ?? '--'}</td>
												<td class="mono">{Array.isArray(tmpl.index_patterns) ? tmpl.index_patterns.join(', ') : tmpl.index_patterns ?? '--'}</td>
												<td class="mono">{tmpl.order ?? tmpl.priority ?? '--'}</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						{/if}
					</div>
				{/if}
			</div>
		</div>
	{/if}

	<!-- ═══════════════════════════════════════════════════════════
	     QUICK STATS BAR
	     ═══════════════════════════════════════════════════════════ -->
	<section class="stats-bar">
		<div class="stat-card-mini">
			<div class="stat-label">Events In</div>
			<div class="stat-value cyan">{logstashStats ? formatNumber(eventsPerSec) : '--'}</div>
		</div>
		<div class="stat-card-mini">
			<div class="stat-label">Disk Used</div>
			<div class="stat-value">{diskUsedPercent > 0 ? diskUsedPercent.toFixed(1) : '--'}<span class="stat-unit">%</span></div>
		</div>
		<div class="stat-card-mini">
			<div class="stat-label">Indices</div>
			<div class="stat-value">{indexCount > 0 ? indexCount : '--'}</div>
		</div>
		<div class="stat-card-mini">
			<div class="stat-label">Latency</div>
			<div class="stat-value green">{latencyMs > 0 ? latencyMs.toFixed(1) : '--'}<span class="stat-unit">ms</span></div>
		</div>
		<div class="stat-card-mini">
			<div class="stat-label">Drop Rate</div>
			<div class="stat-value green">{captureStats ? dropRate.toFixed(2) : '--'}<span class="stat-unit">%</span></div>
		</div>
		<div class="stat-card-mini">
			<div class="stat-label">Uptime</div>
			<div class="stat-value">{formatUptime(uptimeSeconds)}</div>
		</div>
	</section>

	<!-- ═══════════════════════════════════════════════════════════
	     SERVICE LINKS
	     ═══════════════════════════════════════════════════════════ -->
	<section class="services-row">
		<a href="/dashboards/" class="service-link" target="_blank" rel="noopener">
			<div class="service-icon-box os">
				<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
			</div>
			<div class="service-info-text">
				<div class="service-name">OpenSearch Dashboards</div>
				<div class="service-desc">Native query &amp; visualization</div>
			</div>
			<span class="service-arrow">&rarr;</span>
		</a>
		<a href="/grafana/" class="service-link" target="_blank" rel="noopener">
			<div class="service-icon-box grafana">
				<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
			</div>
			<div class="service-info-text">
				<div class="service-name">Grafana</div>
				<div class="service-desc">Advanced dashboards &amp; graphs</div>
			</div>
			<span class="service-arrow">&rarr;</span>
		</a>
		<a href="/cyberchef/" class="service-link" target="_blank" rel="noopener">
			<div class="service-icon-box cyberchef">
				<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/><line x1="14" y1="4" x2="10" y2="20"/></svg>
			</div>
			<div class="service-info-text">
				<div class="service-name">CyberChef</div>
				<div class="service-desc">Data decoding &amp; transformation</div>
			</div>
			<span class="service-arrow">&rarr;</span>
		</a>
	</section>

	<!-- ═══════════════════════════════════════════════════════════
	     UNIFI INTEGRATION
	     ═══════════════════════════════════════════════════════════ -->
	{#if unifiStatus && !unifiStatus.configured}
		<!-- UniFi not configured — show a subtle prompt -->
		<section class="card unifi-not-configured">
			<div class="card-header">
				<h2 class="card-title">
					<svg class="unifi-section-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<path d="M5 12.55a11 11 0 0 1 14.08 0"/>
						<path d="M1.42 9a16 16 0 0 1 21.16 0"/>
						<path d="M8.53 16.11a6 6 0 0 1 6.95 0"/>
						<line x1="12" y1="20" x2="12.01" y2="20"/>
					</svg>
					UniFi Network Integration
				</h2>
			</div>
			<div class="unifi-unconfigured-body">
				<p class="unifi-unconfigured-text">Connect your UniFi controller to view network devices, security policies, and infrastructure topology.</p>
				<a href="/settings" class="btn btn-secondary">Configure UniFi</a>
			</div>
		</section>
	{:else if unifiStatus?.configured}
		<!-- UniFi is configured — show full data sections -->

		{#if unifiStatus.last_error}
			<div class="alert alert-warning unifi-error-banner">
				<strong>UniFi Error:</strong> {unifiStatus.last_error}
			</div>
		{/if}

		<!-- ─── UniFi Devices Card ─────────────────────────────── -->
		<section class="card">
			<div class="card-header">
				<h2 class="card-title">
					<svg class="unifi-section-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<path d="M5 12.55a11 11 0 0 1 14.08 0"/>
						<path d="M1.42 9a16 16 0 0 1 21.16 0"/>
						<path d="M8.53 16.11a6 6 0 0 1 6.95 0"/>
						<line x1="12" y1="20" x2="12.01" y2="20"/>
					</svg>
					UniFi Devices
				</h2>
				<span class="badge badge-info">{unifiDevices.length} device{unifiDevices.length !== 1 ? 's' : ''}</span>
			</div>

			{#if unifiLoading && unifiDevices.length === 0}
				<div class="loading-state">
					<div class="loading-spinner"></div>
					<p class="unifi-loading-text">Loading UniFi devices...</p>
				</div>
			{:else if unifiDevices.length === 0}
				<div class="empty-state">
					<p class="empty-text">No UniFi devices found</p>
					<p class="empty-hint">Check your UniFi controller connection</p>
				</div>
			{:else}
				<div class="detail-table-wrapper">
					<table class="detail-table">
						<thead>
							<tr>
								<th>
									<button class="sort-btn" class:active-sort={unifiDeviceSortKey === 'name'} onclick={() => toggleUnifiDeviceSort('name')}>
										Name{unifiDeviceSortIndicator('name')}
									</button>
								</th>
								<th>Type</th>
								<th>
									<button class="sort-btn" class:active-sort={unifiDeviceSortKey === 'model'} onclick={() => toggleUnifiDeviceSort('model')}>
										Model{unifiDeviceSortIndicator('model')}
									</button>
								</th>
								<th>
									<button class="sort-btn" class:active-sort={unifiDeviceSortKey === 'ipAddress'} onclick={() => toggleUnifiDeviceSort('ipAddress')}>
										IP{unifiDeviceSortIndicator('ipAddress')}
									</button>
								</th>
								<th>
									<button class="sort-btn" class:active-sort={unifiDeviceSortKey === 'state'} onclick={() => toggleUnifiDeviceSort('state')}>
										Status{unifiDeviceSortIndicator('state')}
									</button>
								</th>
								<th>
									<button class="sort-btn" class:active-sort={unifiDeviceSortKey === 'firmwareVersion'} onclick={() => toggleUnifiDeviceSort('firmwareVersion')}>
										Firmware{unifiDeviceSortIndicator('firmwareVersion')}
									</button>
								</th>
							</tr>
						</thead>
						<tbody>
							{#each sortedUnifiDevices as device (device.id)}
								<tr>
									<td>
										<div class="unifi-device-name">
											{#if unifiDeviceIcon(device) === 'wifi'}
												<svg class="unifi-device-type-icon ap" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
													<path d="M5 12.55a11 11 0 0 1 14.08 0"/>
													<path d="M8.53 16.11a6 6 0 0 1 6.95 0"/>
													<line x1="12" y1="20" x2="12.01" y2="20"/>
												</svg>
											{:else if unifiDeviceIcon(device) === 'switch'}
												<svg class="unifi-device-type-icon switch" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
													<rect x="2" y="6" width="20" height="12" rx="2"/>
													<line x1="6" y1="10" x2="6" y2="14"/>
													<line x1="10" y1="10" x2="10" y2="14"/>
													<line x1="14" y1="10" x2="14" y2="14"/>
													<line x1="18" y1="10" x2="18" y2="14"/>
												</svg>
											{:else if unifiDeviceIcon(device) === 'gateway'}
												<svg class="unifi-device-type-icon gateway" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
													<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
												</svg>
											{:else}
												<svg class="unifi-device-type-icon device" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
													<rect x="4" y="4" width="16" height="16" rx="2"/>
													<rect x="9" y="9" width="6" height="6"/>
												</svg>
											{/if}
											<span>{device.name || 'Unnamed'}</span>
										</div>
									</td>
									<td>
										<span class="badge {unifiDeviceType(device) === 'Gateway' ? 'badge-info' : unifiDeviceType(device) === 'AP' ? 'badge-accent' : 'badge-muted'}">
											{unifiDeviceType(device)}
										</span>
									</td>
									<td class="mono">{device.model || '--'}</td>
									<td class="mono">{device.ipAddress || '--'}</td>
									<td>
										{#if device.state === 'ONLINE'}
											<span class="badge badge-success">Online</span>
										{:else}
											<span class="badge badge-danger">{device.state || 'Unknown'}</span>
										{/if}
									</td>
									<td>
										<span class="mono">{device.firmwareVersion || '--'}</span>
										{#if device.firmwareUpdatable}
											<span class="unifi-firmware-update badge badge-warning">Update</span>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</section>

		<!-- ─── Networks & WiFi Card ──────────────────────────── -->
		<section class="unifi-two-col">
			<!-- Networks -->
			<div class="card">
				<div class="card-header">
					<h2 class="card-title">
						<svg class="unifi-section-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
							<rect x="2" y="2" width="20" height="8" rx="2" ry="2"/>
							<rect x="2" y="14" width="20" height="8" rx="2" ry="2"/>
							<line x1="6" y1="6" x2="6.01" y2="6"/>
							<line x1="6" y1="18" x2="6.01" y2="18"/>
						</svg>
						Networks
					</h2>
					<span class="badge badge-muted">{unifiNetworks.length}</span>
				</div>
				{#if unifiNetworks.length === 0}
					<div class="empty-state">
						<p class="empty-text">No networks found</p>
					</div>
				{:else}
					<div class="detail-table-wrapper">
						<table class="detail-table">
							<thead>
								<tr>
									<th>Name</th>
									<th>VLAN ID</th>
									<th>Type</th>
									<th>Status</th>
								</tr>
							</thead>
							<tbody>
								{#each unifiNetworks as network (network.id)}
									<tr>
										<td>{network.name || '--'}</td>
										<td class="mono">{network.vlanId ?? '--'}</td>
										<td>
											<span class="badge badge-muted">{(network as any).management || '--'}</span>
										</td>
										<td>
											{#if network.enabled !== false}
												<span class="badge badge-success">Enabled</span>
											{:else}
												<span class="badge badge-danger">Disabled</span>
											{/if}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>

			<!-- WiFi -->
			<div class="card">
				<div class="card-header">
					<h2 class="card-title">
						<svg class="unifi-section-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
							<path d="M5 12.55a11 11 0 0 1 14.08 0"/>
							<path d="M1.42 9a16 16 0 0 1 21.16 0"/>
							<path d="M8.53 16.11a6 6 0 0 1 6.95 0"/>
							<line x1="12" y1="20" x2="12.01" y2="20"/>
						</svg>
						WiFi Networks
					</h2>
					<span class="badge badge-muted">{unifiWifi.length}</span>
				</div>
				{#if unifiWifi.length === 0}
					<div class="empty-state">
						<p class="empty-text">No WiFi networks found</p>
					</div>
				{:else}
					<div class="detail-table-wrapper">
						<table class="detail-table">
							<thead>
								<tr>
									<th>SSID</th>
									<th>Band</th>
									<th>Security</th>
									<th>Enabled</th>
								</tr>
							</thead>
							<tbody>
								{#each unifiWifi as ssid (ssid.id)}
									{@const freqs = (ssid as any).broadcastingFrequenciesGHz}
									{@const sec = (ssid as any).securityConfiguration?.type || ssid.security || ''}
									{@const secLower = sec.toLowerCase()}
									<tr>
										<td>{ssid.name || '--'}</td>
										<td class="mono">
											{#if Array.isArray(freqs) && freqs.length > 0}
												{[...freqs].sort((a: number, b: number) => a - b).join(' / ')} GHz
											{:else}
												{ssid.band || '--'}
											{/if}
										</td>
										<td>
											<span class="badge {secLower.includes('wpa3') ? 'badge-success' : secLower.includes('wpa2') ? 'badge-info' : sec ? 'badge-warning' : 'badge-muted'}">
												{sec.replace(/_/g, ' ') || '--'}
											</span>
										</td>
										<td>
											{#if ssid.enabled !== false}
												<span class="health-dot green"></span>
											{:else}
												<span class="health-dot red"></span>
											{/if}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>
		</section>

		<!-- ─── Security Posture Card ─────────────────────────── -->
		<section class="card">
			<div class="card-header">
				<h2 class="card-title">
					<svg class="unifi-section-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
					</svg>
					Security Posture
				</h2>
			</div>
			<div class="unifi-security-grid">
				<div class="detail-stat">
					<div class="detail-stat-label">Firewall Policies</div>
					<div class="detail-stat-value cyan">{unifiFirewall.policies.length}</div>
				</div>
				<div class="detail-stat">
					<div class="detail-stat-label">Firewall Zones</div>
					<div class="detail-stat-value">{unifiFirewall.zones.length}</div>
				</div>
				<div class="detail-stat">
					<div class="detail-stat-label">DNS Policies</div>
					<div class="detail-stat-value">{unifiDnsPolicies.length}</div>
				</div>
				<div class="detail-stat">
					<div class="detail-stat-label">VPN Tunnels</div>
					<div class="detail-stat-value">{unifiVpn.length}</div>
				</div>
			</div>
			{#if unifiFirewall.policies.length > 0}
				<div class="unifi-policy-summary">
					<h3 class="unifi-subsection-title">Firewall Policies</h3>
					<div class="detail-table-wrapper">
						<table class="detail-table">
							<thead>
								<tr>
									<th>Policy</th>
									<th>Action</th>
									<th>Enabled</th>
								</tr>
							</thead>
							<tbody>
								{#each unifiFirewall.policies as policy (policy.id)}
									{@const actionType = (typeof policy.action === 'object' ? policy.action?.type : policy.action) || ''}
									{@const actionLower = actionType.toLowerCase()}
									<tr>
										<td>{policy.name || policy.id}</td>
										<td>
											<span class="badge {actionLower === 'drop' || actionLower === 'reject' ? 'badge-danger' : actionLower === 'allow' || actionLower === 'accept' ? 'badge-success' : 'badge-muted'}">
												{actionType || '--'}
											</span>
										</td>
										<td>
											{#if policy.enabled}
												<span class="badge badge-success">Active</span>
											{:else}
												<span class="badge badge-muted">Disabled</span>
											{/if}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			{/if}
		</section>

		<!-- ─── WAN & VPN Card ────────────────────────────────── -->
		{#if unifiWans.length > 0 || unifiVpn.length > 0}
			<section class="unifi-two-col">
				<!-- WAN Interfaces -->
				{#if unifiWans.length > 0}
					<div class="card">
						<div class="card-header">
							<h2 class="card-title">
								<svg class="unifi-section-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
									<circle cx="12" cy="12" r="10"/>
									<line x1="2" y1="12" x2="22" y2="12"/>
									<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
								</svg>
								WAN Interfaces
							</h2>
							<span class="badge badge-muted">{unifiWans.length}</span>
						</div>
						<div class="detail-table-wrapper">
							<table class="detail-table">
								<thead>
									<tr>
										<th>Name</th>
										<th>Type</th>
										<th>Status</th>
									</tr>
								</thead>
								<tbody>
									{#each unifiWans as wan (wan.id)}
										<tr>
											<td>{wan.name || '--'}</td>
											<td class="mono">{wan.type || '--'}</td>
											<td>
												{#if wan.status?.toLowerCase() === 'connected' || wan.status?.toLowerCase() === 'online'}
													<span class="badge badge-success">{wan.status}</span>
												{:else}
													<span class="badge badge-danger">{wan.status || 'Unknown'}</span>
												{/if}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</div>
				{/if}

				<!-- VPN Tunnels -->
				{#if unifiVpn.length > 0}
					<div class="card">
						<div class="card-header">
							<h2 class="card-title">
								<svg class="unifi-section-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
									<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
									<path d="M7 11V7a5 5 0 0 1 10 0v4"/>
								</svg>
								VPN Tunnels
							</h2>
							<span class="badge badge-muted">{unifiVpn.length}</span>
						</div>
						<div class="detail-table-wrapper">
							<table class="detail-table">
								<thead>
									<tr>
										<th>Name</th>
										<th>Type</th>
										<th>Status</th>
									</tr>
								</thead>
								<tbody>
									{#each unifiVpn as tunnel (tunnel.id)}
										<tr>
											<td>{tunnel.name || '--'}</td>
											<td class="mono">{tunnel.type || '--'}</td>
											<td>
												{#if tunnel.status?.toLowerCase() === 'connected' || tunnel.status?.toLowerCase() === 'established'}
													<span class="badge badge-success">{tunnel.status}</span>
												{:else}
													<span class="badge badge-warning">{tunnel.status || 'Unknown'}</span>
												{/if}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</div>
				{/if}
			</section>
		{/if}
	{/if}

</div>

<style>
	/* ═══════════════════════════════════════════════════════════
	   PAGE LAYOUT
	   ═══════════════════════════════════════════════════════════ */
	.poc-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	/* ═══════════════════════════════════════════════════════════
	   HEADER
	   ═══════════════════════════════════════════════════════════ */
	.page-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: var(--space-xs);
		flex-wrap: wrap;
		gap: var(--space-md);
	}

	.header-left h1 {
		font-size: 1.5rem;
		font-weight: 700;
		letter-spacing: -0.02em;
		color: var(--text-primary);
	}

	.header-subtitle {
		font-size: var(--text-sm);
		color: var(--text-muted);
		margin-top: 2px;
	}

	.header-right {
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	.live-badge {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: 6px 14px;
		background: var(--green-dim);
		border: 1px solid rgba(0, 230, 118, 0.2);
		border-radius: var(--radius-full);
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--green);
		text-transform: uppercase;
		letter-spacing: 0.08em;
	}

	.live-dot {
		width: 8px;
		height: 8px;
		background: var(--green);
		border-radius: 50%;
		animation: pulse-dot 2s ease-in-out infinite;
	}

	@keyframes pulse-dot {
		0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(0, 230, 118, 0.4); }
		50% { opacity: 0.7; box-shadow: 0 0 0 6px rgba(0, 230, 118, 0); }
	}

	.btn-refresh {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: var(--space-sm) var(--space-md);
		background: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		color: var(--text-secondary);
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 500;
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.btn-refresh:hover {
		background: var(--bg-elevated);
		border-color: var(--border-bright);
		color: var(--text-primary);
	}

	.btn-refresh:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	/* ═══════════════════════════════════════════════════════════
	   TOPOLOGY SECTION
	   ═══════════════════════════════════════════════════════════ */
	.topology-section {
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		padding: var(--space-xl);
		position: relative;
		overflow: hidden;
	}

	/* Subtle grid background */
	.topology-section::before {
		content: '';
		position: absolute;
		inset: 0;
		background-image:
			linear-gradient(rgba(0, 212, 255, 0.02) 1px, transparent 1px),
			linear-gradient(90deg, rgba(0, 212, 255, 0.02) 1px, transparent 1px);
		background-size: 40px 40px;
		pointer-events: none;
	}

	.topology-wrapper {
		position: relative;
		width: 100%;
	}

	/* ═══════════════════════════════════════════════════════════
	   PIPELINE GRID
	   ═══════════════════════════════════════════════════════════ */
	.pipeline-grid {
		display: grid;
		grid-template-columns: repeat(6, 1fr);
		grid-template-rows: auto auto auto;
		gap: 12px 0;
		align-items: center;
		justify-items: center;
		position: relative;
		z-index: 2;
		padding: var(--space-lg) 0;
	}

	.pipeline-node {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 10px;
		cursor: pointer;
		position: relative;
		z-index: 3;
	}

	/* Grid placement */
	.pipeline-node[data-node="bridge"]    { grid-column: 1; grid-row: 2; }
	.pipeline-node[data-node="capture"]   { grid-column: 2; grid-row: 2; }
	.pipeline-node[data-node="zeek"]      { grid-column: 3; grid-row: 1; }
	.pipeline-node[data-node="suricata"]  { grid-column: 3; grid-row: 3; }
	.pipeline-node[data-node="filebeat"]  { grid-column: 4; grid-row: 2; }
	.pipeline-node[data-node="logstash"]  { grid-column: 5; grid-row: 2; }
	.pipeline-node[data-node="opensearch"]{ grid-column: 6; grid-row: 2; }

	/* SVG overlay for connections */
	.topology-svg-overlay {
		position: absolute;
		top: 0;
		left: 0;
		width: 100%;
		height: 100%;
		z-index: 1;
		pointer-events: none;
	}

	.node-card {
		width: 140px;
		background: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		padding: var(--space-md) var(--space-sm);
		text-align: center;
		transition: all var(--transition-normal);
		position: relative;
	}

	.node-card::before {
		content: '';
		position: absolute;
		inset: -1px;
		border-radius: var(--radius-lg);
		padding: 1px;
		background: linear-gradient(135deg, transparent 40%, var(--cyan) 100%);
		-webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
		mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
		-webkit-mask-composite: xor;
		mask-composite: exclude;
		opacity: 0;
		transition: opacity var(--transition-normal);
	}

	.pipeline-node:hover .node-card::before,
	.pipeline-node.active .node-card::before {
		opacity: 1;
	}

	.pipeline-node:hover .node-card,
	.pipeline-node.active .node-card {
		border-color: rgba(0, 212, 255, 0.3);
		box-shadow: 0 0 20px rgba(0, 212, 255, 0.15);
		transform: translateY(-2px);
	}

	.pipeline-node.active .node-card {
		background: rgba(0, 212, 255, 0.06);
	}

	.node-icon {
		width: 36px;
		height: 36px;
		border-radius: var(--radius-md);
		display: flex;
		align-items: center;
		justify-content: center;
		margin: 0 auto var(--space-sm);
		font-size: 18px;
	}

	.node-icon.bridge { background: rgba(68, 138, 255, 0.15); color: var(--blue); }
	.node-icon.capture { background: rgba(0, 212, 255, 0.15); color: var(--cyan); }
	.node-icon.zeek { background: rgba(0, 230, 118, 0.15); color: var(--green); }
	.node-icon.suricata { background: rgba(255, 71, 87, 0.15); color: var(--red); }
	.node-icon.filebeat { background: rgba(255, 171, 0, 0.15); color: var(--amber); }
	.node-icon.logstash { background: rgba(179, 136, 255, 0.15); color: var(--purple); }
	.node-icon.opensearch { background: rgba(29, 233, 182, 0.15); color: var(--teal); }

	.node-name {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: var(--space-xs);
	}

	.node-health {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 5px;
		font-size: 0.6875rem;
		color: var(--text-secondary);
	}

	.node-metric {
		font-family: var(--font-mono);
		font-size: 0.6875rem;
		color: var(--text-muted);
		margin-top: var(--space-xs);
	}

	.node-metric .value {
		color: var(--cyan);
		font-weight: 500;
	}

	/* ═══════════════════════════════════════════════════════════
	   CONNECTION LINES (SVG)
	   ═══════════════════════════════════════════════════════════ */
	:global(.conn-line) {
		fill: none;
		stroke-width: 2;
		opacity: 0.2;
	}

	:global(.conn-particles) {
		fill: none;
		stroke-width: 2.5;
		stroke-linecap: round;
		opacity: 0.85;
	}

	:global(.conn-particles.speed-fast) {
		stroke-dasharray: 6 14;
		animation: flow-fast 1.2s linear infinite;
	}
	:global(.conn-particles.speed-normal) {
		stroke-dasharray: 4 16;
		animation: flow-normal 2s linear infinite;
	}
	:global(.conn-particles.speed-slow) {
		stroke-dasharray: 3 20;
		animation: flow-slow 3s linear infinite;
	}

	@keyframes flow-fast   { to { stroke-dashoffset: -20; } }
	@keyframes flow-normal { to { stroke-dashoffset: -20; } }
	@keyframes flow-slow   { to { stroke-dashoffset: -23; } }

	:global(.conn-cyan)     { stroke: rgba(0, 212, 255, 0.2); }
	:global(.conn-cyan-p)   { stroke: var(--cyan); }
	:global(.conn-green)    { stroke: rgba(0, 230, 118, 0.15); }
	:global(.conn-green-p)  { stroke: var(--green); }
	:global(.conn-red)      { stroke: rgba(255, 71, 87, 0.15); }
	:global(.conn-red-p)    { stroke: var(--red); }

	/* ═══════════════════════════════════════════════════════════
	   DETAIL PANEL
	   ═══════════════════════════════════════════════════════════ */
	.detail-panel {
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		overflow: hidden;
		animation: panel-open 300ms ease forwards;
	}

	@keyframes panel-open {
		from { opacity: 0; transform: translateY(-8px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.detail-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-lg) var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
	}

	.detail-header-left {
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	.detail-title {
		font-size: var(--text-lg);
		font-weight: 600;
		color: var(--text-primary);
	}

	.detail-subtitle {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.btn-close-detail {
		background: none;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		color: var(--text-muted);
		width: 28px;
		height: 28px;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 14px;
		transition: all var(--transition-fast);
	}

	.btn-close-detail:hover {
		background: var(--bg-tertiary);
		color: var(--text-primary);
	}

	.detail-body {
		padding: var(--space-lg);
	}

	.detail-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
		gap: var(--space-md);
		margin-bottom: var(--space-lg);
	}

	.detail-stat {
		background: var(--bg-tertiary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-md);
		padding: var(--space-md);
	}

	.detail-stat-label {
		font-size: 0.6875rem;
		font-weight: 500;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		margin-bottom: 6px;
	}

	.detail-stat-value {
		font-family: var(--font-mono);
		font-size: 1.25rem;
		font-weight: 600;
		color: var(--text-primary);
	}

	.detail-stat-value.green { color: var(--green); }
	.detail-stat-value.cyan { color: var(--cyan); }
	.detail-stat-value.amber { color: var(--amber); }
	.detail-stat-value.red { color: var(--red); }

	/* ═══════════════════════════════════════════════════════════
	   DETAIL TABLES
	   ═══════════════════════════════════════════════════════════ */
	.detail-table-wrapper {
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-md);
		overflow: hidden;
		max-height: 400px;
		overflow-y: auto;
	}

	.detail-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}

	.detail-table th {
		background: var(--bg-tertiary);
		padding: 10px 14px;
		text-align: left;
		font-weight: 600;
		font-size: 0.6875rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-muted);
		border-bottom: 1px solid var(--border-dim);
		position: sticky;
		top: 0;
		z-index: 1;
	}

	.detail-table td {
		padding: 10px 14px;
		border-bottom: 1px solid var(--border-dim);
		color: var(--text-secondary);
	}

	.detail-table tr:last-child td { border-bottom: none; }

	.detail-table tr:hover td {
		background-color: var(--bg-tertiary);
	}

	.detail-table .mono {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}

	.health-indicator {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}

	/* Sort buttons */
	.sort-btn {
		background: none;
		border: none;
		color: var(--text-muted);
		font-weight: 600;
		font-size: 0.6875rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		cursor: pointer;
		padding: 0;
		white-space: nowrap;
	}

	.sort-btn:hover {
		color: var(--text-primary);
	}

	.sort-btn.active-sort {
		color: var(--accent);
	}

	/* ═══════════════════════════════════════════════════════════
	   TEMPLATES SECTION
	   ═══════════════════════════════════════════════════════════ */
	.templates-section {
		margin-top: var(--space-lg);
		padding-top: var(--space-lg);
		border-top: 1px solid var(--border-dim);
	}

	.templates-toggle {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		background: none;
		border: none;
		color: var(--text-primary);
		font-size: var(--text-base);
		font-weight: 600;
		cursor: pointer;
		padding: 0;
		font-family: var(--font-sans);
	}

	.templates-toggle:hover {
		color: var(--accent);
	}

	.chevron {
		transition: transform var(--transition-fast);
	}

	.chevron.rotated {
		transform: rotate(90deg);
	}

	/* ═══════════════════════════════════════════════════════════
	   HEAP BAR
	   ═══════════════════════════════════════════════════════════ */
	.heap-bar-container {
		height: 10px;
		background: var(--bg-primary);
		border-radius: 5px;
		overflow: hidden;
		margin: var(--space-sm) 0;
	}

	.heap-bar-fill {
		height: 100%;
		border-radius: 5px;
		transition: width 500ms ease;
	}

	.heap-labels {
		display: flex;
		justify-content: space-between;
		font-size: 0.6875rem;
		color: var(--text-muted);
		font-family: var(--font-mono);
	}

	/* ═══════════════════════════════════════════════════════════
	   QUICK STATS BAR
	   ═══════════════════════════════════════════════════════════ */
	.stats-bar {
		display: grid;
		grid-template-columns: repeat(6, 1fr);
		gap: var(--space-md);
	}

	.stat-card-mini {
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-md) var(--space-lg);
		text-align: center;
	}

	.stat-label {
		font-size: 0.6875rem;
		font-weight: 500;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		margin-bottom: 6px;
	}

	.stat-value {
		font-family: var(--font-mono);
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--text-primary);
		line-height: 1.2;
	}

	.stat-value.green { color: var(--green); }
	.stat-value.cyan { color: var(--cyan); }
	.stat-value.amber { color: var(--amber); }

	.stat-unit {
		font-size: var(--text-xs);
		font-weight: 400;
		color: var(--text-muted);
		margin-left: 2px;
	}

	/* ═══════════════════════════════════════════════════════════
	   SERVICE LINKS
	   ═══════════════════════════════════════════════════════════ */
	.services-row {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--space-md);
	}

	.service-link {
		display: flex;
		align-items: center;
		gap: 14px;
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-md) var(--space-lg);
		text-decoration: none;
		color: var(--text-primary);
		transition: all 200ms ease;
	}

	.service-link:hover {
		border-color: var(--border-bright);
		background: var(--bg-tertiary);
		transform: translateY(-1px);
	}

	.service-icon-box {
		width: 40px;
		height: 40px;
		border-radius: var(--radius-md);
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 20px;
		flex-shrink: 0;
	}

	.service-icon-box.os { background: rgba(29, 233, 182, 0.12); color: var(--teal); }
	.service-icon-box.grafana { background: rgba(255, 109, 0, 0.12); color: var(--orange); }
	.service-icon-box.cyberchef { background: rgba(179, 136, 255, 0.12); color: var(--purple); }

	.service-info-text .service-name {
		font-weight: 600;
		font-size: var(--text-base);
	}

	.service-info-text .service-desc {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.service-arrow {
		margin-left: auto;
		color: var(--text-muted);
		font-size: var(--text-lg);
	}

	/* ═══════════════════════════════════════════════════════════
	   HEALTH DOT (scoped overrides for this page)
	   ═══════════════════════════════════════════════════════════ */
	.health-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		display: inline-block;
		flex-shrink: 0;
	}

	.health-dot.green { background: var(--green); box-shadow: 0 0 6px rgba(0, 230, 118, 0.5); }
	.health-dot.yellow { background: var(--amber); box-shadow: 0 0 6px rgba(255, 171, 0, 0.5); }
	.health-dot.red { background: var(--red); box-shadow: 0 0 6px rgba(255, 71, 87, 0.5); }

	/* ═══════════════════════════════════════════════════════════
	   BADGE (scoped)
	   ═══════════════════════════════════════════════════════════ */
	.badge {
		display: inline-flex;
		align-items: center;
		gap: var(--space-xs);
		padding: 2px 8px;
		font-size: var(--text-xs);
		font-weight: 600;
		border-radius: var(--radius-full);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		line-height: 1.5;
	}

	.badge-muted {
		background-color: rgba(85, 95, 115, 0.15);
		color: var(--text-muted);
	}

	/* ═══════════════════════════════════════════════════════════
	   UNIFI INTEGRATION
	   ═══════════════════════════════════════════════════════════ */
	.unifi-section-icon {
		vertical-align: -3px;
		margin-right: var(--space-xs);
	}

	.unifi-not-configured {
		border-style: dashed;
	}

	.unifi-unconfigured-body {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	.unifi-unconfigured-text {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	.unifi-error-banner {
		margin-bottom: 0;
	}

	.unifi-loading-text {
		color: var(--text-muted);
		font-size: var(--text-sm);
		margin-top: var(--space-sm);
	}

	.unifi-device-name {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.unifi-device-type-icon {
		flex-shrink: 0;
	}

	.unifi-device-type-icon.ap { color: var(--cyan); }
	.unifi-device-type-icon.switch { color: var(--blue); }
	.unifi-device-type-icon.gateway { color: var(--green); }
	.unifi-device-type-icon.device { color: var(--text-muted); }

	.unifi-firmware-update {
		margin-left: var(--space-sm);
		font-size: 0.625rem;
	}

	.unifi-two-col {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-md);
	}

	.unifi-security-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--space-md);
		margin-bottom: var(--space-lg);
	}

	.unifi-policy-summary {
		margin-top: var(--space-md);
	}

	.unifi-subsection-title {
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: var(--space-md);
	}

	/* ═══════════════════════════════════════════════════════════
	   RESPONSIVE
	   ═══════════════════════════════════════════════════════════ */
	@media (max-width: 1100px) {
		.pipeline-grid {
			grid-template-columns: repeat(3, 1fr);
			grid-template-rows: auto;
		}
		.pipeline-node[data-node="bridge"]    { grid-column: 1; grid-row: 1; }
		.pipeline-node[data-node="capture"]   { grid-column: 2; grid-row: 1; }
		.pipeline-node[data-node="zeek"]      { grid-column: 3; grid-row: 1; }
		.pipeline-node[data-node="suricata"]  { grid-column: 1; grid-row: 2; }
		.pipeline-node[data-node="filebeat"]  { grid-column: 2; grid-row: 2; }
		.pipeline-node[data-node="logstash"]  { grid-column: 3; grid-row: 2; }
		.pipeline-node[data-node="opensearch"]{ grid-column: 2; grid-row: 3; }
		.topology-svg-overlay { display: none; }
		.stats-bar { grid-template-columns: repeat(3, 1fr); }
		.services-row { grid-template-columns: 1fr; }
		.unifi-two-col { grid-template-columns: 1fr; }
		.unifi-security-grid { grid-template-columns: repeat(2, 1fr); }
	}

	@media (max-width: 700px) {
		.page-header {
			flex-direction: column;
			align-items: flex-start;
		}
		.stats-bar { grid-template-columns: repeat(2, 1fr); }
		.detail-grid { grid-template-columns: 1fr 1fr; }
		.unifi-security-grid { grid-template-columns: 1fr; }
		.pipeline-grid {
			grid-template-columns: repeat(2, 1fr);
		}
		.pipeline-node[data-node="bridge"]    { grid-column: 1; grid-row: 1; }
		.pipeline-node[data-node="capture"]   { grid-column: 2; grid-row: 1; }
		.pipeline-node[data-node="zeek"]      { grid-column: 1; grid-row: 2; }
		.pipeline-node[data-node="suricata"]  { grid-column: 2; grid-row: 2; }
		.pipeline-node[data-node="filebeat"]  { grid-column: 1; grid-row: 3; }
		.pipeline-node[data-node="logstash"]  { grid-column: 2; grid-row: 3; }
		.pipeline-node[data-node="opensearch"]{ grid-column: 1; grid-row: 4; }
	}
</style>
