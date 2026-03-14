<script lang="ts">
	/**
	 * Threat Intelligence Page — /threats
	 *
	 * Behavioral threat analysis dashboard:
	 *   1. Threat Brief header (score, baseline, categories)
	 *   2. Active Kill Chains
	 *   3. Beaconing Detection + DNS Anomalies
	 *   4. Lateral Movement + Threat Intel Matches
	 *   5. Auto-Investigations
	 */

	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { getThreatReport, getThreatIntel } from '$api/threats';
	import type {
		ThreatReport,
		KillChain,
		BeaconSuspect,
		LateralMovement,
		DnsAnomalies,
		Investigation,
		ThreatIntelInfo,
	} from '$api/threats';
	import IPAddress from '$components/IPAddress.svelte';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let loading = $state(true);
	let report = $state<ThreatReport | null>(null);
	let threatIntel = $state<ThreatIntelInfo | null>(null);
	let selectedRange = $state('24h');
	let lastUpdated = $state(new Date());
	let expandedInvestigation = $state<number | null>(0);

	// Derived
	let summary = $derived(report?.summary);
	let killChains = $derived(report?.kill_chains ?? []);
	let beacons = $derived(report?.beaconing ?? []);
	let dnsAnomalies = $derived(report?.dns_anomalies ?? { dga_suspects: [], tunnel_suspects: [], nxdomain_spikes: [], suspicious_tlds: [] });
	let lateralMoves = $derived(report?.lateral_movement ?? []);
	let investigations = $derived(report?.investigations ?? []);
	let baseline = $derived(summary?.baseline);

	let threatScore = $derived(summary?.threat_score ?? 0);
	let threatLevel = $derived(summary?.threat_level ?? 'none');

	let lastUpdatedText = $derived.by(() => {
		const diff = Math.floor((Date.now() - lastUpdated.getTime()) / 1000);
		if (diff < 5) return 'just now';
		if (diff < 60) return `${diff}s ago`;
		return `${Math.floor(diff / 60)}m ago`;
	});

	// Risk gauge arc
	let gaugeArcPath = $derived.by(() => {
		const pct = Math.min(threatScore / 100, 1);
		const angle = pct * 180;
		const rad = (angle * Math.PI) / 180;
		const endX = 90 - 75 * Math.cos(rad);
		const endY = 90 - 75 * Math.sin(rad);
		const largeArc = angle > 180 ? 1 : 0;
		return `M 15 90 A 75 75 0 ${largeArc} 1 ${endX} ${endY}`;
	});

	let threatColor = $derived(
		threatLevel === 'critical' ? 'var(--red)' :
		threatLevel === 'high' ? 'var(--red)' :
		threatLevel === 'medium' ? 'var(--amber)' :
		threatLevel === 'low' ? 'var(--green)' : 'var(--text-muted)'
	);

	// Category bar segments
	let categorySegments = $derived.by(() => {
		if (!summary?.categories) return [];
		const cats = Object.entries(summary.categories);
		const total = cats.reduce((s, [, v]) => s + v.events, 0) || 1;
		const colors: Record<string, string> = {
			malware_c2: 'var(--red)', exfiltration: 'var(--orange)',
			reconnaissance: 'var(--amber)', exploit: 'var(--purple)',
			policy: 'var(--blue)', protocol_anomaly: 'var(--teal)',
			informational: 'var(--text-dim)',
		};
		return cats
			.filter(([, v]) => v.events > 0)
			.map(([key, v]) => ({
				key,
				label: v.label,
				pct: Math.max(2, (v.events / total) * 100),
				color: colors[key] ?? 'var(--text-dim)',
				events: v.events,
				groups: v.groups,
			}))
			.sort((a, b) => b.pct - a.pct);
	});

	// Headline
	let headline = $derived.by(() => {
		const groups = summary?.total_groups ?? 0;
		const invCount = investigations.length;
		if (groups === 0) return 'No actionable threats detected.';
		return `Suricata generated ${formatNumber(summary?.total_events ?? 0)} alert events. NetTap found ${invCount} investigation${invCount !== 1 ? 's' : ''}.`;
	});

	let subheadline = $derived.by(() => {
		const parts: string[] = [];
		if (killChains.length > 0) parts.push(`${killChains.length} active kill chain${killChains.length > 1 ? 's' : ''}`);
		if (beacons.length > 0) parts.push(`${beacons.length} beaconing suspect${beacons.length > 1 ? 's' : ''}`);
		const tiTotal = threatIntel?.total_indicators ?? 0;
		if (tiTotal > 0) parts.push(`${tiTotal} threat intel indicators`);
		return parts.join(' \u00b7 ') || 'Scanning network activity...';
	});

	// ---------------------------------------------------------------------------
	// Time helpers
	// ---------------------------------------------------------------------------

	function computeTimeParams(range: string): { from: string; to: string } {
		const now = new Date();
		let from: Date;
		switch (range) {
			case '1h': from = new Date(now.getTime() - 60 * 60 * 1000); break;
			case '6h': from = new Date(now.getTime() - 6 * 60 * 60 * 1000); break;
			case '7d': from = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000); break;
			case '30d': from = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000); break;
			default: from = new Date(now.getTime() - 24 * 60 * 60 * 1000); break;
		}
		return { from: from.toISOString(), to: now.toISOString() };
	}

	// ---------------------------------------------------------------------------
	// Fetching
	// ---------------------------------------------------------------------------

	async function fetchAll(range: string) {
		loading = true;
		const params = computeTimeParams(range);
		try {
			const [reportRes, tiRes] = await Promise.all([
				getThreatReport(params),
				getThreatIntel(params),
			]);
			report = reportRes;
			threatIntel = tiRes;
			lastUpdated = new Date();
		} catch {
			report = null;
			threatIntel = null;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		const range = selectedRange;
		fetchAll(range);
	});

	// ---------------------------------------------------------------------------
	// Formatters
	// ---------------------------------------------------------------------------

	function formatNumber(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
		return n.toLocaleString();
	}

	function formatBytes(bytes: number): string {
		if (bytes === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
	}

	const STAGE_NAMES: Record<number, string> = { 1: 'Reconnaissance', 2: 'Exploit', 3: 'Malware & C2', 4: 'Exfiltration' };
</script>

<svelte:head>
	<title>Threat Intelligence | NetTap</title>
</svelte:head>

<div class="threats-page">
	<!-- Page Header -->
	<div class="page-header">
		<div>
			<h1>Threat Intelligence</h1>
			<p class="subtitle">Behavioral analysis &middot; Last scan {lastUpdatedText}</p>
		</div>
		<div class="header-controls">
			<div class="pills">
				{#each [{ l: '1h', v: '1h' }, { l: '6h', v: '6h' }, { l: '24h', v: '24h' }, { l: '7d', v: '7d' }, { l: '30d', v: '30d' }] as r}
					<button class="pill" class:active={selectedRange === r.v} onclick={() => (selectedRange = r.v)}>{r.l}</button>
				{/each}
			</div>
		</div>
	</div>

	{#if loading && !report}
		<div class="loading-state">
			<div class="loading-spinner"></div>
			<span class="text-muted">Analyzing network threats...</span>
		</div>
	{:else if !report}
		<div class="empty-state">
			<p>Failed to load threat intelligence data.</p>
		</div>
	{:else}
		<!-- ============================================================
		     Threat Brief — Hero Section
		     ============================================================ -->
		<div class="threat-brief">
			<div class="threat-score-area">
				<div class="threat-gauge">
					<svg viewBox="0 0 180 100">
						<path d="M 15 90 A 75 75 0 0 1 165 90" fill="none" stroke="var(--bg-tertiary)" stroke-width="14" stroke-linecap="round" />
						<path d={gaugeArcPath} fill="none" stroke={threatColor} stroke-width="14" stroke-linecap="round" />
						<text x="90" y="72" text-anchor="middle" fill={threatColor} font-family="var(--font-mono)" font-size="42" font-weight="700">{threatScore}</text>
						<text x="90" y="90" text-anchor="middle" fill="var(--text-muted)" font-size="10" font-weight="600" letter-spacing="0.1em">THREAT SCORE</text>
					</svg>
				</div>
				<span class="threat-level-badge" style="color: {threatColor}; background: color-mix(in srgb, {threatColor} 12%, transparent); border-color: color-mix(in srgb, {threatColor} 30%, transparent);">{threatLevel.toUpperCase()}</span>
				{#if baseline}
					<div class="baseline-indicator mono">
						<span class="baseline-value" style="color: {baseline.deviation > 2 ? 'var(--red)' : baseline.deviation > 1.5 ? 'var(--amber)' : 'var(--text-muted)'};">{baseline.deviation}x</span> {baseline.is_anomalous ? 'above' : 'vs'} baseline
					</div>
				{/if}
			</div>
			<div class="threat-brief-right">
				<div>
					<div class="brief-headline">{headline}</div>
					<div class="brief-subheadline">{subheadline}</div>
				</div>
				<div class="brief-stats">
					<div class="brief-stat">
						<div class="brief-stat-label">Alert Groups</div>
						<div class="brief-stat-value">{formatNumber(summary?.total_groups ?? 0)}</div>
					</div>
					<div class="brief-stat">
						<div class="brief-stat-label">Kill Chains</div>
						<div class="brief-stat-value" class:danger={killChains.length > 0}>{killChains.length}</div>
					</div>
					<div class="brief-stat">
						<div class="brief-stat-label">Beaconing</div>
						<div class="brief-stat-value" class:warning={beacons.length > 0}>{beacons.length}</div>
					</div>
					<div class="brief-stat">
						<div class="brief-stat-label">TI Indicators</div>
						<div class="brief-stat-value" class:danger={(threatIntel?.total_indicators ?? 0) > 0}>{threatIntel?.total_indicators ?? 0}</div>
					</div>
				</div>
				{#if categorySegments.length > 0}
					<div class="category-bar">
						{#each categorySegments as seg (seg.key)}
							<div class="cat-segment" style="width: {seg.pct}%; background: {seg.color};" title="{seg.label}: {formatNumber(seg.events)} events"></div>
						{/each}
					</div>
					<div class="category-legend">
						{#each categorySegments.slice(0, 5) as seg (seg.key)}
							<span class="cat-legend-item"><span class="cat-dot" style="background:{seg.color};"></span>{seg.label} ({Math.round(seg.pct)}%)</span>
						{/each}
					</div>
				{/if}
			</div>
		</div>

		<!-- ============================================================
		     Active Kill Chains
		     ============================================================ -->
		{#if killChains.length > 0}
			<div class="card kill-chain-card">
				<div class="card-header">
					<span class="card-title">Active Kill Chains</span>
					<span class="card-badge danger">{killChains.length} detected</span>
				</div>
				{#each killChains as kc, i (`${kc.source_ip}-${i}`)}
					<div class="kill-chain-item">
						<div class="kc-header">
							<span class="kc-ip mono">{kc.source_ip}</span>
							<span class="kc-badge">{kc.stages.length}-Stage Chain</span>
						</div>
						<div class="kc-stages">
							{#each [1, 2, 3, 4] as stage, si}
								{#if si > 0}<span class="kc-arrow">&rarr;</span>{/if}
								<div class="kc-stage" class:active={kc.stages.includes(stage)}>
									<span class="kc-stage-num">STAGE {stage}</span>
									<span class="kc-stage-name">{STAGE_NAMES[stage]}</span>
									{#if kc.stages.includes(stage)}
										<span class="kc-stage-count">{kc.alert_count} alerts</span>
									{:else}
										<span class="kc-stage-count">&mdash;</span>
									{/if}
								</div>
							{/each}
						</div>
						<div class="kc-assessment">{kc.assessment}</div>
						<div class="kc-actions">
							<button class="btn-investigate" onclick={() => goto(`/devices/${encodeURIComponent(kc.source_ip)}`)}>Investigate Device</button>
							<button class="btn-secondary-sm" onclick={() => goto(`/connections?ip=${kc.source_ip}`)}>View Connections</button>
						</div>
					</div>
				{/each}
			</div>
		{/if}

		<!-- ============================================================
		     Beaconing + DNS Anomalies
		     ============================================================ -->
		<div class="two-col">
			<!-- Beaconing -->
			<div class="card">
				<div class="card-header">
					<span class="card-title">Beaconing Detection</span>
					<span class="card-badge" class:danger={beacons.length > 0}>{beacons.length} suspects</span>
				</div>
				{#if beacons.length > 0}
					{#each beacons as b, i (`${b.source_ip}-${b.destination_ip}-${i}`)}
						<div class="beacon-row">
							<div class="beacon-pair">
								<span class="beacon-src mono">{b.source_ip}</span>
								<span class="beacon-dst mono">&rarr; {b.destination_ip}:{b.destination_port}</span>
							</div>
							<span class="beacon-interval mono">~{b.interval_seconds}s</span>
							<span class="beacon-jitter mono">{(b.jitter_coefficient * 100).toFixed(1)}% jitter</span>
							<div class="confidence-meter">
								<div class="confidence-fill" style="width: {b.confidence}%; background: {b.confidence > 80 ? 'var(--red)' : b.confidence > 50 ? 'var(--amber)' : 'var(--green)'};"></div>
							</div>
							<span class="beacon-confidence mono" style="color: {b.confidence > 80 ? 'var(--red)' : b.confidence > 50 ? 'var(--amber)' : 'var(--green)'};">{b.confidence}%</span>
						</div>
					{/each}
				{:else}
					<p class="empty-msg">No beaconing patterns detected.</p>
				{/if}
			</div>

			<!-- DNS Anomalies -->
			<div class="card">
				<div class="card-header">
					<span class="card-title">DNS Anomalies</span>
					<span class="card-badge" class:danger={(dnsAnomalies.dga_suspects?.length ?? 0) + (dnsAnomalies.nxdomain_spikes?.length ?? 0) > 0}>
						{(dnsAnomalies.dga_suspects?.length ?? 0) + (dnsAnomalies.tunnel_suspects?.length ?? 0) + (dnsAnomalies.nxdomain_spikes?.length ?? 0)} findings
					</span>
				</div>
				{#if dnsAnomalies.dga_suspects?.length}
					<div class="anomaly-group-header">DGA Suspects <span class="anomaly-count-badge">{dnsAnomalies.dga_suspects.length}</span></div>
					{#each dnsAnomalies.dga_suspects.slice(0, 5) as d, i (`dga-${i}`)}
						<div class="dga-row">
							<span class="dga-domain mono">{d.domain}</span>
							<span class="dga-entropy mono">H={d.entropy}</span>
							<span class="dga-count mono">{formatNumber(d.query_count)} queries</span>
						</div>
					{/each}
				{/if}
				{#if dnsAnomalies.nxdomain_spikes?.length}
					<div class="anomaly-group-header">NXDOMAIN Spikes <span class="anomaly-count-badge">{dnsAnomalies.nxdomain_spikes.length}</span></div>
					{#each dnsAnomalies.nxdomain_spikes.slice(0, 5) as nx, i (`nx-${i}`)}
						<div class="nxdomain-row">
							<span class="nxdomain-ip mono">{nx.source_ip}</span>
							<div class="nxdomain-bar-track"><div class="nxdomain-bar-fill" style="width: {nx.nxdomain_ratio * 100}%;"></div></div>
							<span class="nxdomain-pct mono">{Math.round(nx.nxdomain_ratio * 100)}%</span>
							<span class="nxdomain-count mono">{formatNumber(nx.nxdomain_count)} / {formatNumber(nx.total_queries)}</span>
						</div>
					{/each}
				{/if}
				{#if !dnsAnomalies.dga_suspects?.length && !dnsAnomalies.nxdomain_spikes?.length}
					<p class="empty-msg">No DNS anomalies detected.</p>
				{/if}
			</div>
		</div>

		<!-- ============================================================
		     Lateral Movement + Threat Intel
		     ============================================================ -->
		<div class="two-col">
			<!-- Lateral Movement -->
			<div class="card">
				<div class="card-header">
					<span class="card-title">Lateral Movement</span>
					<span class="card-badge">{lateralMoves.length} internal paths</span>
				</div>
				{#if lateralMoves.length > 0}
					{#each lateralMoves.slice(0, 8) as lm, i (`${lm.source_ip}-${lm.destination_ip}-${i}`)}
						<div class="lateral-row">
							{#if lm.fan_out}
								<span class="lateral-fanout">FAN-OUT: {lm.fan_out}</span>
							{:else}
								<span style="min-width:85px;"></span>
							{/if}
							<div class="lateral-path">
								<span class="lateral-src mono">{lm.source_ip}</span>
								<span class="lateral-arrow">&rarr;</span>
								<span class="lateral-dst mono">{lm.destination_ip}</span>
							</div>
							<span class="lateral-service">{lm.service}</span>
							<span class="lateral-port mono">:{lm.port}</span>
							<span class="lateral-count mono">{formatNumber(lm.connection_count)} conn</span>
						</div>
					{/each}
				{:else}
					<p class="empty-msg">No lateral movement detected.</p>
				{/if}
			</div>

			<!-- Threat Intel -->
			<div class="card">
				<div class="card-header">
					<span class="card-title">Threat Intel Matches</span>
					<span class="card-badge" class:danger={(threatIntel?.total_indicators ?? 0) > 0}>{threatIntel?.total_indicators ?? 0} indicators</span>
				</div>
				{#if threatIntel && Object.keys(threatIntel.feeds).length > 0}
					{#each Object.entries(threatIntel.feeds) as [feedId, feed], i (`${feedId}-${i}`)}
						<div class="ti-row">
							<span class="ti-badge">TI</span>
							<div>
								<div class="ti-feed-name">{feed.label}</div>
								<div class="ti-feed-count mono">{feed.indicator_count} indicators loaded</div>
							</div>
						</div>
					{/each}
				{:else}
					<p class="empty-msg">No threat intel indicators loaded. Feeds populate from Suricata detections.</p>
				{/if}
			</div>
		</div>

		<!-- ============================================================
		     Auto-Investigations
		     ============================================================ -->
		{#if investigations.length > 0}
			<div class="card">
				<div class="card-header">
					<span class="card-title">Auto-Investigations</span>
					<span class="card-badge">{investigations.length} completed</span>
				</div>
				<div class="inv-list">
					{#each investigations as inv, i (`inv-${i}`)}
						<div class="investigation-card">
							<button class="inv-header" type="button" onclick={() => (expandedInvestigation = expandedInvestigation === i ? null : i)}>
								<div class="inv-title-area">
									<span class="inv-sev" class:sev-critical={inv.alert.severity_label === 'CRITICAL'} class:sev-high={inv.alert.severity_label === 'HIGH'}>{inv.alert.severity_label}</span>
									<div>
										<div class="inv-title">{inv.alert.signature}</div>
										<div class="inv-subtitle mono">{inv.alert.source_ip} &rarr; {inv.alert.destination_ip}</div>
									</div>
								</div>
								<span class="inv-expand">{expandedInvestigation === i ? '\u25BC' : '\u25B6'}</span>
							</button>
							{#if expandedInvestigation === i}
								<div class="inv-body">
									{#if inv.sections.source_profile}
										<div>
											<div class="inv-section-title">Source Host Profile</div>
											<div class="inv-detail-grid">
												<div class="inv-field"><span class="inv-field-label">IP</span><span class="inv-field-value mono">{inv.sections.source_profile.ip}</span></div>
												<div class="inv-field"><span class="inv-field-label">Connections (24h)</span><span class="inv-field-value mono">{formatNumber(Number(inv.sections.source_profile.connection_count_24h) || 0)}</span></div>
												<div class="inv-field"><span class="inv-field-label">Unique Destinations</span><span class="inv-field-value mono">{Number(inv.sections.source_profile.unique_destinations) || 0}</span></div>
												<div class="inv-field"><span class="inv-field-label">Bytes (24h)</span><span class="inv-field-value mono">{formatBytes(Number(inv.sections.source_profile.total_bytes_24h) || 0)}</span></div>
											</div>
										</div>
									{/if}
									{#if inv.sections.connection_history}
										<div>
											<div class="inv-section-title">Connection History (7d)</div>
											<div class="inv-detail-grid">
												<div class="inv-field"><span class="inv-field-label">Total Connections</span><span class="inv-field-value mono">{formatNumber(Number(inv.sections.connection_history.total_connections_7d) || 0)}</span></div>
												<div class="inv-field"><span class="inv-field-label">Total Bytes</span><span class="inv-field-value mono">{formatBytes(Number(inv.sections.connection_history.total_bytes_7d) || 0)}</span></div>
												<div class="inv-field"><span class="inv-field-label">First Seen</span><span class="inv-field-value mono">{inv.sections.connection_history.first_seen ?? '--'}</span></div>
												<div class="inv-field"><span class="inv-field-label">Last Seen</span><span class="inv-field-value mono">{inv.sections.connection_history.last_seen ?? '--'}</span></div>
											</div>
										</div>
									{/if}
									<div class="inv-recommendation">
										<div class="inv-rec-label">Recommended Action</div>
										{inv.recommendation}
									</div>
								</div>
							{/if}
						</div>
					{/each}
				</div>
			</div>
		{/if}
	{/if}
</div>

<style>
	.threats-page { display: flex; flex-direction: column; gap: var(--space-lg); }
	.page-header { display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: var(--space-md); }
	h1 { font-size: var(--text-2xl); font-weight: 700; letter-spacing: -0.02em; }
	.subtitle { font-size: var(--text-sm); color: var(--text-muted); margin-top: 2px; }
	.header-controls { display: flex; align-items: center; gap: var(--space-md); }
	.pills { display: flex; gap: 2px; background: var(--bg-tertiary); border-radius: var(--radius-md); padding: 2px; border: 1px solid var(--border-dim); }
	.pill { padding: 5px 12px; border: none; background: transparent; color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--text-xs); font-weight: 500; border-radius: 5px; cursor: pointer; transition: all var(--transition-fast); }
	.pill:hover { color: var(--text-primary); background: var(--bg-elevated); }
	.pill.active { background: var(--cyan); color: var(--bg-void); font-weight: 600; }
	.loading-state { display: flex; align-items: center; justify-content: center; gap: var(--space-md); padding: var(--space-3xl); }
	.empty-state { text-align: center; padding: var(--space-3xl); color: var(--text-muted); }
	.empty-msg { padding: var(--space-lg); text-align: center; font-size: var(--text-sm); color: var(--text-muted); }

	/* Threat Brief */
	.threat-brief { display: grid; grid-template-columns: 280px 1fr; gap: var(--space-lg); padding: var(--space-lg); background: var(--bg-secondary); border: 1px solid var(--border-dim); border-radius: var(--radius-lg); position: relative; overflow: hidden; }
	.threat-brief::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: linear-gradient(90deg, var(--red), var(--amber), var(--red)); animation: threatPulse 3s ease-in-out infinite; }
	@keyframes threatPulse { 0%,100% { opacity: 0.6; } 50% { opacity: 1; } }
	.threat-score-area { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-md); padding: var(--space-md); border-right: 1px solid var(--border-dim); }
	.threat-gauge { width: 180px; height: 100px; }
	.threat-level-badge { font-size: var(--text-xs); font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; padding: 4px 16px; border-radius: var(--radius-sm); border: 1px solid; }
	.baseline-indicator { font-size: var(--text-xs); color: var(--text-muted); text-align: center; }
	.baseline-value { font-weight: 600; }
	.threat-brief-right { display: flex; flex-direction: column; gap: var(--space-md); }
	.brief-headline { font-size: var(--text-xl); font-weight: 700; line-height: 1.3; }
	.brief-subheadline { font-size: var(--text-sm); color: var(--text-muted); }
	.brief-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-md); }
	.brief-stat { background: var(--bg-tertiary); border: 1px solid var(--border-dim); border-radius: var(--radius-md); padding: var(--space-sm) var(--space-md); }
	.brief-stat-label { font-size: 10px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 500; }
	.brief-stat-value { font-family: var(--font-mono); font-size: var(--text-xl); font-weight: 600; color: var(--text-primary); margin-top: 2px; }
	.brief-stat-value.danger { color: var(--red); }
	.brief-stat-value.warning { color: var(--amber); }
	.category-bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; gap: 2px; }
	.cat-segment { border-radius: 4px; }
	.category-legend { display: flex; gap: var(--space-lg); font-size: var(--text-xs); color: var(--text-muted); flex-wrap: wrap; }
	.cat-legend-item { display: flex; align-items: center; gap: 6px; }
	.cat-dot { width: 8px; height: 8px; border-radius: 50%; }

	/* Cards */
	.card { background: var(--bg-secondary); border: 1px solid var(--border-dim); border-radius: var(--radius-md); overflow: hidden; }
	.card-header { display: flex; align-items: center; justify-content: space-between; padding: var(--space-md) var(--space-lg); border-bottom: 1px solid var(--border-dim); }
	.card-title { font-size: var(--text-sm); font-weight: 600; }
	.card-badge { font-family: var(--font-mono); font-size: var(--text-xs); color: var(--text-muted); background: var(--bg-tertiary); padding: 2px 8px; border-radius: var(--radius-sm); }
	.card-badge.danger { color: var(--red); background: rgba(255,71,87,0.12); }
	.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-md); }

	/* Kill Chains */
	.kill-chain-card { border-color: rgba(255,71,87,0.2); }
	.kill-chain-item { padding: var(--space-lg); border-bottom: 1px solid var(--border-dim); }
	.kill-chain-item:last-child { border-bottom: none; }
	.kc-header { display: flex; align-items: center; gap: var(--space-md); margin-bottom: var(--space-md); }
	.kc-ip { font-size: var(--text-lg); font-weight: 600; color: var(--red); }
	.kc-badge { font-size: 10px; font-weight: 700; text-transform: uppercase; padding: 2px 8px; border-radius: var(--radius-sm); background: rgba(255,71,87,0.12); color: var(--red); }
	.kc-stages { display: flex; align-items: center; margin-bottom: var(--space-md); flex-wrap: wrap; gap: var(--space-xs); }
	.kc-stage { display: flex; flex-direction: column; align-items: center; gap: var(--space-xs); padding: var(--space-sm) var(--space-md); background: var(--bg-tertiary); border: 1px solid var(--border-dim); border-radius: var(--radius-md); min-width: 110px; text-align: center; }
	.kc-stage.active { border-color: var(--red); background: rgba(255,71,87,0.08); }
	.kc-stage-num { font-family: var(--font-mono); font-size: 10px; color: var(--text-dim); font-weight: 600; }
	.kc-stage.active .kc-stage-num { color: var(--red); }
	.kc-stage-name { font-size: var(--text-xs); font-weight: 600; color: var(--text-secondary); }
	.kc-stage.active .kc-stage-name { color: var(--red); }
	.kc-stage-count { font-family: var(--font-mono); font-size: 10px; color: var(--text-dim); }
	.kc-arrow { font-size: 16px; color: var(--text-dim); }
	.kc-assessment { font-size: var(--text-sm); color: var(--text-secondary); line-height: 1.6; padding: var(--space-sm) var(--space-md); background: var(--bg-tertiary); border-radius: var(--radius-sm); border-left: 3px solid var(--red); }
	.kc-actions { display: flex; gap: var(--space-sm); margin-top: var(--space-md); }
	.btn-investigate { padding: 6px 16px; background: var(--red); color: var(--bg-void); border: none; border-radius: var(--radius-sm); font-size: var(--text-xs); font-weight: 700; cursor: pointer; font-family: var(--font-sans); transition: all var(--transition-fast); }
	.btn-investigate:hover { box-shadow: 0 0 16px rgba(255,71,87,0.4); }
	.btn-secondary-sm { padding: 6px 16px; background: transparent; color: var(--text-secondary); border: 1px solid var(--border-default); border-radius: var(--radius-sm); font-size: var(--text-xs); font-weight: 600; cursor: pointer; font-family: var(--font-sans); transition: all var(--transition-fast); }
	.btn-secondary-sm:hover { border-color: var(--border-bright); color: var(--text-primary); }

	/* Beaconing */
	.beacon-row { display: grid; grid-template-columns: 1fr auto auto auto auto; align-items: center; gap: var(--space-md); padding: var(--space-sm) var(--space-lg); border-bottom: 1px solid var(--border-dim); transition: background var(--transition-fast); }
	.beacon-row:hover { background: var(--bg-tertiary); }
	.beacon-row:last-child { border-bottom: none; }
	.beacon-pair { display: flex; flex-direction: column; gap: 2px; }
	.beacon-src { font-size: var(--text-sm); color: var(--cyan); }
	.beacon-dst { font-size: var(--text-xs); color: var(--purple); }
	.beacon-interval { font-size: var(--text-sm); font-weight: 600; }
	.beacon-jitter { font-size: var(--text-xs); color: var(--text-muted); }
	.confidence-meter { width: 60px; height: 6px; background: var(--bg-tertiary); border-radius: 3px; overflow: hidden; }
	.confidence-fill { height: 100%; border-radius: 3px; }
	.beacon-confidence { font-size: var(--text-xs); font-weight: 600; min-width: 32px; text-align: right; }

	/* DNS Anomalies */
	.anomaly-group-header { display: flex; align-items: center; gap: var(--space-sm); padding: var(--space-sm) var(--space-lg); font-size: var(--text-xs); font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-dim); border-bottom: 1px solid var(--border-dim); }
	.anomaly-count-badge { font-family: var(--font-mono); padding: 1px 6px; border-radius: var(--radius-sm); background: rgba(255,71,87,0.12); color: var(--red); font-size: 10px; }
	.dga-row { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: var(--space-md); padding: var(--space-sm) var(--space-lg); border-bottom: 1px solid var(--border-dim); }
	.dga-row:last-child { border-bottom: none; }
	.dga-domain { font-size: var(--text-sm); word-break: break-all; }
	.dga-entropy { font-size: var(--text-xs); color: var(--amber); font-weight: 600; }
	.dga-count { font-size: var(--text-xs); color: var(--text-muted); }
	.nxdomain-row { display: grid; grid-template-columns: auto 1fr auto auto; align-items: center; gap: var(--space-md); padding: var(--space-sm) var(--space-lg); border-bottom: 1px solid var(--border-dim); }
	.nxdomain-ip { font-size: var(--text-sm); color: var(--cyan); }
	.nxdomain-bar-track { height: 6px; background: var(--bg-tertiary); border-radius: 3px; overflow: hidden; }
	.nxdomain-bar-fill { height: 100%; background: var(--red); border-radius: 3px; }
	.nxdomain-pct { font-size: var(--text-xs); font-weight: 600; color: var(--red); min-width: 32px; text-align: right; }
	.nxdomain-count { font-size: 10px; color: var(--text-dim); }

	/* Lateral Movement */
	.lateral-row { display: grid; grid-template-columns: auto 1fr auto auto auto; align-items: center; gap: var(--space-md); padding: var(--space-sm) var(--space-lg); border-bottom: 1px solid var(--border-dim); transition: background var(--transition-fast); }
	.lateral-row:hover { background: var(--bg-tertiary); }
	.lateral-row:last-child { border-bottom: none; }
	.lateral-fanout { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: var(--radius-sm); font-size: 10px; font-weight: 700; background: rgba(255,71,87,0.12); color: var(--red); min-width: 85px; }
	.lateral-path { display: flex; align-items: center; gap: var(--space-sm); font-size: var(--text-sm); }
	.lateral-src { color: var(--cyan); }
	.lateral-arrow { color: var(--text-dim); font-size: 12px; }
	.lateral-dst { color: var(--purple); }
	.lateral-service { font-size: var(--text-xs); color: var(--text-muted); font-weight: 500; }
	.lateral-port { font-size: var(--text-xs); color: var(--text-secondary); }
	.lateral-count { font-size: var(--text-xs); color: var(--text-dim); }

	/* Threat Intel */
	.ti-row { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: var(--space-md); padding: var(--space-sm) var(--space-lg); border-bottom: 1px solid var(--border-dim); }
	.ti-row:last-child { border-bottom: none; }
	.ti-badge { font-size: 10px; font-weight: 700; text-transform: uppercase; padding: 2px 8px; border-radius: var(--radius-sm); background: rgba(255,71,87,0.12); color: var(--red); }
	.ti-feed-name { font-size: var(--text-sm); }
	.ti-feed-count { font-size: var(--text-xs); color: var(--text-muted); }

	/* Investigations */
	.inv-list { padding: var(--space-md); display: flex; flex-direction: column; gap: var(--space-md); }
	.investigation-card { border: 1px solid var(--border-dim); border-radius: var(--radius-md); overflow: hidden; }
	.inv-header { display: flex; align-items: center; justify-content: space-between; padding: var(--space-md) var(--space-lg); background: var(--bg-secondary); border: none; width: 100%; cursor: pointer; text-align: left; font: inherit; color: inherit; transition: background var(--transition-fast); }
	.inv-header:hover { background: var(--bg-tertiary); }
	.inv-title-area { display: flex; align-items: center; gap: var(--space-md); }
	.inv-sev { padding: 3px 10px; border-radius: var(--radius-sm); font-size: 10px; font-weight: 700; text-transform: uppercase; background: rgba(255,171,0,0.12); color: var(--amber); }
	.sev-critical { background: rgba(255,71,87,0.15); color: var(--red); }
	.sev-high { background: rgba(255,71,87,0.12); color: var(--red); }
	.inv-title { font-size: var(--text-sm); font-weight: 600; }
	.inv-subtitle { font-size: var(--text-xs); color: var(--text-muted); }
	.inv-expand { font-size: 14px; color: var(--text-dim); }
	.inv-body { padding: var(--space-lg); display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-lg); border-top: 1px solid var(--border-dim); }
	.inv-section-title { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-dim); margin-bottom: var(--space-sm); padding-bottom: var(--space-xs); border-bottom: 1px solid var(--border-dim); }
	.inv-detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-xs) var(--space-md); }
	.inv-field { display: flex; flex-direction: column; gap: 1px; }
	.inv-field-label { font-size: 10px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 500; }
	.inv-field-value { font-size: var(--text-sm); color: var(--text-primary); }
	.inv-recommendation { grid-column: 1 / -1; padding: var(--space-md); background: rgba(255,71,87,0.08); border: 1px solid rgba(255,71,87,0.2); border-radius: var(--radius-md); font-size: var(--text-sm); color: var(--text-primary); line-height: 1.6; }
	.inv-rec-label { font-size: 10px; font-weight: 700; text-transform: uppercase; color: var(--red); margin-bottom: var(--space-xs); letter-spacing: 0.06em; }

	/* Responsive */
	@media (max-width: 1024px) { .two-col { grid-template-columns: 1fr; } .brief-stats { grid-template-columns: repeat(2, 1fr); } .threat-brief { grid-template-columns: 1fr; } .inv-body { grid-template-columns: 1fr; } }
</style>
