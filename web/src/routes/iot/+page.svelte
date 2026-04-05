<script lang="ts">
	/**
	 * IoT Trust Score Dashboard — /iot
	 *
	 * Complete smart home health dashboard:
	 *   1. Hero Score Card (SVG gauge arc, sub-scores)
	 *   2. Stat Cards Row (4 key metrics)
	 *   3. Time Range Pills
	 *   4. Device Trust Grid (4-col responsive cards)
	 *   5. Manufacturer Profiles Card
	 *   6. Findings Feed Card
	 *   7. Network Isolation Card
	 *   8. Device Detail Drawer (5 tabs)
	 */

	import DetailDrawer from '$lib/components/DetailDrawer.svelte';
	import DrawerSection from '$lib/components/drawer/DrawerSection.svelte';
	import KVRow from '$lib/components/drawer/KVRow.svelte';
	import HorizontalBarList from '$lib/components/HorizontalBarList.svelte';
	import DonutChart from '$lib/components/charts/DonutChart.svelte';
	import TimeSeriesChart from '$lib/components/charts/TimeSeriesChart.svelte';
	import type { DrawerTab } from '$lib/components/DetailDrawer.svelte';
	import type { BarItem } from '$lib/components/HorizontalBarList.svelte';
	import type { Segment } from '$lib/components/charts/DonutChart.svelte';

	import {
		getFleetSummary,
		getPrivacyReport,
		getCommunicationMap,
		getActivityTimeline,
		getProtocolAudit,
		getNetworkIsolation,
		getManufacturerProfiles,
	} from '$lib/api/iot';
	import type {
		FleetSummary, FleetDevice, PrivacyReport, PrivacyDevice,
		CommunicationMap, Destination, ActivityTimeline,
		ProtocolAudit, ProtocolDevice, ProtocolFinding,
		NetworkIsolation, IsolationPair,
		ManufacturerProfilesResponse, ManufacturerProfile,
	} from '$lib/api/iot';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let fleet = $state<FleetSummary | null>(null);
	let privacy = $state<PrivacyReport | null>(null);
	let protocol = $state<ProtocolAudit | null>(null);
	let isolation = $state<NetworkIsolation | null>(null);
	let manufacturers = $state<ManufacturerProfilesResponse | null>(null);

	let loading = $state(true);
	let selectedRange = $state('24h');

	// Detail drawer state
	let drawerOpen = $state(false);
	let selectedDevice = $state<FleetDevice | null>(null);
	let activeTab = $state('overview');
	let commMapData = $state<CommunicationMap | null>(null);
	let timelineData = $state<ActivityTimeline | null>(null);
	let drawerLoading = $state(false);

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	const TIME_RANGES = [
		{ label: '1h', value: '1h' },
		{ label: '6h', value: '6h' },
		{ label: '24h', value: '24h' },
		{ label: '7d', value: '7d' },
	];

	const DRAWER_TABS: DrawerTab[] = [
		{ id: 'overview', label: 'Overview' },
		{ id: 'communication', label: 'Comm Map' },
		{ id: 'privacy', label: 'Privacy' },
		{ id: 'protocol', label: 'Protocol' },
		{ id: 'timeline', label: 'Timeline' },
	];

	// ---------------------------------------------------------------------------
	// Time helpers
	// ---------------------------------------------------------------------------

	function computeTimeParams(range: string): { from: string; to: string } {
		const now = new Date();
		let ms = 24 * 60 * 60 * 1000;
		switch (range) {
			case '1h': ms = 60 * 60 * 1000; break;
			case '6h': ms = 6 * 60 * 60 * 1000; break;
			case '24h': ms = 24 * 60 * 60 * 1000; break;
			case '7d': ms = 7 * 24 * 60 * 60 * 1000; break;
		}
		return { from: new Date(now.getTime() - ms).toISOString(), to: now.toISOString() };
	}

	// ---------------------------------------------------------------------------
	// Fetching
	// ---------------------------------------------------------------------------

	async function fetchAll(range: string) {
		loading = true;
		const params = computeTimeParams(range);
		try {
			const [fleetRes, privacyRes, protocolRes, isolationRes, mfgRes] = await Promise.all([
				getFleetSummary(params),
				getPrivacyReport(params),
				getProtocolAudit(params),
				getNetworkIsolation(params),
				getManufacturerProfiles(params),
			]);
			fleet = fleetRes;
			privacy = privacyRes;
			protocol = protocolRes;
			isolation = isolationRes;
			manufacturers = mfgRes;
		} catch {
			fleet = null;
			privacy = null;
			protocol = null;
			isolation = null;
			manufacturers = null;
		} finally {
			loading = false;
		}
	}

	$effect(() => { fetchAll(selectedRange); });

	async function selectDevice(device: FleetDevice) {
		selectedDevice = device;
		drawerOpen = true;
		activeTab = 'overview';
		drawerLoading = true;
		const params = computeTimeParams(selectedRange);
		try {
			const [commMap, timeline] = await Promise.all([
				getCommunicationMap(device.mac, params),
				getActivityTimeline(device.mac, params),
			]);
			commMapData = commMap;
			timelineData = timeline;
		} catch {
			commMapData = null;
			timelineData = null;
		} finally {
			drawerLoading = false;
		}
	}

	function closeDrawer() {
		drawerOpen = false;
		selectedDevice = null;
		commMapData = null;
		timelineData = null;
	}

	// ---------------------------------------------------------------------------
	// Derived — Hero gauge
	// ---------------------------------------------------------------------------

	let healthScore = $derived(fleet?.health_score ?? 0);
	let healthGrade = $derived(fleet?.health_grade ?? 'F');

	function gradeColor(grade: string): string {
		switch (grade) {
			case 'A': return 'var(--green)';
			case 'B': return 'var(--cyan)';
			case 'C': return 'var(--amber)';
			case 'D': return 'var(--orange)';
			default: return 'var(--red)';
		}
	}

	let gaugeColor = $derived(gradeColor(healthGrade));

	let gaugeArcPath = $derived.by(() => {
		const pct = Math.min(healthScore / 100, 1);
		const angle = pct * 180;
		const rad = (angle * Math.PI) / 180;
		const endX = 90 - 75 * Math.cos(rad);
		const endY = 90 - 75 * Math.sin(rad);
		const largeArc = angle > 180 ? 1 : 0;
		return `M 15 90 A 75 75 0 ${largeArc} 1 ${endX} ${endY}`;
	});

	let heroSubtitle = $derived(fleet?.subtitle || 'Scanning your smart home...');

	// Sorted devices — worst trust score first
	let sortedDevices = $derived.by(() => {
		if (!fleet?.devices) return [];
		return [...fleet.devices].sort((a, b) => a.score - b.score);
	});

	// ---------------------------------------------------------------------------
	// Derived — Findings feed
	// ---------------------------------------------------------------------------

	interface Finding {
		id: string;
		severity: string;
		description: string;
		deviceName: string;
		deviceMac: string;
		category: 'Privacy' | 'Security' | 'Behavior';
		timestamp: string;
	}

	let findings = $derived.by((): Finding[] => {
		const items: Finding[] = [];
		let idx = 0;

		// Protocol audit findings
		if (protocol?.devices) {
			for (const dev of protocol.devices) {
				for (const f of dev.findings) {
					items.push({
						id: `proto-${idx++}`,
						severity: f.severity,
						description: f.description,
						deviceName: dev.name,
						deviceMac: dev.mac,
						category: 'Security',
						timestamp: '',
					});
				}
			}
		}

		// Privacy findings from privacy report
		if (privacy?.devices) {
			for (const dev of privacy.devices) {
				if (dev.tracker_count > 0) {
					items.push({
						id: `privacy-${idx++}`,
						severity: dev.tracker_count > 5 ? 'high' : dev.tracker_count > 2 ? 'medium' : 'low',
						description: `${dev.name} contacted ${dev.tracker_count} tracker domain${dev.tracker_count !== 1 ? 's' : ''}`,
						deviceName: dev.name,
						deviceMac: dev.mac,
						category: 'Privacy',
						timestamp: '',
					});
				}
				if (dev.encryption_ratio < 0.9) {
					const pct = Math.round(dev.encryption_ratio * 100);
					items.push({
						id: `unenc-${idx++}`,
						severity: pct < 50 ? 'high' : 'medium',
						description: `${dev.name} has only ${pct}% encrypted connections`,
						deviceName: dev.name,
						deviceMac: dev.mac,
						category: 'Security',
						timestamp: '',
					});
				}
				if (dev.phone_home_per_hour > 60) {
					items.push({
						id: `phonehome-${idx++}`,
						severity: 'medium',
						description: `${dev.name} phones home ${Math.round(dev.phone_home_per_hour)}x/hour`,
						deviceName: dev.name,
						deviceMac: dev.mac,
						category: 'Behavior',
						timestamp: '',
					});
				}
			}
		}

		// Sort by severity (high first)
		const sevOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
		items.sort((a, b) => (sevOrder[a.severity] ?? 4) - (sevOrder[b.severity] ?? 4));
		return items;
	});

	// ---------------------------------------------------------------------------
	// Derived — Manufacturer bar items
	// ---------------------------------------------------------------------------

	let mfgBarItems = $derived.by((): BarItem[] => {
		if (!manufacturers?.manufacturers) return [];
		const mfgs = [...manufacturers.manufacturers].sort((a, b) => a.avg_trust_score - b.avg_trust_score);
		const max = Math.max(...mfgs.map(m => m.avg_trust_score), 1);
		return mfgs.map(m => ({
			key: m.name,
			label: m.name,
			value: m.avg_trust_score,
			formattedValue: `${Math.round(m.avg_trust_score)}`,
			color: gradeColor(m.avg_trust_grade),
			secondaryValue: `${m.device_count} device${m.device_count !== 1 ? 's' : ''}`,
		}));
	});

	// ---------------------------------------------------------------------------
	// Derived — Drawer device data
	// ---------------------------------------------------------------------------

	let selectedPrivacy = $derived.by((): PrivacyDevice | null => {
		if (!privacy?.devices || !selectedDevice) return null;
		return privacy.devices.find(d => d.mac === selectedDevice!.mac) ?? null;
	});

	let selectedProtocol = $derived.by((): ProtocolDevice | null => {
		if (!protocol?.devices || !selectedDevice) return null;
		return protocol.devices.find(d => d.mac === selectedDevice!.mac) ?? null;
	});

	// Comm map bar items
	let commBarItems = $derived.by((): BarItem[] => {
		if (!commMapData?.destinations) return [];
		const dests = [...commMapData.destinations].sort((a, b) => (b.bytes_sent + b.bytes_received) - (a.bytes_sent + a.bytes_received));
		return dests.slice(0, 20).map(d => ({
			key: d.ip,
			label: d.hostname || d.ip,
			value: d.bytes_sent + d.bytes_received,
			formattedValue: formatBytes(d.bytes_sent + d.bytes_received),
			color: d.in_baseline ? 'var(--green)' : 'var(--amber)',
			secondaryValue: d.country ?? '',
			mono: !d.hostname,
			isIp: !d.hostname,
			badgeText: d.in_baseline ? 'IN BASELINE' : 'NEW',
			badgeClass: d.in_baseline ? 'badge-success' : 'badge-warning',
		}));
	});

	// Privacy tracker bar items
	let trackerBarItems = $derived.by((): BarItem[] => {
		if (!selectedPrivacy?.tracker_domains) return [];
		return selectedPrivacy.tracker_domains.map(t => ({
			key: t.domain,
			label: t.domain,
			value: t.query_count,
			formattedValue: `${t.query_count}`,
			color: 'var(--red)',
			mono: true,
		}));
	});

	// Privacy donut segments
	let privacyDonutSegments = $derived.by((): Segment[] => {
		if (!selectedPrivacy) return [];
		const encrypted = Math.round(selectedPrivacy.encryption_ratio * 100);
		const unencrypted = 100 - encrypted;
		return [
			{ label: 'Encrypted', value: encrypted, color: 'var(--green)' },
			{ label: 'Unencrypted', value: unencrypted, color: 'var(--red)' },
		];
	});

	// Timeline chart data
	let timelineChartData = $derived.by(() => {
		if (!timelineData?.buckets) return [];
		return timelineData.buckets.map(b => ({
			time: b.time,
			value: b.connections,
		}));
	});

	// Isolation table sort
	let isoSortField = $state<string>('connection_count');
	let isoSortDir = $state<'asc' | 'desc'>('desc');

	function toggleIsoSort(field: string) {
		if (isoSortField === field) {
			isoSortDir = isoSortDir === 'desc' ? 'asc' : 'desc';
		} else {
			isoSortField = field;
			isoSortDir = 'desc';
		}
	}

	let sortedIsolationPairs = $derived.by(() => {
		if (!isolation?.pairs) return [];
		return [...isolation.pairs].sort((a, b) => {
			let av: string | number, bv: string | number;
			switch (isoSortField) {
				case 'iot_device':
					av = a.iot_device.name; bv = b.iot_device.name;
					break;
				case 'internal_target':
					av = a.internal_target.hostname ?? a.internal_target.ip;
					bv = b.internal_target.hostname ?? b.internal_target.ip;
					break;
				case 'risk':
					const riskOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
					av = riskOrder[a.risk] ?? 4; bv = riskOrder[b.risk] ?? 4;
					break;
				default:
					av = a.connection_count; bv = b.connection_count;
			}
			const cmp = av < bv ? -1 : av > bv ? 1 : 0;
			return isoSortDir === 'asc' ? cmp : -cmp;
		});
	});

	// Protocol audit table sort (for drawer)
	let protoSortField = $state<string>('severity');
	let protoSortDir = $state<'asc' | 'desc'>('desc');

	function toggleProtoSort(field: string) {
		if (protoSortField === field) {
			protoSortDir = protoSortDir === 'desc' ? 'asc' : 'desc';
		} else {
			protoSortField = field;
			protoSortDir = 'desc';
		}
	}

	let sortedProtocolFindings = $derived.by(() => {
		if (!selectedProtocol?.findings) return [];
		const sevOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
		return [...selectedProtocol.findings].sort((a, b) => {
			let av: string | number, bv: string | number;
			switch (protoSortField) {
				case 'type':
					av = a.type; bv = b.type; break;
				case 'port':
					av = a.port ?? 0; bv = b.port ?? 0; break;
				case 'protocol':
					av = a.protocol ?? ''; bv = b.protocol ?? ''; break;
				default:
					av = sevOrder[a.severity] ?? 5; bv = sevOrder[b.severity] ?? 5;
			}
			const cmp = av < bv ? -1 : av > bv ? 1 : 0;
			return protoSortDir === 'asc' ? cmp : -cmp;
		});
	});

	// ---------------------------------------------------------------------------
	// Formatters
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

	function timeAgo(dateStr: string | null): string {
		if (!dateStr) return '--';
		const diff = Date.now() - new Date(dateStr).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h ago`;
		return `${Math.floor(hours / 24)}d ago`;
	}

	function severityColor(severity: string): string {
		switch (severity) {
			case 'critical': return 'var(--red)';
			case 'high': return 'var(--red)';
			case 'medium': return 'var(--amber)';
			case 'low': return 'var(--green)';
			default: return 'var(--text-muted)';
		}
	}

	function severityBadgeClass(severity: string): string {
		switch (severity) {
			case 'critical': return 'badge-danger';
			case 'high': return 'badge-danger';
			case 'medium': return 'badge-warning';
			case 'low': return 'badge-success';
			default: return '';
		}
	}

	function categoryColor(cat: string): string {
		switch (cat) {
			case 'Privacy': return 'var(--purple)';
			case 'Security': return 'var(--red)';
			case 'Behavior': return 'var(--amber)';
			default: return 'var(--text-muted)';
		}
	}

	function scoreToGrade(score: number): string {
		if (score >= 90) return 'A';
		if (score >= 75) return 'B';
		if (score >= 60) return 'C';
		if (score >= 40) return 'D';
		return 'F';
	}
</script>

<svelte:head>
	<title>IoT Trust Score | NetTap</title>
</svelte:head>

<div class="iot-page">
	<!-- ================================================================
	     Page Header
	     ================================================================ -->
	<header class="page-header">
		<div class="header-left">
			<h1>IoT Trust Score</h1>
			<p class="subtitle">Smart home device health, privacy, and security</p>
		</div>
		<div class="header-right">
			<div class="pills">
				{#each TIME_RANGES as tr}
					<button class="pill" class:active={selectedRange === tr.value}
						onclick={() => (selectedRange = tr.value)}>
						{tr.label}
					</button>
				{/each}
			</div>
			<button class="btn btn-primary btn-sm" onclick={() => fetchAll(selectedRange)} disabled={loading}>
				{loading ? 'Loading...' : 'Refresh'}
			</button>
		</div>
	</header>

	{#if loading && !fleet}
		<div class="loading-state">
			<div class="loading-spinner"></div>
			<span class="text-muted">Scanning IoT devices...</span>
		</div>
	{:else if !fleet}
		<div class="empty-state">
			<p class="empty-text">Failed to load IoT data.</p>
			<p class="empty-hint">Check that the daemon is running and OpenSearch is accessible.</p>
		</div>
	{:else}
		<!-- ============================================================
		     1. Hero Score Card
		     ============================================================ -->
		<div class="hero-card card">
			<div class="hero-inner">
				<div class="hero-gauge-area">
					<div class="hero-gauge">
						<svg viewBox="0 0 180 100">
							<!-- Background arc -->
							<path d="M 15 90 A 75 75 0 0 1 165 90" fill="none" stroke="var(--bg-tertiary)" stroke-width="14" stroke-linecap="round" />
							<!-- Score arc -->
							<path d={gaugeArcPath} fill="none" stroke={gaugeColor} stroke-width="14" stroke-linecap="round" />
							<!-- Grade letter -->
							<text x="90" y="62" text-anchor="middle" fill={gaugeColor} font-family="var(--font-mono)" font-size="38" font-weight="700">{healthGrade}</text>
							<!-- Numeric score -->
							<text x="90" y="82" text-anchor="middle" fill="var(--text-secondary)" font-family="var(--font-mono)" font-size="14">{healthScore}/100</text>
							<!-- Label -->
							<text x="90" y="96" text-anchor="middle" fill="var(--text-muted)" font-size="8" font-weight="600" letter-spacing="0.12em">SMART HOME HEALTH</text>
						</svg>
					</div>

					<!-- Sub-score badges -->
					<div class="sub-scores">
						<div class="sub-score-badge">
							<span class="sub-dot" style="background: var(--purple);"></span>
							<span class="sub-label">Privacy</span>
							<span class="sub-value mono">{fleet.privacy_score}</span>
						</div>
						<div class="sub-score-badge">
							<span class="sub-dot" style="background: var(--cyan);"></span>
							<span class="sub-label">Security</span>
							<span class="sub-value mono">{fleet.security_score}</span>
						</div>
						<div class="sub-score-badge">
							<span class="sub-dot" style="background: var(--amber);"></span>
							<span class="sub-label">Behavior</span>
							<span class="sub-value mono">{fleet.behavior_score}</span>
						</div>
					</div>
				</div>

				<div class="hero-headline">
					<p class="hero-subtitle">{heroSubtitle}</p>
				</div>
			</div>
		</div>

		<!-- ============================================================
		     2. Stat Cards Row
		     ============================================================ -->
		<div class="stats-grid">
			<div class="stat-card">
				<span class="stat-label">IoT DEVICES</span>
				<span class="stat-value" style="color: var(--cyan);">{fleet.device_count}</span>
				<span class="stat-hint">classified devices</span>
			</div>
			<div class="stat-card">
				<span class="stat-label">ANOMALIES</span>
				<span class="stat-value" style="color: {fleet.anomaly_count === 0 ? 'var(--green)' : fleet.anomaly_count <= 3 ? 'var(--amber)' : 'var(--red)'};">{fleet.anomaly_count}</span>
				<span class="stat-hint">{fleet.anomaly_count === 0 ? 'all clear' : 'need review'}</span>
			</div>
			<div class="stat-card">
				<span class="stat-label">PRIVACY CONCERNS</span>
				<span class="stat-value" style="color: {fleet.privacy_concerns === 0 ? 'var(--green)' : fleet.privacy_concerns <= 2 ? 'var(--amber)' : 'var(--red)'};">{fleet.privacy_concerns}</span>
				<span class="stat-hint">{fleet.privacy_concerns === 0 ? 'no trackers' : 'tracker domains found'}</span>
			</div>
			<div class="stat-card">
				<span class="stat-label">UNENCRYPTED</span>
				<span class="stat-value" style="color: {fleet.unencrypted_count === 0 ? 'var(--green)' : 'var(--red)'};">{fleet.unencrypted_count}</span>
				<span class="stat-hint">{fleet.unencrypted_count === 0 ? 'fully encrypted' : 'devices using plaintext'}</span>
			</div>
		</div>

		<!-- ============================================================
		     4. Device Trust Grid
		     ============================================================ -->
		{#if sortedDevices.length > 0}
			<section class="card">
				<div class="card-header">
					<h2>Device Trust Scores</h2>
					<span class="card-badge">{sortedDevices.length} DEVICES</span>
				</div>
				<div class="trust-grid">
					{#each sortedDevices as device, i (device.mac)}
						<button
							class="trust-card"
							style="border-left-color: {gradeColor(device.grade)}; animation-delay: {i * 40}ms;"
							onclick={() => selectDevice(device)}
							type="button"
						>
							<div class="tc-header">
								<div class="tc-identity">
									<span class="tc-name">{device.name}</span>
									<span class="tc-mfg">{device.manufacturer}</span>
									{#if device.ip}
										<span class="tc-ip mono">{device.ip}</span>
									{/if}
								</div>
								<div class="tc-grade" style="color: {gradeColor(device.grade)}; background: color-mix(in srgb, {gradeColor(device.grade)} 12%, transparent);">
									{device.grade}
								</div>
							</div>

							<div class="tc-indicators">
								<div class="tc-indicator">
									<span class="tc-ind-label">Privacy</span>
									<span class="tc-ind-value" style="color: {gradeColor(scoreToGrade(device.privacy_score))};">{scoreToGrade(device.privacy_score)}</span>
								</div>
								<div class="tc-indicator">
									<span class="tc-ind-label">Encrypted</span>
									<span class="tc-ind-value mono">{device.encryption_pct}%</span>
								</div>
								<div class="tc-indicator">
									<span class="tc-ind-label">Anomalies</span>
									<span class="tc-ind-value mono" style="color: {device.anomaly_count === 0 ? 'var(--green)' : 'var(--amber)'};">{device.anomaly_count}</span>
								</div>
							</div>

							{#if device.last_seen}
								<span class="tc-lastseen">{timeAgo(device.last_seen)}</span>
							{/if}
						</button>
					{/each}
				</div>
			</section>
		{:else}
			<section class="card">
				<div class="card-header">
					<h2>Device Trust Scores</h2>
				</div>
				<div class="empty-state">
					<p class="empty-text">No IoT devices classified yet.</p>
					<p class="empty-hint">Devices are automatically classified based on manufacturer fingerprints (Ring, Nest, Wyze, etc.)</p>
				</div>
			</section>
		{/if}

		<!-- ============================================================
		     Two-column layout: Manufacturer Profiles + Findings Feed
		     ============================================================ -->
		<div class="two-col">
			<!-- 5. Manufacturer Profiles -->
			<section class="card">
				<div class="card-header">
					<h2>Manufacturer Profiles</h2>
					{#if manufacturers?.manufacturers?.length}
						<span class="card-badge">{manufacturers.manufacturers.length} VENDORS</span>
					{/if}
				</div>
				<div class="card-body">
					{#if mfgBarItems.length > 0}
						<HorizontalBarList
							items={mfgBarItems}
							showDot={true}
							labelWidth={130}
						/>
					{:else}
						<div class="empty-state-inline">
							<p class="text-muted">No manufacturer data available.</p>
						</div>
					{/if}
				</div>
			</section>

			<!-- 6. Findings Feed -->
			<section class="card">
				<div class="card-header">
					<h2>Findings Feed</h2>
					{#if findings.length > 0}
						<span class="card-badge" style="color: var(--amber);">{findings.length} FINDINGS</span>
					{/if}
				</div>
				<div class="findings-list">
					{#if findings.length > 0}
						{#each findings.slice(0, 20) as finding (finding.id)}
							<div class="finding-item">
								<span class="severity-dot" style="background: {severityColor(finding.severity)};"></span>
								<div class="finding-content">
									<p class="finding-desc">{finding.description}</p>
									<div class="finding-meta">
										<button class="finding-device" type="button"
											onclick={() => {
												const dev = fleet?.devices.find(d => d.mac === finding.deviceMac);
												if (dev) selectDevice(dev);
											}}>
											{finding.deviceName}
										</button>
										<span class="finding-tag" style="color: {categoryColor(finding.category)}; background: color-mix(in srgb, {categoryColor(finding.category)} 12%, transparent);">
											{finding.category}
										</span>
									</div>
								</div>
							</div>
						{/each}
						{#if findings.length > 20}
							<div class="finding-overflow">
								+{findings.length - 20} more findings
							</div>
						{/if}
					{:else}
						<div class="empty-state-inline">
							<p class="text-muted">No findings -- all devices look healthy.</p>
						</div>
					{/if}
				</div>
			</section>
		</div>

		<!-- ============================================================
		     7. Network Isolation Card
		     ============================================================ -->
		<section class="card">
			<div class="card-header">
				<h2>Network Isolation</h2>
				{#if isolation}
					<div class="iso-header-badges">
						<span class="iso-score mono">{isolation.segmentation_score}/100</span>
						<span class="iso-grade" style="color: {gradeColor(isolation.segmentation_grade)}; background: color-mix(in srgb, {gradeColor(isolation.segmentation_grade)} 12%, transparent);">
							{isolation.segmentation_grade}
						</span>
					</div>
				{/if}
			</div>
			{#if isolation && isolation.pairs.length > 0}
				<div class="table-wrap">
					<table class="data-table">
						<thead>
							<tr>
								<th class="sortable" class:sorted={isoSortField === 'iot_device'}
									onclick={() => toggleIsoSort('iot_device')}>
									IoT Device
									{#if isoSortField === 'iot_device'}
										<span class="sort-arrow">{isoSortDir === 'desc' ? '\u2193' : '\u2191'}</span>
									{/if}
								</th>
								<th class="sortable" class:sorted={isoSortField === 'internal_target'}
									onclick={() => toggleIsoSort('internal_target')}>
									Internal Target
									{#if isoSortField === 'internal_target'}
										<span class="sort-arrow">{isoSortDir === 'desc' ? '\u2193' : '\u2191'}</span>
									{/if}
								</th>
								<th class="sortable" class:sorted={isoSortField === 'risk'}
									onclick={() => toggleIsoSort('risk')}>
									Risk
									{#if isoSortField === 'risk'}
										<span class="sort-arrow">{isoSortDir === 'desc' ? '\u2193' : '\u2191'}</span>
									{/if}
								</th>
								<th class="sortable" class:sorted={isoSortField === 'connection_count'}
									onclick={() => toggleIsoSort('connection_count')}>
									Connections
									{#if isoSortField === 'connection_count'}
										<span class="sort-arrow">{isoSortDir === 'desc' ? '\u2193' : '\u2191'}</span>
									{/if}
								</th>
								<th>Ports</th>
								<th>Description</th>
							</tr>
						</thead>
						<tbody>
							{#each sortedIsolationPairs as pair (pair.iot_device.mac + '-' + pair.internal_target.ip)}
								<tr>
									<td>
										<div class="iso-device">
											<span class="iso-name">{pair.iot_device.name}</span>
											<span class="iso-ip mono">{pair.iot_device.ip}</span>
										</div>
									</td>
									<td class="mono">{pair.internal_target.hostname ?? pair.internal_target.ip}</td>
									<td>
										<span class="{severityBadgeClass(pair.risk)}" style="padding: var(--space-xs) var(--space-sm); border-radius: var(--radius-full); font-size: var(--text-xs); font-weight: 600; text-transform: uppercase;">
											{pair.risk}
										</span>
									</td>
									<td class="mono">{formatNumber(pair.connection_count)}</td>
									<td class="mono" style="font-size: var(--text-xs);">{pair.ports.join(', ')}</td>
									<td style="font-size: var(--text-sm); color: var(--text-secondary); max-width: 300px;">{pair.description}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				{#if isolation.recommendation}
					<div class="iso-recommendation">
						<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="var(--amber)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
							<circle cx="12" cy="12" r="10"></circle>
							<line x1="12" y1="8" x2="12" y2="12"></line>
							<line x1="12" y1="16" x2="12.01" y2="16"></line>
						</svg>
						<p>{isolation.recommendation}</p>
					</div>
				{/if}
			{:else}
				<div class="empty-state-inline" style="padding: var(--space-lg);">
					<p class="text-muted">No cross-segment IoT communication detected.</p>
				</div>
			{/if}
		</section>
	{/if}
</div>

<!-- ==================================================================
     8. Device Detail Drawer
     ================================================================== -->
<DetailDrawer
	open={drawerOpen}
	title={selectedDevice?.name ?? 'Device Details'}
	subtitle={selectedDevice?.mac ?? ''}
	tabs={DRAWER_TABS}
	{activeTab}
	onclose={closeDrawer}
	ontabchange={(tabId) => (activeTab = tabId)}
>
	{#snippet children()}
		{#if drawerLoading && activeTab !== 'overview'}
			<div class="loading-state" style="padding: var(--space-xl);">
				<div class="loading-spinner"></div>
				<span class="text-muted">Loading device data...</span>
			</div>
		{:else if selectedDevice}
			<!-- Tab 1: Overview -->
			{#if activeTab === 'overview'}
				<DrawerSection title="Trust Score Breakdown">
					<div class="drawer-progress-bars">
						<div class="drawer-progress-item">
							<div class="dp-header">
								<span class="dp-label">Privacy</span>
								<span class="dp-value mono" style="color: var(--purple);">{selectedDevice.privacy_score}</span>
							</div>
							<div class="dp-track">
								<div class="dp-fill" style="width: {selectedDevice.privacy_score}%; background: var(--purple);"></div>
							</div>
						</div>
						<div class="drawer-progress-item">
							<div class="dp-header">
								<span class="dp-label">Security</span>
								<span class="dp-value mono" style="color: var(--cyan);">{selectedDevice.security_score}</span>
							</div>
							<div class="dp-track">
								<div class="dp-fill" style="width: {selectedDevice.security_score}%; background: var(--cyan);"></div>
							</div>
						</div>
						<div class="drawer-progress-item">
							<div class="dp-header">
								<span class="dp-label">Behavior</span>
								<span class="dp-value mono" style="color: var(--amber);">{selectedDevice.behavior_score}</span>
							</div>
							<div class="dp-track">
								<div class="dp-fill" style="width: {selectedDevice.behavior_score}%; background: var(--amber);"></div>
							</div>
						</div>
					</div>
				</DrawerSection>

				<DrawerSection title="Device Info">
					<KVRow label="IP Address" value={selectedDevice.ip} mono copyable />
					<KVRow label="MAC Address" value={selectedDevice.mac} mono copyable />
					<KVRow label="Manufacturer" value={selectedDevice.manufacturer} />
					<KVRow label="Trust Grade" value={`${selectedDevice.grade} (${selectedDevice.score}/100)`} />
					<KVRow label="Last Seen" value={selectedDevice.last_seen ? timeAgo(selectedDevice.last_seen) : '--'} />
				</DrawerSection>

				<DrawerSection title="Quick Stats">
					<KVRow label="Encryption" value={`${selectedDevice.encryption_pct}%`} mono />
					<KVRow label="Trackers" value={String(selectedDevice.tracker_count)} mono />
					<KVRow label="Anomalies" value={String(selectedDevice.anomaly_count)} mono />
				</DrawerSection>

			<!-- Tab 2: Communication Map -->
			{:else if activeTab === 'communication'}
				<DrawerSection title="Top Destinations">
					{#if commBarItems.length > 0}
						<HorizontalBarList
							items={commBarItems}
							showRank={true}
							labelWidth={160}
						/>
					{:else}
						<p class="text-muted" style="font-size: var(--text-sm);">No communication data for this device.</p>
					{/if}
				</DrawerSection>

			<!-- Tab 3: Privacy -->
			{:else if activeTab === 'privacy'}
				{#if selectedPrivacy}
					<DrawerSection title="Privacy Grade">
						<div class="drawer-grade-display">
							<span class="drawer-grade-letter" style="color: {gradeColor(selectedPrivacy.privacy_grade)};">
								{selectedPrivacy.privacy_grade}
							</span>
							<span class="drawer-grade-score mono">{selectedPrivacy.privacy_score}/100</span>
						</div>
					</DrawerSection>

					{#if trackerBarItems.length > 0}
						<DrawerSection title="Tracker Domains ({selectedPrivacy.tracker_count})">
							<HorizontalBarList
								items={trackerBarItems}
								showRank={true}
								labelWidth={180}
							/>
						</DrawerSection>
					{/if}

					<DrawerSection title="Encryption">
						<DonutChart
							segments={privacyDonutSegments}
							size={160}
							formatValue={(n) => `${n}%`}
						/>
					</DrawerSection>

					<DrawerSection title="Phone Home Frequency">
						<div class="phone-home-stat">
							<span class="ph-value mono">{Math.round(selectedPrivacy.phone_home_per_hour)}</span>
							<span class="ph-label">requests/hour</span>
						</div>
					</DrawerSection>
				{:else}
					<div class="empty-state-inline">
						<p class="text-muted">No privacy data available for this device.</p>
					</div>
				{/if}

			<!-- Tab 4: Protocol Audit -->
			{:else if activeTab === 'protocol'}
				{#if selectedProtocol && selectedProtocol.findings.length > 0}
					<DrawerSection title="Protocol Findings ({selectedProtocol.findings.length})">
						<div class="table-wrap" style="margin-top: var(--space-sm);">
							<table class="data-table">
								<thead>
									<tr>
										<th class="sortable" class:sorted={protoSortField === 'type'}
											onclick={() => toggleProtoSort('type')}>
											Type
											{#if protoSortField === 'type'}
												<span class="sort-arrow">{protoSortDir === 'desc' ? '\u2193' : '\u2191'}</span>
											{/if}
										</th>
										<th class="sortable" class:sorted={protoSortField === 'severity'}
											onclick={() => toggleProtoSort('severity')}>
											Severity
											{#if protoSortField === 'severity'}
												<span class="sort-arrow">{protoSortDir === 'desc' ? '\u2193' : '\u2191'}</span>
											{/if}
										</th>
										<th class="sortable" class:sorted={protoSortField === 'port'}
											onclick={() => toggleProtoSort('port')}>
											Port
											{#if protoSortField === 'port'}
												<span class="sort-arrow">{protoSortDir === 'desc' ? '\u2193' : '\u2191'}</span>
											{/if}
										</th>
										<th>Description</th>
									</tr>
								</thead>
								<tbody>
									{#each sortedProtocolFindings as f, i (`${f.type}-${f.port}-${i}`)}
										<tr>
											<td>
												<span class="proto-type-badge">
													{f.type.replace(/_/g, ' ')}
												</span>
											</td>
											<td>
												<span class="{severityBadgeClass(f.severity)}" style="padding: var(--space-xs) var(--space-sm); border-radius: var(--radius-full); font-size: var(--text-xs); font-weight: 600; text-transform: uppercase;">
													{f.severity}
												</span>
											</td>
											<td class="mono">{f.port ?? '--'}</td>
											<td style="font-size: var(--text-sm); color: var(--text-secondary);">{f.description}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</DrawerSection>
				{:else}
					<DrawerSection title="Protocol Audit">
						<div class="proto-compliant">
							<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="var(--green)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
								<polyline points="22 4 12 14.01 9 11.01"></polyline>
							</svg>
							<span>All protocols within expected parameters.</span>
						</div>
					</DrawerSection>
				{/if}

			<!-- Tab 5: Activity Timeline -->
			{:else if activeTab === 'timeline'}
				<DrawerSection title="Connections Over Time">
					{#if timelineChartData.length > 0}
						<TimeSeriesChart
							data={timelineChartData}
							height={200}
							color="var(--cyan)"
							label="Connections"
							formatValue={(n) => formatNumber(Math.round(n))}
						/>
					{:else}
						<p class="text-muted" style="font-size: var(--text-sm);">No activity data available.</p>
					{/if}
				</DrawerSection>
			{/if}
		{/if}
	{/snippet}
</DetailDrawer>

<style>
	/* ----------------------------------------------------------------
	   Page Layout
	   ---------------------------------------------------------------- */
	.iot-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.page-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	h1 {
		font-size: var(--text-2xl);
		font-weight: 700;
		letter-spacing: -0.02em;
		margin-bottom: var(--space-xs);
	}

	.subtitle {
		color: var(--text-secondary);
		font-size: var(--text-sm);
	}

	.header-right {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		flex-wrap: wrap;
	}

	/* ----------------------------------------------------------------
	   Card overrides
	   ---------------------------------------------------------------- */
	.card-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-md) var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
	}

	.card-header h2 {
		font-size: var(--text-lg);
		font-weight: 600;
		color: var(--text-primary);
	}

	.card-badge {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		letter-spacing: 0.05em;
		text-transform: uppercase;
	}

	.card-body {
		padding: var(--space-md) var(--space-lg);
	}

	/* ----------------------------------------------------------------
	   1. Hero Score Card
	   ---------------------------------------------------------------- */
	.hero-card {
		padding: var(--space-lg);
	}

	.hero-inner {
		display: flex;
		align-items: center;
		gap: var(--space-xl);
		flex-wrap: wrap;
	}

	.hero-gauge-area {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-md);
		flex-shrink: 0;
	}

	.hero-gauge {
		width: 220px;
	}

	.hero-gauge svg {
		display: block;
		width: 100%;
	}

	.sub-scores {
		display: flex;
		gap: var(--space-md);
	}

	.sub-score-badge {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		padding: var(--space-xs) var(--space-sm);
		background: var(--bg-tertiary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-full);
		font-size: var(--text-xs);
	}

	.sub-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.sub-label {
		color: var(--text-secondary);
		font-weight: 500;
	}

	.sub-value {
		color: var(--text-primary);
		font-weight: 600;
	}

	.hero-headline {
		flex: 1;
		min-width: 200px;
	}

	.hero-subtitle {
		font-size: var(--text-lg);
		color: var(--text-secondary);
		line-height: 1.5;
	}

	/* ----------------------------------------------------------------
	   2. Stat Cards
	   ---------------------------------------------------------------- */
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--space-md);
	}

	.stat-hint {
		display: block;
		font-size: var(--text-xs);
		color: var(--text-dim);
		margin-top: 2px;
	}

	/* ----------------------------------------------------------------
	   4. Device Trust Grid
	   ---------------------------------------------------------------- */
	.trust-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--space-md);
		padding: var(--space-md) var(--space-lg);
	}

	.trust-card {
		background: var(--bg-tertiary);
		border: 1px solid var(--border-dim);
		border-left: 3px solid var(--text-dim);
		border-radius: var(--radius-md);
		padding: var(--space-md);
		cursor: pointer;
		text-align: left;
		transition: transform var(--transition-fast), box-shadow var(--transition-fast), border-color var(--transition-fast);
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		animation: trustCardIn 400ms ease both;
		color: var(--text-primary);
	}

	@keyframes trustCardIn {
		from {
			opacity: 0;
			transform: translateY(8px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	.trust-card:hover {
		transform: translateY(-2px);
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
		border-color: var(--border-bright);
	}

	.tc-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--space-sm);
	}

	.tc-identity {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
		flex: 1;
	}

	.tc-name {
		font-weight: 600;
		font-size: var(--text-sm);
		color: var(--text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.tc-mfg {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.tc-ip {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.tc-grade {
		font-family: var(--font-mono);
		font-size: var(--text-lg);
		font-weight: 700;
		width: 36px;
		height: 36px;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: var(--radius-sm);
		flex-shrink: 0;
	}

	.tc-indicators {
		display: flex;
		gap: var(--space-sm);
		border-top: 1px solid var(--border-dim);
		padding-top: var(--space-sm);
	}

	.tc-indicator {
		display: flex;
		flex-direction: column;
		gap: 2px;
		flex: 1;
	}

	.tc-ind-label {
		font-size: 10px;
		color: var(--text-dim);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.tc-ind-value {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
	}

	.tc-lastseen {
		font-size: 10px;
		color: var(--text-dim);
		text-align: right;
	}

	/* ----------------------------------------------------------------
	   Two-column layout
	   ---------------------------------------------------------------- */
	.two-col {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-md);
	}

	/* ----------------------------------------------------------------
	   6. Findings Feed
	   ---------------------------------------------------------------- */
	.findings-list {
		display: flex;
		flex-direction: column;
	}

	.finding-item {
		display: flex;
		gap: var(--space-md);
		padding: var(--space-sm) var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
	}

	.finding-item:last-child {
		border-bottom: none;
	}

	.severity-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		margin-top: 6px;
		flex-shrink: 0;
	}

	.finding-content {
		flex: 1;
		min-width: 0;
	}

	.finding-desc {
		font-size: var(--text-sm);
		color: var(--text-primary);
		line-height: 1.4;
		margin-bottom: var(--space-xs);
	}

	.finding-meta {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.finding-device {
		font-size: var(--text-xs);
		color: var(--text-link);
		background: none;
		border: none;
		cursor: pointer;
		padding: 0;
		text-decoration: none;
		font-weight: 500;
	}

	.finding-device:hover {
		text-decoration: underline;
	}

	.finding-tag {
		font-size: 10px;
		font-weight: 600;
		padding: 2px var(--space-sm);
		border-radius: var(--radius-full);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.finding-overflow {
		padding: var(--space-sm) var(--space-lg);
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-align: center;
	}

	/* ----------------------------------------------------------------
	   7. Network Isolation
	   ---------------------------------------------------------------- */
	.iso-header-badges {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.iso-score {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	.iso-grade {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		font-weight: 700;
		padding: var(--space-xs) var(--space-sm);
		border-radius: var(--radius-sm);
	}

	.iso-device {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.iso-name {
		font-weight: 500;
		font-size: var(--text-sm);
		color: var(--text-primary);
	}

	.iso-ip {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.iso-recommendation {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		padding: var(--space-md) var(--space-lg);
		border-top: 1px solid var(--border-dim);
		background: color-mix(in srgb, var(--amber) 5%, transparent);
	}

	.iso-recommendation p {
		font-size: var(--text-sm);
		color: var(--text-secondary);
		line-height: 1.5;
	}

	/* ----------------------------------------------------------------
	   Table overrides
	   ---------------------------------------------------------------- */
	.table-wrap {
		overflow-x: auto;
	}

	.data-table th.sortable {
		cursor: pointer;
		user-select: none;
	}

	.data-table th.sortable:hover {
		color: var(--text-primary);
	}

	.data-table th.sorted {
		color: var(--accent);
	}

	.sort-arrow {
		color: var(--accent);
		margin-left: 2px;
	}

	/* ----------------------------------------------------------------
	   Drawer tab content
	   ---------------------------------------------------------------- */
	.drawer-progress-bars {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.drawer-progress-item {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.dp-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.dp-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.dp-value {
		font-size: var(--text-sm);
		font-weight: 600;
	}

	.dp-track {
		height: 6px;
		background: var(--bg-tertiary);
		border-radius: var(--radius-full);
		overflow: hidden;
	}

	.dp-fill {
		height: 100%;
		border-radius: var(--radius-full);
		transition: width var(--transition-normal);
	}

	/* Privacy grade display */
	.drawer-grade-display {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		padding: var(--space-sm) 0;
	}

	.drawer-grade-letter {
		font-family: var(--font-mono);
		font-size: var(--text-4xl);
		font-weight: 700;
	}

	.drawer-grade-score {
		font-size: var(--text-lg);
		color: var(--text-secondary);
	}

	/* Phone home stat */
	.phone-home-stat {
		display: flex;
		align-items: baseline;
		gap: var(--space-sm);
		padding: var(--space-sm) 0;
	}

	.ph-value {
		font-size: var(--text-3xl);
		font-weight: 700;
		color: var(--text-primary);
	}

	.ph-label {
		font-size: var(--text-sm);
		color: var(--text-muted);
	}

	/* Protocol type badge */
	.proto-type-badge {
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--text-secondary);
		text-transform: capitalize;
	}

	/* Protocol compliant state */
	.proto-compliant {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-sm) 0;
		font-size: var(--text-sm);
		color: var(--green);
	}

	/* ----------------------------------------------------------------
	   Empty / Loading states
	   ---------------------------------------------------------------- */
	.empty-state-inline {
		padding: var(--space-lg);
		text-align: center;
	}

	.loading-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: var(--space-3xl);
		gap: var(--space-md);
	}

	.empty-state {
		padding: var(--space-xl);
		text-align: center;
	}

	.empty-text {
		color: var(--text-secondary);
		font-size: var(--text-sm);
		margin-bottom: var(--space-xs);
	}

	.empty-hint {
		color: var(--text-dim);
		font-size: var(--text-xs);
	}

	/* ----------------------------------------------------------------
	   Responsive
	   ---------------------------------------------------------------- */
	@media (max-width: 1280px) {
		.trust-grid {
			grid-template-columns: repeat(3, 1fr);
		}
	}

	@media (max-width: 1024px) {
		.stats-grid {
			grid-template-columns: repeat(2, 1fr);
		}

		.trust-grid {
			grid-template-columns: repeat(2, 1fr);
		}

		.two-col {
			grid-template-columns: 1fr;
		}
	}

	@media (max-width: 768px) {
		.page-header {
			flex-direction: column;
		}

		.stats-grid {
			grid-template-columns: 1fr;
		}

		.trust-grid {
			grid-template-columns: 1fr;
		}

		.hero-inner {
			flex-direction: column;
			text-align: center;
		}

		.sub-scores {
			flex-wrap: wrap;
			justify-content: center;
		}
	}
</style>
