<script lang="ts">
	/**
	 * Device Intelligence Dashboard v2
	 *
	 * Sections:
	 *   1. Device identity header (icon, meta, risk gauge, status, time range)
	 *   2. 6 stat cards (bandwidth DL/UL, upload ratio, connections, alerts, unique dests, first/last seen)
	 *   3. Bandwidth over time chart (dual series DL/UL via TimeSeriesChart)
	 *   4. Traffic intelligence (categories + top services)
	 *   5. Security posture (risk factor breakdown + recent alerts)
	 *   6. Network detail (top destinations, DNS activity, top ports)
	 *   7. Recent connections (protocol filters, clickable rows → drawer)
	 */

	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { onDestroy } from 'svelte';
	import TimeSeriesChart from '$components/charts/TimeSeriesChart.svelte';
	import HorizontalBarList from '$components/HorizontalBarList.svelte';
	import IPAddress from '$components/IPAddress.svelte';
	import ConnectionDrawer from '$components/ConnectionDrawer.svelte';
	import {
		getDeviceDetail,
		getDeviceConnections,
		getDeviceCategories,
		getDeviceAlerts,
		getDevicePorts,
		getDeviceRiskScore,
	} from '$api/devices';
	import type {
		DeviceDetail,
		DeviceConnection,
		DeviceCategory,
		DeviceAlert,
		DevicePort,
		RiskFactor,
	} from '$api/devices';

	// ---------------------------------------------------------------------------
	// Category colors (same as traffic category pages)
	// ---------------------------------------------------------------------------

	const CATEGORY_COLORS: Record<string, string> = {
		streaming: 'var(--red)', gaming: 'var(--purple)', social: 'var(--blue)',
		communication: 'var(--amber)', work: 'var(--green)', iot: 'var(--orange)',
		cloud: 'var(--cyan)', file_transfer: 'var(--teal)', dns: 'var(--text-muted)',
		email: 'var(--pink)', web: 'var(--accent)', security: 'var(--green)',
		shopping: 'var(--orange)', news: 'var(--blue)', ads: 'var(--text-muted)',
		updates: 'var(--teal)', suspicious: 'var(--red)', other: 'var(--text-muted)',
	};

	const DEVICE_ICONS: Record<string, string> = {
		ios: '\u{1F4F1}', android: '\u{1F4F1}', windows: '\u{1F4BB}', macos: '\u{1F4BB}',
		linux: '\u{1F5A5}', chromeos: '\u{1F4BB}', default: '\u{1F4E1}',
	};

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let deviceIp = $derived(decodeURIComponent(($page.params as Record<string, string>).ip ?? ''));

	// Core data
	let loading = $state(true);
	let device = $state<DeviceDetail | null>(null);
	let categories = $state<DeviceCategory[]>([]);
	let alerts = $state<DeviceAlert[]>([]);
	let alertsTotal = $state(0);
	let ports = $state<DevicePort[]>([]);
	let riskScore = $state(0);
	let riskLevel = $state('low');
	let riskFactors = $state<RiskFactor[]>([]);

	// Connections
	let connections = $state<DeviceConnection[]>([]);
	let connectionsLoading = $state(false);
	let connectionsPage = $state(1);
	let connectionsTotalPages = $state(0);
	let connectionsTotal = $state(0);
	const connectionsPageSize = 25;
	let protoFilter = $state('all');

	// UI state
	let autoRefresh = $state(false);
	let autoRefreshTimer: ReturnType<typeof setInterval> | null = null;
	let lastUpdated = $state(new Date());
	let selectedConnection = $state<Record<string, unknown> | null>(null);
	let drawerOpen = $state(false);

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	let deviceIcon = $derived(DEVICE_ICONS[(device?.os_hint ?? '').toLowerCase()] ?? DEVICE_ICONS.default);
	let isOnline = $derived(device?.last_seen ? (Date.now() - new Date(device.last_seen).getTime()) < 5 * 60 * 1000 : false);
	let statusLabel = $derived(isOnline ? 'Online' : device?.last_seen ? (Date.now() - new Date(device.last_seen).getTime() < 60 * 60 * 1000 ? 'Idle' : 'Offline') : 'Unknown');

	let origBytes = $derived(device?.orig_bytes ?? 0);
	let respBytes = $derived(device?.resp_bytes ?? 0);
	let totalBytes = $derived(device?.total_bytes ?? 0);
	let uploadRatio = $derived(totalBytes > 0 ? Math.round((origBytes / totalBytes) * 100) : 0);
	let uploadRatioColor = $derived(uploadRatio < 40 ? 'var(--green)' : uploadRatio < 70 ? 'var(--amber)' : 'var(--red)');
	let uploadRatioLabel = $derived(uploadRatio < 40 ? 'Normal' : uploadRatio < 70 ? 'Elevated' : 'High');

	let chartData = $derived(
		device?.bandwidth_series?.map((p) => ({
			time: p.timestamp,
			value: p.bytes,
		})) ?? [],
	);

	let isNewDevice = $derived(device?.first_seen ? (Date.now() - new Date(device.first_seen).getTime()) < 24 * 60 * 60 * 1000 : false);

	// Risk gauge arc calculation
	let riskArcPath = $derived.by(() => {
		const angle = Math.min(riskScore / 100, 1) * 180;
		const rad = (angle * Math.PI) / 180;
		const endX = 60 - 50 * Math.cos(rad);
		const endY = 65 - 50 * Math.sin(rad);
		const largeArc = angle > 180 ? 1 : 0;
		return `M 10 65 A 50 50 0 ${largeArc} 1 ${endX} ${endY}`;
	});

	let lastUpdatedText = $derived.by(() => {
		const diff = Math.floor((Date.now() - lastUpdated.getTime()) / 1000);
		if (diff < 5) return 'just now';
		if (diff < 60) return `${diff}s ago`;
		return `${Math.floor(diff / 60)}m ago`;
	});

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchAll() {
		loading = true;
		try {
			const [deviceRes, catRes, alertRes, portRes, riskRes] = await Promise.all([
				getDeviceDetail(deviceIp),
				getDeviceCategories(deviceIp),
				getDeviceAlerts(deviceIp, { limit: 10 }),
				getDevicePorts(deviceIp),
				getDeviceRiskScore(deviceIp),
			]);
			device = deviceRes.device;
			categories = catRes.categories;
			alerts = alertRes.alerts;
			alertsTotal = alertRes.total;
			ports = portRes.ports;
			riskScore = riskRes.score;
			riskLevel = riskRes.level;
			riskFactors = riskRes.factors;
			lastUpdated = new Date();
		} catch {
			device = null;
		} finally {
			loading = false;
		}
		fetchConnections(1);
	}

	async function fetchConnections(pageNum: number = 1) {
		connectionsLoading = true;
		try {
			const res = await getDeviceConnections(deviceIp, {
				page: pageNum,
				size: connectionsPageSize,
			});
			connections = res.connections;
			connectionsPage = res.page;
			connectionsTotalPages = res.total_pages;
			connectionsTotal = res.total;
		} catch {
			connections = [];
		} finally {
			connectionsLoading = false;
		}
	}

	$effect(() => {
		const ip = deviceIp;
		if (ip) fetchAll();
	});

	// Auto-refresh
	$effect(() => {
		if (autoRefreshTimer) clearInterval(autoRefreshTimer);
		if (autoRefresh) {
			autoRefreshTimer = setInterval(() => fetchAll(), 30_000);
		}
		return () => { if (autoRefreshTimer) clearInterval(autoRefreshTimer); };
	});

	onDestroy(() => { if (autoRefreshTimer) clearInterval(autoRefreshTimer); });

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function formatBytes(bytes: number): string {
		if (bytes === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
	}

	function formatNumber(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
		return n.toLocaleString();
	}

	function formatDate(dateStr: string): string {
		if (!dateStr) return '--';
		try { return new Date(dateStr).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); } catch { return dateStr; }
	}

	function timeAgo(dateStr: string): string {
		if (!dateStr) return '--';
		const diffMs = Date.now() - new Date(dateStr).getTime();
		const mins = Math.floor(diffMs / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h ago`;
		return `${Math.floor(hours / 24)}d ago`;
	}

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

	function formatDuration(startVal: unknown, endVal: unknown): string {
		const s = asString(startVal);
		const e = asString(endVal);
		if (!s || !e) return '--';
		const diffMs = new Date(e).getTime() - new Date(s).getTime();
		if (isNaN(diffMs) || diffMs < 0) return '--';
		if (diffMs < 1000) return `${Math.round(diffMs)}ms`;
		const sec = diffMs / 1000;
		if (sec < 60) return `${sec.toFixed(1)}s`;
		return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`;
	}

	function riskColor(level: string): string {
		if (level === 'critical') return 'var(--red)';
		if (level === 'high') return 'var(--red)';
		if (level === 'medium') return 'var(--amber)';
		return 'var(--green)';
	}

	function sevLabel(sev: number): string {
		if (sev === 1) return 'HIGH';
		if (sev === 2) return 'MED';
		return 'LOW';
	}

	function sevClass(sev: number): string {
		if (sev === 1) return 'sev-high';
		if (sev === 2) return 'sev-med';
		return 'sev-low';
	}

	function openDrawer(conn: Record<string, unknown>) {
		selectedConnection = conn;
		drawerOpen = true;
	}

	function closeDrawer() {
		drawerOpen = false;
		selectedConnection = null;
	}

	// Filter connections by protocol (client-side)
	let filteredConnections = $derived.by(() => {
		if (protoFilter === 'all') return connections;
		return connections.filter((c) => {
			const proto = asString(getField(c, 'network.transport')).toLowerCase();
			return proto === protoFilter;
		});
	});
</script>

<svelte:head>
	<title>{deviceIp} | Device Intelligence | NetTap</title>
</svelte:head>

<div class="device-page">
	{#if loading && !device}
		<div class="loading-state">
			<div class="loading-spinner"></div>
			<span class="text-muted">Loading device data...</span>
		</div>
	{:else if !device || !device.ip}
		<div class="empty-state">
			<p class="empty-text">Device not found: {deviceIp}</p>
			<button class="btn-back" onclick={() => goto('/devices')}>Return to Devices</button>
		</div>
	{:else}
		<!-- ============================================================
		     Section 1: Device Identity Header
		     ============================================================ -->
		<div class="device-header">
			<div class="header-top">
				<button class="back-link" onclick={() => goto('/devices')}>&larr; Back to Devices</button>
				<div class="header-controls">
					<div class="pills">
						<button class="pill active">24h</button>
						<button class="pill">7d</button>
						<button class="pill">30d</button>
					</div>
					<button class="auto-btn" class:active={autoRefresh} onclick={() => (autoRefresh = !autoRefresh)}>
						<span class="auto-dot"></span> Auto
					</button>
				</div>
			</div>
			<div class="header-main">
				<div class="device-icon-area">
					<div class="device-icon-box">
						{deviceIcon}
						<span class="status-dot" class:online={isOnline} class:idle={!isOnline && statusLabel === 'Idle'}></span>
					</div>
					<span class="status-label" class:online={isOnline}>{statusLabel}</span>
				</div>
				<div class="device-info">
					<h1 class="mono">{device.ip}</h1>
					{#if device.hostname}
						<div class="device-hostname">{device.hostname}</div>
					{/if}
					<div class="device-meta">
						{#if device.mac}<span class="meta-item"><span class="meta-label">MAC</span> <span class="meta-value mono">{device.mac}</span></span>{/if}
						{#if device.manufacturer}<span class="meta-item"><span class="meta-label">Vendor</span> <span class="meta-value">{device.manufacturer}</span></span>{/if}
						<span class="meta-item"><span class="meta-label">Updated</span> <span class="meta-value">{lastUpdatedText}</span></span>
					</div>
					<div class="device-badges">
						{#if device.os_hint}<span class="badge badge-os">{device.os_hint}</span>{/if}
						{#if isNewDevice}<span class="badge badge-new">NEW</span>{/if}
					</div>
					{#if device.protocols?.length}
						<div class="protocol-list">
							{#each device.protocols.slice(0, 8) as proto}<span class="proto-tag">{proto}</span>{/each}
						</div>
					{/if}
				</div>
				<div class="risk-area">
					<div class="risk-gauge">
						<svg viewBox="0 0 120 70">
							<path d="M 10 65 A 50 50 0 0 1 110 65" fill="none" stroke="var(--bg-tertiary)" stroke-width="10" stroke-linecap="round" />
							<path d={riskArcPath} fill="none" stroke={riskColor(riskLevel)} stroke-width="10" stroke-linecap="round" />
							<text x="60" y="52" text-anchor="middle" fill={riskColor(riskLevel)} font-family="var(--font-mono)" font-size="22" font-weight="700">{riskScore}</text>
							<text x="60" y="66" text-anchor="middle" fill="var(--text-muted)" font-size="9" font-weight="600" letter-spacing="0.08em">RISK</text>
						</svg>
					</div>
					<span class="risk-badge" style="color: {riskColor(riskLevel)}; background: color-mix(in srgb, {riskColor(riskLevel)} 12%, transparent);">{riskLevel.toUpperCase()}</span>
				</div>
			</div>
		</div>

		<!-- ============================================================
		     Section 2: Stat Cards
		     ============================================================ -->
		<div class="stats-grid">
			<div class="stat-card stat-accent">
				<div class="stat-label">Total Bandwidth</div>
				<div class="stat-value accent">{formatBytes(totalBytes)}</div>
				<div class="split-bar">
					<div class="split-dl" style="width: {totalBytes > 0 ? (respBytes / totalBytes) * 100 : 50}%;"></div>
					<div class="split-ul" style="width: {totalBytes > 0 ? (origBytes / totalBytes) * 100 : 50}%;"></div>
				</div>
				<div class="split-legend">
					<span class="legend-item"><span class="legend-dot" style="background:var(--cyan);"></span>{formatBytes(respBytes)}</span>
					<span class="legend-item"><span class="legend-dot" style="background:var(--purple);"></span>{formatBytes(origBytes)}</span>
				</div>
			</div>
			<div class="stat-card">
				<div class="stat-label">Upload Ratio</div>
				<div class="stat-value" style="color: {uploadRatioColor};">{uploadRatio}%</div>
				<div class="ratio-bar"><div class="ratio-fill" style="width: {uploadRatio}%; background: {uploadRatioColor};"></div></div>
				<div class="stat-sub">{uploadRatioLabel}</div>
			</div>
			<div class="stat-card">
				<div class="stat-label">Connections</div>
				<div class="stat-value">{formatNumber(device.connection_count)}</div>
			</div>
			<div class="stat-card">
				<div class="stat-label">Alerts</div>
				<div class="stat-value" style="color: {device.alert_count > 0 ? 'var(--red)' : 'var(--text-primary)'};">{formatNumber(device.alert_count)}</div>
			</div>
			<div class="stat-card">
				<div class="stat-label">Unique Destinations</div>
				<div class="stat-value">{formatNumber(device.unique_destinations ?? 0)}</div>
			</div>
			<div class="stat-card">
				<div class="stat-label">First Seen</div>
				<div class="stat-value" style="font-size: var(--text-lg);">{formatDate(device.first_seen)}</div>
				<div class="stat-sub">Last: {timeAgo(device.last_seen)}</div>
			</div>
		</div>

		<!-- ============================================================
		     Section 3: Bandwidth Chart
		     ============================================================ -->
		{#if chartData.length > 0}
			<div class="section-card">
				<div class="section-header">
					<span class="section-title">Bandwidth Over Time</span>
				</div>
				<div class="chart-body">
					<TimeSeriesChart data={chartData} height={220} color="var(--cyan)" formatValue={formatBytes} />
				</div>
			</div>
		{/if}

		<!-- ============================================================
		     Section 4: Traffic Intelligence
		     ============================================================ -->
		<div class="two-col">
			<div class="card">
				<div class="card-header">
					<span class="card-title">Traffic Categories</span>
					<span class="card-badge">{categories.length} categories</span>
				</div>
				{#if categories.length > 0}
					<HorizontalBarList
						items={categories.map((c, i) => ({
							key: `${c.name}-${i}`,
							label: c.label,
							value: c.total_bytes,
							formattedValue: formatBytes(c.total_bytes),
							color: CATEGORY_COLORS[c.name] ?? 'var(--text-muted)',
							href: `/traffic/${c.name}`,
						}))}
						showDot={true}
						labelWidth={130}
						barHeight={10}
					/>
				{:else}
					<p class="empty-msg">No category data available.</p>
				{/if}
			</div>
			<div class="card">
				<div class="card-header">
					<span class="card-title">Top Services</span>
					<span class="card-badge">by bytes</span>
				</div>
				{#if device.top_services?.length}
					<div class="service-list">
						{#each device.top_services as svc, i (`${svc.name}-${i}`)}
							<div class="svc-row">
								<span class="svc-name">{svc.name}</span>
								<span class="svc-bytes mono">{formatBytes(svc.bytes)}</span>
								<span class="svc-conns mono">{formatNumber(svc.connections)} conn</span>
							</div>
						{/each}
					</div>
				{:else}
					<p class="empty-msg">No service data available.</p>
				{/if}
			</div>
		</div>

		<!-- ============================================================
		     Section 5: Security Posture
		     ============================================================ -->
		<div class="two-col">
			<div class="card">
				<div class="card-header">
					<span class="card-title">Risk Factor Breakdown</span>
					<span class="card-badge">{riskScore} / 100</span>
				</div>
				{#if riskFactors.length > 0}
					<div class="risk-factor-list">
						{#each riskFactors as factor, i (`${factor.name}-${i}`)}
							{@const pct = factor.max > 0 ? (factor.score / factor.max) * 100 : 0}
							{@const fColor = pct > 66 ? 'var(--red)' : pct > 33 ? 'var(--amber)' : 'var(--green)'}
							<div class="risk-factor">
								<span class="rf-name">{factor.name.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())}</span>
								<div class="rf-bar"><div class="rf-fill" style="width: {pct}%; background: {fColor};"></div></div>
								<span class="rf-score mono" style="color: {fColor};">{factor.score} / {factor.max}</span>
							</div>
						{/each}
					</div>
				{:else}
					<p class="empty-msg">No risk data available.</p>
				{/if}
			</div>
			<div class="card">
				<div class="card-header">
					<span class="card-title">Recent Alerts</span>
					<span class="card-badge">{formatNumber(alertsTotal)} total</span>
				</div>
				{#if alerts.length > 0}
					<div class="alert-list">
						{#each alerts as alert, i (`${alert.signature_id}-${i}`)}
							<div class="alert-row">
								<span class="alert-sev {sevClass(alert.severity)}">{sevLabel(alert.severity)}</span>
								<div class="alert-info">
									<div class="alert-sig">{alert.signature}</div>
									<div class="alert-cat">{alert.category}</div>
								</div>
								<span class="alert-time mono">{new Date(alert.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
							</div>
						{/each}
					</div>
					<a href="/alerts?ip={deviceIp}" class="card-link">View all alerts &rarr;</a>
				{:else}
					<p class="empty-msg">No alerts for this device.</p>
				{/if}
			</div>
		</div>

		<!-- ============================================================
		     Section 6: Network Detail
		     ============================================================ -->
		<div class="three-col">
			<!-- Top Destinations -->
			<div class="card">
				<div class="card-header"><span class="card-title">Top Destinations</span></div>
				{#if device.top_destinations?.length}
					<div class="table-wrap">
						<table class="data-table">
							<thead><tr><th>Destination</th><th>Bytes</th><th>Conn</th></tr></thead>
							<tbody>
								{#each device.top_destinations.slice(0, 8) as dest, i (`${dest.ip}-${i}`)}
									<tr>
										<td><span class="mono td-sm"><IPAddress ip={dest.ip} /></span></td>
										<td class="mono td-sm">{formatBytes(dest.bytes)}</td>
										<td class="mono td-sm">{formatNumber(dest.connections)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<p class="empty-msg">No destination data.</p>
				{/if}
			</div>

			<!-- DNS Activity -->
			<div class="card">
				<div class="card-header"><span class="card-title">DNS Activity</span></div>
				{#if device.dns_queries?.length}
					<div class="table-wrap">
						<table class="data-table">
							<thead><tr><th>Domain</th><th>Count</th></tr></thead>
							<tbody>
								{#each device.dns_queries.filter((d) => !d.domain.includes('._tcp.') && !d.domain.includes('._udp.') && !d.domain.endsWith('.arpa')).slice(0, 10) as q, i (`${q.domain}-${i}`)}
									<tr>
										<td class="td-sm" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title={q.domain}>{q.domain}</td>
										<td class="mono td-sm">{formatNumber(q.count)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<p class="empty-msg">No DNS data.</p>
				{/if}
			</div>

			<!-- Top Ports -->
			<div class="card">
				<div class="card-header"><span class="card-title">Top Ports Used</span></div>
				{#if ports.length > 0}
					<div class="table-wrap">
						<table class="data-table">
							<thead><tr><th>Port</th><th>Service</th><th>Conn</th></tr></thead>
							<tbody>
								{#each ports.slice(0, 8) as p, i (`${p.port}-${i}`)}
									<tr>
										<td class="mono td-sm" class:port-suspicious={p.suspicious}>{p.port}</td>
										<td class="td-sm" class:port-suspicious={p.suspicious}>{p.service}{#if p.suspicious} &#x26A0;{/if}</td>
										<td class="mono td-sm">{formatNumber(p.connections)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<p class="empty-msg">No port data.</p>
				{/if}
			</div>
		</div>

		<!-- ============================================================
		     Section 7: Recent Connections
		     ============================================================ -->
		<div class="card">
			<div class="card-header">
				<span class="card-title">Recent Connections</span>
				<span class="card-badge">{formatNumber(connectionsTotal)} total</span>
			</div>
			<div class="conn-toolbar">
				<div class="proto-pills">
					{#each ['all', 'tcp', 'udp', 'icmp'] as p}
						<button class="proto-pill" class:active={protoFilter === p} onclick={() => (protoFilter = p)}>{p.toUpperCase()}</button>
					{/each}
				</div>
			</div>
			{#if connectionsLoading}
				<div class="loading-inline"><span class="text-muted">Loading connections...</span></div>
			{:else}
				<div class="table-wrap">
					<table class="data-table">
						<thead>
							<tr><th>Time</th><th>Destination</th><th>Proto</th><th>Service</th><th>Duration</th><th>DL</th><th>UL</th></tr>
						</thead>
						<tbody>
							{#each filteredConnections as conn, i (`${conn._id}-${i}`)}
								<tr class="conn-row" class:selected={selectedConnection === conn} onclick={() => openDrawer(conn)}>
									<td class="mono td-sm">{new Date(asString(getField(conn, '@timestamp'))).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</td>
									<td class="mono td-sm">{asString(getField(conn, 'destination.ip'))}:{asString(getField(conn, 'destination.port'))}</td>
									<td><span class="proto-tag">{asString(getField(conn, 'network.transport'))}</span></td>
									<td class="td-sm">{asString(getField(conn, 'network.protocol')) || asString(getField(conn, 'network.transport'))}</td>
									<td class="mono td-sm">{formatDuration(getField(conn, 'event.start'), getField(conn, 'event.end'))}</td>
									<td class="mono td-sm dl-col">{formatBytes(Number(asString(getField(conn, 'destination.bytes') ?? getField(conn, 'server.bytes'))) || 0)}</td>
									<td class="mono td-sm ul-col">{formatBytes(Number(asString(getField(conn, 'source.bytes') ?? getField(conn, 'client.bytes'))) || 0)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				<div class="pagination">
					<button class="page-btn" disabled={connectionsPage <= 1} onclick={() => fetchConnections(connectionsPage - 1)}>Previous</button>
					<span class="page-info mono">Page {connectionsPage} of {connectionsTotalPages}</span>
					<button class="page-btn" disabled={connectionsPage >= connectionsTotalPages} onclick={() => fetchConnections(connectionsPage + 1)}>Next</button>
				</div>
			{/if}
			<div class="quick-links">
				<a href="/logs?filter={deviceIp}" class="quick-link">View in Log Explorer &rarr;</a>
				<a href="/connections?ip={deviceIp}" class="quick-link">Filter Connections &rarr;</a>
			</div>
		</div>
	{/if}
</div>

<!-- Connection Drill-Down Drawer -->
{#if drawerOpen && selectedConnection}
	<ConnectionDrawer connection={selectedConnection} deviceIp={deviceIp} onclose={closeDrawer} />
{/if}

<style>
	.device-page { display: flex; flex-direction: column; gap: var(--space-lg); }

	/* Loading / Empty */
	.loading-state { display: flex; align-items: center; justify-content: center; gap: var(--space-md); padding: var(--space-3xl); }
	.loading-inline { padding: var(--space-xl); text-align: center; }
	.empty-state { text-align: center; padding: var(--space-3xl); }
	.empty-text { font-size: var(--text-lg); color: var(--text-primary); margin-bottom: var(--space-md); }
	.empty-msg { padding: var(--space-lg); text-align: center; font-size: var(--text-sm); color: var(--text-muted); }
	.btn-back { padding: 6px 14px; background: var(--bg-tertiary); border: 1px solid var(--border-dim); border-radius: var(--radius-sm); color: var(--text-secondary); font-size: var(--text-sm); cursor: pointer; }

	/* ---------------------------------------------------------------- Header */
	.device-header {
		background: var(--bg-secondary); border: 1px solid var(--border-dim);
		border-radius: var(--radius-lg); padding: var(--space-lg);
		position: relative; overflow: hidden;
	}
	.device-header::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: linear-gradient(90deg, var(--cyan), var(--purple), var(--cyan)); opacity: 0.7; }
	.header-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-lg); }
	.back-link { font-size: var(--text-sm); color: var(--text-muted); text-decoration: none; background: none; border: none; cursor: pointer; font-family: var(--font-sans); transition: color var(--transition-fast); }
	.back-link:hover { color: var(--accent); }
	.header-controls { display: flex; align-items: center; gap: var(--space-md); }
	.header-main { display: grid; grid-template-columns: auto 1fr auto; gap: var(--space-lg); align-items: start; }

	.device-icon-area { display: flex; flex-direction: column; align-items: center; gap: var(--space-sm); }
	.device-icon-box { width: 64px; height: 64px; border-radius: var(--radius-lg); display: flex; align-items: center; justify-content: center; font-size: 1.75rem; background: var(--cyan-dim); border: 1px solid rgba(0,212,255,0.2); position: relative; }
	.status-dot { position: absolute; bottom: -2px; right: -2px; width: 14px; height: 14px; border-radius: 50%; background: var(--text-dim); border: 3px solid var(--bg-secondary); }
	.status-dot.online { background: var(--green); box-shadow: 0 0 8px rgba(0,230,118,0.5); animation: pulse 2s infinite; }
	.status-dot.idle { background: var(--amber); }
	@keyframes pulse { 0%,100% { box-shadow: 0 0 4px rgba(0,230,118,0.3); } 50% { box-shadow: 0 0 12px rgba(0,230,118,0.6); } }
	.status-label { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-dim); }
	.status-label.online { color: var(--green); }

	.device-info { display: flex; flex-direction: column; gap: var(--space-xs); }
	.device-info h1 { font-size: var(--text-2xl); font-weight: 700; letter-spacing: -0.02em; }
	.device-hostname { font-size: var(--text-lg); color: var(--text-secondary); }
	.device-meta { display: flex; flex-wrap: wrap; gap: var(--space-sm) var(--space-lg); margin-top: var(--space-xs); }
	.meta-item { display: flex; align-items: center; gap: 6px; font-size: var(--text-xs); color: var(--text-muted); }
	.meta-label { font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; }
	.meta-value { color: var(--text-secondary); }
	.device-badges { display: flex; gap: var(--space-sm); margin-top: var(--space-xs); }
	.badge { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: var(--radius-sm); font-size: var(--text-xs); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
	.badge-os { background: rgba(179,136,255,0.12); color: var(--purple); border: 1px solid rgba(179,136,255,0.2); }
	.badge-new { background: rgba(0,230,118,0.12); color: var(--green); border: 1px solid rgba(0,230,118,0.2); }
	.protocol-list { display: flex; gap: 4px; margin-top: var(--space-xs); }
	.proto-tag { padding: 2px 8px; border-radius: var(--radius-sm); font-family: var(--font-mono); font-size: 10px; font-weight: 500; background: var(--bg-tertiary); color: var(--text-muted); border: 1px solid var(--border-dim); text-transform: uppercase; }

	.risk-area { display: flex; flex-direction: column; align-items: center; gap: var(--space-sm); }
	.risk-gauge { width: 120px; height: 70px; }
	.risk-badge { font-size: var(--text-xs); font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; padding: 3px 12px; border-radius: var(--radius-sm); }

	/* Pills + Auto */
	.pills { display: flex; gap: 2px; background: var(--bg-tertiary); border-radius: var(--radius-md); padding: 2px; border: 1px solid var(--border-dim); }
	.pill { padding: 5px 12px; border: none; background: transparent; color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--text-xs); font-weight: 500; border-radius: 5px; cursor: pointer; transition: all var(--transition-fast); }
	.pill:hover { color: var(--text-primary); background: var(--bg-elevated); }
	.pill.active { background: var(--cyan); color: var(--bg-void); font-weight: 600; }
	.auto-btn { display: flex; align-items: center; gap: 6px; padding: 5px 10px; background: var(--bg-tertiary); border: 1px solid var(--border-dim); border-radius: var(--radius-md); color: var(--text-muted); font-size: var(--text-xs); font-family: var(--font-sans); cursor: pointer; transition: all var(--transition-fast); }
	.auto-btn.active { border-color: var(--cyan); color: var(--cyan); background: rgba(0,212,255,0.06); }
	.auto-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--text-dim); transition: all var(--transition-fast); }
	.auto-btn.active .auto-dot { background: var(--cyan); box-shadow: 0 0 6px rgba(0,212,255,0.5); }

	/* ---------------------------------------------------------------- Stat Cards */
	.stats-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: var(--space-md); }
	.stat-card { background: var(--bg-secondary); border: 1px solid var(--border-dim); border-radius: var(--radius-md); padding: var(--space-md); position: relative; overflow: hidden; }
	.stat-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: var(--border-dim); }
	.stat-accent::before { background: var(--cyan); box-shadow: 0 0 10px rgba(0,212,255,0.3); }
	.stat-label { font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 500; margin-bottom: 6px; }
	.stat-value { font-family: var(--font-mono); font-size: var(--text-xl); font-weight: 600; color: var(--text-primary); letter-spacing: -0.02em; line-height: 1; }
	.stat-value.accent { color: var(--cyan); }
	.stat-sub { font-size: 10px; color: var(--text-muted); margin-top: 6px; font-family: var(--font-mono); }
	.split-bar { display: flex; height: 4px; border-radius: 2px; overflow: hidden; gap: 1px; margin-top: 8px; }
	.split-dl { background: var(--cyan); border-radius: 2px 0 0 2px; }
	.split-ul { background: var(--purple); border-radius: 0 2px 2px 0; }
	.split-legend { display: flex; gap: var(--space-sm); margin-top: 4px; font-size: 10px; }
	.legend-item { display: flex; align-items: center; gap: 4px; color: var(--text-dim); }
	.legend-dot { width: 6px; height: 6px; border-radius: 50%; }
	.ratio-bar { height: 6px; border-radius: 3px; background: var(--bg-tertiary); margin-top: 8px; overflow: hidden; }
	.ratio-fill { height: 100%; border-radius: 3px; transition: width var(--transition-slow); }

	/* ---------------------------------------------------------------- Chart */
	.section-card { background: var(--bg-secondary); border: 1px solid var(--border-dim); border-radius: var(--radius-md); overflow: hidden; }
	.section-header { display: flex; align-items: center; justify-content: space-between; padding: var(--space-md) var(--space-lg); border-bottom: 1px solid var(--border-dim); }
	.section-title { font-size: var(--text-sm); font-weight: 600; }
	.chart-body { padding: var(--space-sm) var(--space-md); }

	/* ---------------------------------------------------------------- Grid layouts */
	.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-md); }
	.three-col { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: var(--space-md); }

	/* ---------------------------------------------------------------- Card */
	.card { background: var(--bg-secondary); border: 1px solid var(--border-dim); border-radius: var(--radius-md); overflow: hidden; }
	.card-header { display: flex; align-items: center; justify-content: space-between; padding: var(--space-md) var(--space-lg); border-bottom: 1px solid var(--border-dim); }
	.card-title { font-size: var(--text-sm); font-weight: 600; }
	.card-badge { font-family: var(--font-mono); font-size: var(--text-xs); color: var(--text-muted); background: var(--bg-tertiary); padding: 2px 8px; border-radius: var(--radius-sm); }
	.card-link { display: block; padding: var(--space-sm) var(--space-lg); border-top: 1px solid var(--border-dim); font-size: var(--text-xs); color: var(--text-link); text-decoration: none; transition: background var(--transition-fast); }
	.card-link:hover { background: var(--bg-tertiary); }

	/* ---------------------------------------------------------------- Services */
	.service-list { padding: var(--space-xs) 0; }
	.svc-row { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: var(--space-md); padding: var(--space-sm) var(--space-lg); border-bottom: 1px solid var(--border-dim); transition: background var(--transition-fast); }
	.svc-row:last-child { border-bottom: none; }
	.svc-row:hover { background: var(--bg-tertiary); }
	.svc-name { font-size: var(--text-sm); }
	.svc-bytes { font-size: var(--text-xs); color: var(--text-secondary); }
	.svc-conns { font-size: 10px; color: var(--text-dim); }

	/* ---------------------------------------------------------------- Risk factors */
	.risk-factor-list { padding: var(--space-md) var(--space-lg); }
	.risk-factor { display: grid; grid-template-columns: 140px 1fr auto; align-items: center; gap: var(--space-md); padding: var(--space-sm) 0; }
	.risk-factor + .risk-factor { border-top: 1px solid var(--border-dim); }
	.rf-name { font-size: var(--text-sm); color: var(--text-secondary); }
	.rf-bar { height: 8px; background: var(--bg-tertiary); border-radius: 4px; overflow: hidden; }
	.rf-fill { height: 100%; border-radius: 4px; transition: width var(--transition-slow); }
	.rf-score { font-size: var(--text-xs); font-weight: 600; min-width: 50px; text-align: right; }

	/* ---------------------------------------------------------------- Alerts */
	.alert-list { padding: var(--space-xs) 0; }
	.alert-row { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: var(--space-md); padding: var(--space-sm) var(--space-lg); border-bottom: 1px solid var(--border-dim); transition: background var(--transition-fast); }
	.alert-row:last-child { border-bottom: none; }
	.alert-row:hover { background: var(--bg-tertiary); }
	.alert-sev { padding: 2px 8px; border-radius: var(--radius-sm); font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; white-space: nowrap; }
	.sev-high { background: rgba(255,71,87,0.12); color: var(--red); }
	.sev-med { background: rgba(255,171,0,0.12); color: var(--amber); }
	.sev-low { background: rgba(0,212,255,0.08); color: var(--cyan); }
	.alert-info { min-width: 0; }
	.alert-sig { font-size: var(--text-sm); color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.alert-cat { font-size: var(--text-xs); color: var(--text-muted); }
	.alert-time { font-size: 10px; color: var(--text-dim); white-space: nowrap; }

	/* ---------------------------------------------------------------- Tables */
	.table-wrap { overflow-x: auto; }
	.data-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
	.data-table th { padding: var(--space-sm) var(--space-md); text-align: left; font-size: 10px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; background: var(--bg-tertiary); border-bottom: 1px solid var(--border-dim); white-space: nowrap; }
	.data-table td { padding: var(--space-sm) var(--space-md); border-bottom: 1px solid var(--border-dim); vertical-align: middle; }
	.data-table tbody tr { transition: background var(--transition-fast); }
	.data-table tbody tr:hover { background: var(--bg-tertiary); }
	.data-table tbody tr:last-child td { border-bottom: none; }
	.td-sm { font-size: var(--text-xs); }
	.port-suspicious { color: var(--red); font-weight: 600; }
	.dl-col { color: var(--cyan); }
	.ul-col { color: var(--purple); }

	/* ---------------------------------------------------------------- Connections */
	.conn-toolbar { display: flex; align-items: center; gap: var(--space-md); padding: var(--space-sm) var(--space-lg); border-bottom: 1px solid var(--border-dim); }
	.proto-pills { display: flex; gap: 2px; }
	.proto-pill { padding: 4px 10px; border: 1px solid var(--border-dim); background: transparent; color: var(--text-muted); font-size: 10px; font-family: var(--font-mono); font-weight: 500; border-radius: var(--radius-sm); cursor: pointer; text-transform: uppercase; transition: all var(--transition-fast); }
	.proto-pill:hover { color: var(--text-secondary); border-color: var(--border-default); }
	.proto-pill.active { background: var(--cyan); color: var(--bg-void); border-color: var(--cyan); }
	.conn-row { cursor: pointer; }
	.conn-row:hover { background: var(--bg-elevated) !important; }
	.conn-row.selected { background: rgba(0,212,255,0.06) !important; }
	.pagination { display: flex; align-items: center; justify-content: center; gap: var(--space-md); padding: var(--space-md); border-top: 1px solid var(--border-dim); }
	.page-btn { padding: 4px 12px; background: var(--bg-tertiary); border: 1px solid var(--border-dim); border-radius: var(--radius-sm); color: var(--text-secondary); font-size: var(--text-xs); cursor: pointer; transition: all var(--transition-fast); }
	.page-btn:hover:not(:disabled) { border-color: var(--border-default); color: var(--text-primary); }
	.page-btn:disabled { opacity: 0.3; cursor: default; }
	.page-info { font-size: var(--text-xs); color: var(--text-muted); }
	.quick-links { display: flex; gap: var(--space-md); padding: var(--space-md) var(--space-lg); border-top: 1px solid var(--border-dim); }
	.quick-link { font-size: var(--text-xs); color: var(--text-link); text-decoration: none; transition: opacity var(--transition-fast); }
	.quick-link:hover { opacity: 0.8; text-decoration: underline; }

	/* ---------------------------------------------------------------- Responsive */
	@media (max-width: 1200px) { .three-col { grid-template-columns: 1fr; } .two-col { grid-template-columns: 1fr; } }
	@media (max-width: 1024px) { .stats-grid { grid-template-columns: repeat(3, 1fr); } }
	@media (max-width: 768px) { .stats-grid { grid-template-columns: repeat(2, 1fr); } .header-main { grid-template-columns: 1fr; } }
</style>
