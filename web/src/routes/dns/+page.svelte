<script lang="ts">
	import { onMount } from 'svelte';
	import {
		getDnsStats,
		getTopDomains,
		getNxdomains,
		getQueryTypes,
		getDnsTimeline,
		getSuspiciousDns,
		getDeviceDns,
	} from '$lib/api/dns';
	import { page } from '$app/stores';
	import HorizontalBarList from '$components/HorizontalBarList.svelte';
	import type {
		DnsStats,
		TopDomain,
		NxdomainEntry,
		QueryTypeEntry,
		TimelineEntry,
		SuspiciousEntry,
		DeviceDnsEntry,
	} from '$lib/api/dns';

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	const TIME_RANGES = [
		{ label: '15m', value: '15m', ms: 15 * 60 * 1000 },
		{ label: '1h', value: '1h', ms: 60 * 60 * 1000 },
		{ label: '4h', value: '4h', ms: 4 * 60 * 60 * 1000 },
		{ label: '24h', value: '24h', ms: 24 * 60 * 60 * 1000 },
		{ label: '7d', value: '7d', ms: 7 * 24 * 60 * 60 * 1000 },
	];

	const SEVERITY_COLORS: Record<string, string> = {
		critical: 'var(--red)',
		high: 'var(--orange)',
		medium: 'var(--amber)',
		low: 'var(--accent)',
	};

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let selectedTimeRange = $state('24h');
	let loading = $state(true);
	let initialized = $state(false);

	// Data
	let stats = $state<DnsStats>({ total_queries: 0, unique_domains: 0, nxdomain_count: 0, avg_resolution_ms: 0 });
	let topDomains = $state<TopDomain[]>([]);
	let nxdomains = $state<NxdomainEntry[]>([]);
	let queryTypes = $state<QueryTypeEntry[]>([]);
	let timeline = $state<TimelineEntry[]>([]);
	let suspicious = $state<SuspiciousEntry[]>([]);

	// Per-device
	let deviceIpInput = $state('');
	let selectedDeviceIp = $state('');
	let deviceDns = $state<DeviceDnsEntry[]>([]);
	let deviceLoading = $state(false);

	// Interaction state
	let selectedDomain = $state<string | null>(null);
	let domainSearch = $state('');
	let hoveredBarIndex = $state<number | null>(null);

	// Sorting — Top Domains
	type DomainSortKey = 'domain' | 'count' | 'unique_clients';
	let domainSortKey = $state<DomainSortKey>('count');
	let domainSortDir = $state<'asc' | 'desc'>('desc');

	// Sorting — NXDOMAIN
	type NxSortKey = 'domain' | 'count';
	let nxSortKey = $state<NxSortKey>('count');
	let nxSortDir = $state<'asc' | 'desc'>('desc');

	// Sorting — Device DNS
	type DeviceSortKey = 'domain' | 'count';
	let deviceSortKey = $state<DeviceSortKey>('count');
	let deviceSortDir = $state<'asc' | 'desc'>('desc');

	// Chart dimensions
	let chartWidth = $state(800);

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	let filteredDomains = $derived(
		(() => {
			let list = [...topDomains];
			if (domainSearch) {
				const q = domainSearch.toLowerCase();
				list = list.filter((d) => d.domain.toLowerCase().includes(q));
			}
			const key = domainSortKey;
			list.sort((a, b) => {
				const cmp = key === 'domain'
					? a.domain.localeCompare(b.domain)
					: (a[key] as number) - (b[key] as number);
				return domainSortDir === 'asc' ? cmp : -cmp;
			});
			return list;
		})()
	);

	let sortedNxdomains = $derived(
		(() => {
			const list = [...nxdomains];
			list.sort((a, b) => {
				const cmp = nxSortKey === 'domain'
					? a.domain.localeCompare(b.domain)
					: a.count - b.count;
				return nxSortDir === 'asc' ? cmp : -cmp;
			});
			return list;
		})()
	);

	let sortedDeviceDns = $derived(
		(() => {
			const list = [...deviceDns];
			list.sort((a, b) => {
				const cmp = deviceSortKey === 'domain'
					? a.domain.localeCompare(b.domain)
					: a.count - b.count;
				return deviceSortDir === 'asc' ? cmp : -cmp;
			});
			return list;
		})()
	);

	let maxTimelineCount = $derived(Math.max(1, ...timeline.map((t) => t.count)));

	let totalQueryTypeCount = $derived(queryTypes.reduce((sum, qt) => sum + qt.count, 0));

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function getTimeRange(): { from: string; to: string } {
		const now = new Date();
		const range = TIME_RANGES.find((r) => r.value === selectedTimeRange);
		const ms = range?.ms ?? 24 * 60 * 60 * 1000;
		return {
			from: new Date(now.getTime() - ms).toISOString(),
			to: now.toISOString(),
		};
	}

	function formatNumber(n: number): string {
		if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
		if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
		return n.toString();
	}

	function formatTimestamp(ts: string): string {
		try {
			const d = new Date(ts);
			return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
		} catch {
			return ts;
		}
	}

	function sortIndicator(active: boolean, dir: 'asc' | 'desc'): string {
		return active ? (dir === 'asc' ? ' \u2191' : ' \u2193') : '';
	}

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchAll() {
		loading = true;
		const { from, to } = getTimeRange();
		const interval = selectedTimeRange === '15m' ? '1m' : selectedTimeRange === '1h' ? '5m' : selectedTimeRange === '4h' ? '10m' : selectedTimeRange === '7d' ? '1h' : '15m';

		const results = await Promise.allSettled([
			getDnsStats({ from, to }),
			getTopDomains({ from, to, limit: 50 }),
			getNxdomains({ from, to }),
			getQueryTypes({ from, to }),
			getDnsTimeline({ from, to, interval }),
			getSuspiciousDns({ from, to }),
		]);

		if (results[0].status === 'fulfilled') stats = results[0].value;
		if (results[1].status === 'fulfilled') topDomains = results[1].value.domains;
		if (results[2].status === 'fulfilled') nxdomains = results[2].value.nxdomains;
		if (results[3].status === 'fulfilled') queryTypes = results[3].value.types;
		if (results[4].status === 'fulfilled') timeline = results[4].value.series;
		if (results[5].status === 'fulfilled') suspicious = results[5].value.suspicious;

		loading = false;
	}

	async function lookupDevice() {
		const ip = deviceIpInput.trim() || selectedDeviceIp;
		if (!ip) return;

		deviceLoading = true;
		selectedDeviceIp = ip;
		const { from, to } = getTimeRange();

		try {
			const result = await getDeviceDns(ip, { from, to });
			deviceDns = result.domains;
		} catch {
			deviceDns = [];
		} finally {
			deviceLoading = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Interaction handlers
	// ---------------------------------------------------------------------------

	function selectDomain(domain: string) {
		selectedDomain = selectedDomain === domain ? null : domain;
	}

	function selectDeviceIp(ip: string) {
		deviceIpInput = ip;
		selectedDeviceIp = ip;
		lookupDevice();
		setTimeout(() => {
			document.getElementById('device-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
		}, 50);
	}

	function toggleDomainSort(key: DomainSortKey) {
		if (domainSortKey === key) {
			domainSortDir = domainSortDir === 'asc' ? 'desc' : 'asc';
		} else {
			domainSortKey = key;
			domainSortDir = key === 'domain' ? 'asc' : 'desc';
		}
	}

	function toggleNxSort(key: NxSortKey) {
		if (nxSortKey === key) {
			nxSortDir = nxSortDir === 'asc' ? 'desc' : 'asc';
		} else {
			nxSortKey = key;
			nxSortDir = key === 'domain' ? 'asc' : 'desc';
		}
	}

	function toggleDeviceSort(key: DeviceSortKey) {
		if (deviceSortKey === key) {
			deviceSortDir = deviceSortDir === 'asc' ? 'desc' : 'asc';
		} else {
			deviceSortKey = key;
			deviceSortDir = key === 'domain' ? 'asc' : 'desc';
		}
	}

	function handleTimeRangeChange(value: string) {
		selectedTimeRange = value;
		if (initialized) fetchAll();
	}

	function copyDomain(domain: string) {
		navigator.clipboard.writeText(domain);
	}

	// ---------------------------------------------------------------------------
	// Lifecycle
	// ---------------------------------------------------------------------------

	onMount(() => {
		// Apply query params from URL
		const urlDomain = $page.url.searchParams.get('domain') || '';
		const urlType = $page.url.searchParams.get('type') || '';
		if (urlDomain) {
			domainSearch = urlDomain;
		}
		if (urlType) {
			// urlType can pre-filter; stored for potential future use
			domainSearch = domainSearch || urlType;
		}

		fetchAll().then(() => {
			initialized = true;
		});
	});
</script>

<svelte:head>
	<title>DNS Analytics - NetTap</title>
</svelte:head>

<div class="page-container">
	<!-- Header -->
	<header class="page-header">
		<div class="header-left">
			<h1>DNS Analytics</h1>
			<p class="subtitle">Domain queries, NXDOMAIN errors, and suspicious patterns</p>
		</div>
		<div class="header-right">
			<div class="pills">
				{#each TIME_RANGES as range}
					<button
						class="pill"
						class:active={selectedTimeRange === range.value}
						onclick={() => handleTimeRangeChange(range.value)}
					>
						{range.label}
					</button>
				{/each}
			</div>
			<button class="btn btn-primary" onclick={fetchAll} disabled={loading}>
				{loading ? 'Loading...' : 'Refresh'}
			</button>
		</div>
	</header>

	<!-- Hero Stats -->
	<div class="stats-grid">
		<div class="stat-card">
			<span class="stat-label">Total Queries</span>
			<span class="stat-value">{formatNumber(stats.total_queries)}</span>
		</div>
		<div class="stat-card">
			<span class="stat-label">Unique Domains</span>
			<span class="stat-value">{formatNumber(stats.unique_domains)}</span>
		</div>
		<button class="stat-card clickable" onclick={() => document.getElementById('nxdomain-section')?.scrollIntoView({ behavior: 'smooth' })}>
			<span class="stat-label">NXDOMAIN Errors</span>
			<span class="stat-value" class:text-warning={stats.nxdomain_count > 0}>{formatNumber(stats.nxdomain_count)}</span>
		</button>
		<div class="stat-card">
			<span class="stat-label">Avg Resolution</span>
			<span class="stat-value">{stats.avg_resolution_ms.toFixed(1)}<span class="stat-unit">ms</span></span>
		</div>
	</div>

	<!-- Timeline Chart -->
	<section class="card">
		<h2>Query Volume Timeline</h2>
		{#if timeline.length === 0 && !loading}
			<p class="empty-state">No timeline data available for this time range.</p>
		{:else}
			<div class="chart-wrapper" bind:clientWidth={chartWidth}>
				<svg class="timeline-svg" viewBox="0 0 {chartWidth} 220" preserveAspectRatio="none">
					<!-- Y-axis gridlines -->
					{#each [0, 0.25, 0.5, 0.75, 1] as frac}
						<line
							x1="45" y1={200 - frac * 180}
							x2={chartWidth} y2={200 - frac * 180}
							stroke="var(--border-dim)" stroke-width="1"
						/>
						{#if frac === 0 || frac === 0.5 || frac === 1}
							<text
								x="40" y={204 - frac * 180}
								text-anchor="end" font-size="10"
								fill="var(--text-muted)"
							>{formatNumber(Math.round(maxTimelineCount * frac))}</text>
						{/if}
					{/each}

					<!-- Bars -->
					{#each timeline as point, i}
						{@const barW = Math.max(2, (chartWidth - 50) / timeline.length - 1)}
						{@const x = 50 + i * ((chartWidth - 50) / timeline.length)}
						{@const h = (point.count / maxTimelineCount) * 180}
						<rect
							{x} y={200 - h} width={barW} height={Math.max(1, h)}
							fill={hoveredBarIndex === i ? 'var(--accent)' : 'var(--cyan)'}
							opacity={hoveredBarIndex !== null && hoveredBarIndex !== i ? 0.4 : 1}
							rx="1"
							onmouseenter={() => hoveredBarIndex = i}
							onmouseleave={() => hoveredBarIndex = null}
							style="cursor: pointer; transition: opacity 100ms"
						/>
					{/each}

					<!-- X-axis labels -->
					{#each Array(Math.min(6, timeline.length)) as _, idx}
						{@const i = Math.round(idx * (timeline.length - 1) / Math.max(1, Math.min(5, timeline.length - 1)))}
						{@const x = 50 + i * ((chartWidth - 50) / timeline.length) + Math.max(2, (chartWidth - 50) / timeline.length - 1) / 2}
						{#if timeline[i]}
							<text
								{x} y="216" text-anchor="middle" font-size="10"
								fill="var(--text-muted)"
							>{formatTimestamp(timeline[i].timestamp)}</text>
						{/if}
					{/each}
				</svg>

				<!-- Hover tooltip -->
				{#if hoveredBarIndex !== null && timeline[hoveredBarIndex]}
					{@const tooltipX = 50 + hoveredBarIndex * ((chartWidth - 50) / timeline.length)}
					<div class="bar-tooltip" style="left: {Math.min(tooltipX, chartWidth - 150)}px">
						<span class="mono">{formatTimestamp(timeline[hoveredBarIndex].timestamp)}</span>
						<span class="accent">{timeline[hoveredBarIndex].count.toLocaleString()} queries</span>
					</div>
				{/if}
			</div>
		{/if}
	</section>

	<!-- Two-column: Top Domains + Query Types -->
	<div class="two-col">
		<!-- Top Queried Domains -->
		<section class="card">
			<div class="card-header">
				<h2>Top Queried Domains</h2>
				<input
					type="text"
					class="search-input"
					placeholder="Filter domains..."
					bind:value={domainSearch}
				/>
			</div>
			{#if topDomains.length === 0 && !loading}
				<p class="empty-state">No domains recorded. Check that Zeek is capturing DNS traffic.</p>
			{:else}
				<div class="table-container">
					<table class="data-table">
						<thead>
							<tr>
								<th>
									<button class="sort-btn" class:active-sort={domainSortKey === 'domain'} onclick={() => toggleDomainSort('domain')}>
										Domain{sortIndicator(domainSortKey === 'domain', domainSortDir)}
									</button>
								</th>
								<th>
									<button class="sort-btn" class:active-sort={domainSortKey === 'count'} onclick={() => toggleDomainSort('count')}>
										Queries{sortIndicator(domainSortKey === 'count', domainSortDir)}
									</button>
								</th>
								<th>
									<button class="sort-btn" class:active-sort={domainSortKey === 'unique_clients'} onclick={() => toggleDomainSort('unique_clients')}>
										Clients{sortIndicator(domainSortKey === 'unique_clients', domainSortDir)}
									</button>
								</th>
								<th></th>
							</tr>
						</thead>
						<tbody>
							{#each filteredDomains.slice(0, 25) as domain}
								<tr
									class="clickable-row"
									class:selected-row={selectedDomain === domain.domain}
									onclick={() => selectDomain(domain.domain)}
								>
									<td class="mono domain-cell">{domain.domain}</td>
									<td class="mono">{domain.count.toLocaleString()}</td>
									<td class="mono">{domain.unique_clients}</td>
									<td>
										<button class="btn-icon copy-btn" title="Copy domain" onclick={(e) => { e.stopPropagation(); copyDomain(domain.domain); }}>
											&#x2398;
										</button>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				{#if filteredDomains.length > 25}
					<p class="table-footer">Showing 25 of {filteredDomains.length} domains</p>
				{/if}
			{/if}
		</section>

		<!-- Query Type Distribution -->
		<section class="card">
			<h2>Query Type Distribution</h2>
			{#if queryTypes.length === 0 && !loading}
				<p class="empty-state">No query type data available.</p>
			{:else}
				<HorizontalBarList
					items={queryTypes.map(qt => {
						const pct = totalQueryTypeCount > 0 ? (qt.count / totalQueryTypeCount) * 100 : 0;
						return {
							key: qt.type,
							label: qt.type,
							mono: true,
							value: qt.count,
							formattedValue: qt.count.toLocaleString(),
							color: 'var(--cyan)',
							secondaryValue: pct.toFixed(1) + '%',
						};
					})}
					maxValue={queryTypes.length > 0 ? queryTypes[0].count : 1}
					showRank={false}
					labelWidth={60}
					barHeight={12}
				/>
			{/if}
		</section>
	</div>

	<!-- Per-Device DNS -->
	<section class="card" id="device-section">
		<h2>Per-Device DNS</h2>
		<div class="device-layout">
			<div class="device-input-panel">
				{#if selectedDomain}
					<div class="domain-banner">
						<span class="label">Selected domain</span>
						<span class="mono">{selectedDomain}</span>
						<button class="btn-icon" onclick={() => selectedDomain = null}>&times;</button>
					</div>
				{/if}
				<div class="device-input-row">
					<input
						type="text"
						class="input"
						placeholder="Enter device IP (e.g. 192.168.1.100)"
						bind:value={deviceIpInput}
						onkeydown={(e) => e.key === 'Enter' && lookupDevice()}
					/>
					<button class="btn btn-primary" onclick={lookupDevice} disabled={deviceLoading}>
						{deviceLoading ? 'Loading...' : 'Lookup'}
					</button>
				</div>
			</div>
			<div class="device-results-panel">
				{#if !selectedDeviceIp}
					<p class="empty-state">Enter a device IP to see its DNS queries.</p>
				{:else if deviceLoading}
					<p class="empty-state">Loading DNS data for {selectedDeviceIp}...</p>
				{:else if deviceDns.length === 0}
					<p class="empty-state">No DNS records for <span class="mono">{selectedDeviceIp}</span></p>
				{:else}
					<div class="table-container">
						<table class="data-table">
							<thead>
								<tr>
									<th>
										<button class="sort-btn" class:active-sort={deviceSortKey === 'domain'} onclick={() => toggleDeviceSort('domain')}>
											Domain{sortIndicator(deviceSortKey === 'domain', deviceSortDir)}
										</button>
									</th>
									<th>
										<button class="sort-btn" class:active-sort={deviceSortKey === 'count'} onclick={() => toggleDeviceSort('count')}>
											Queries{sortIndicator(deviceSortKey === 'count', deviceSortDir)}
										</button>
									</th>
									<th>Types</th>
								</tr>
							</thead>
							<tbody>
								{#each sortedDeviceDns.slice(0, 50) as entry}
									<tr
										class="clickable-row"
										class:selected-row={selectedDomain === entry.domain}
										onclick={() => selectDomain(entry.domain)}
									>
										<td class="mono domain-cell">{entry.domain}</td>
										<td class="mono">{entry.count.toLocaleString()}</td>
										<td class="mono">{entry.query_types.map((t) => t.type).join(', ')}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
					{#if deviceDns.length > 50}
						<p class="table-footer">Showing 50 of {deviceDns.length} domains</p>
					{/if}
				{/if}
			</div>
		</div>
	</section>

	<!-- Two-column: NXDOMAIN + Suspicious -->
	<div class="two-col" id="nxdomain-section">
		<!-- NXDOMAIN Errors -->
		<section class="card">
			<h2>NXDOMAIN Errors</h2>
			{#if nxdomains.length === 0 && !loading}
				<p class="empty-state ok-state">No NXDOMAIN errors detected. That's a good sign.</p>
			{:else}
				<div class="table-container">
					<table class="data-table">
						<thead>
							<tr>
								<th>
									<button class="sort-btn" class:active-sort={nxSortKey === 'domain'} onclick={() => toggleNxSort('domain')}>
										Domain{sortIndicator(nxSortKey === 'domain', nxSortDir)}
									</button>
								</th>
								<th>
									<button class="sort-btn" class:active-sort={nxSortKey === 'count'} onclick={() => toggleNxSort('count')}>
										Count{sortIndicator(nxSortKey === 'count', nxSortDir)}
									</button>
								</th>
								<th>Clients</th>
							</tr>
						</thead>
						<tbody>
							{#each sortedNxdomains as nx}
								<tr class="clickable-row" onclick={() => selectDomain(nx.domain)}>
									<td class="mono domain-cell">{nx.domain}</td>
									<td class="mono">{nx.count.toLocaleString()}</td>
									<td>
										{#each nx.clients.slice(0, 3) as ip, j}
											{#if j > 0}<span class="text-muted">, </span>{/if}
											<button class="ip-link mono" onclick={(e) => { e.stopPropagation(); selectDeviceIp(ip); }}>{ip}</button>
										{/each}
										{#if nx.clients.length > 3}
											<span class="text-muted"> +{nx.clients.length - 3}</span>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</section>

		<!-- Suspicious DNS Patterns -->
		<section class="card">
			<h2>Suspicious DNS Patterns</h2>
			{#if suspicious.length === 0 && !loading}
				<p class="empty-state ok-state">No suspicious DNS patterns detected.</p>
			{:else}
				<div class="suspicious-list">
					{#each suspicious as s}
						<div class="suspicious-item">
							<div class="suspicious-header">
								<span class="severity-badge" style="background: {SEVERITY_COLORS[s.severity] || 'var(--text-muted)'}">{s.severity}</span>
								<span class="suspicious-type">{s.type.replace(/_/g, ' ')}</span>
							</div>
							<button class="suspicious-domain mono" onclick={() => selectDomain(s.domain)}>{s.domain}</button>
							<p class="suspicious-desc">{s.description}</p>
							<div class="suspicious-meta">
								<span>{s.count.toLocaleString()} queries</span>
								{#if s.unique_clients}
									<span>{s.unique_clients} client(s)</span>
								{/if}
								{#if s.length}
									<span>{s.length} chars</span>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</section>
	</div>
</div>

<style>
	.page-container {
		margin: 0 auto;
		padding: var(--space-lg);
	}

	/* Header */
	.page-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		margin-bottom: var(--space-lg);
		flex-wrap: wrap;
		gap: var(--space-md);
	}

	.header-left h1 {
		font-size: var(--text-3xl);
		font-weight: 700;
		color: var(--text-primary);
		margin: 0;
	}

	.subtitle {
		color: var(--text-secondary);
		margin: var(--space-xs) 0 0;
		font-size: var(--text-base);
	}

	.header-right {
		display: flex;
		gap: var(--space-sm);
		align-items: center;
	}

	/* Pills */
	.pills {
		display: flex;
		gap: var(--space-xs);
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 0.2rem;
	}

	.pill {
		padding: 0.35rem 0.75rem;
		border: none;
		border-radius: var(--radius-sm);
		background: transparent;
		color: var(--text-secondary);
		font-size: var(--text-sm);
		cursor: pointer;
		transition: all 0.15s;
	}

	.pill:hover { color: var(--text-primary); }

	.pill.active {
		background: var(--accent);
		color: #000;
	}

	/* Buttons */
	.btn {
		padding: var(--space-sm) var(--space-md);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		cursor: pointer;
		font-size: var(--text-base);
		transition: all 0.15s;
		background: var(--bg-secondary);
		color: var(--text-primary);
	}

	.btn:disabled { opacity: 0.5; cursor: not-allowed; }

	.btn-primary {
		background: var(--accent);
		border-color: var(--accent);
		color: #000;
	}

	.btn-primary:hover:not(:disabled) { filter: brightness(0.85); }

	.btn-icon {
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		padding: var(--space-xs);
		font-size: 1rem;
		line-height: 1;
	}

	.btn-icon:hover { color: var(--text-primary); }

	/* Stats Grid */
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--space-md);
		margin-bottom: var(--space-lg);
	}

	.stat-card.clickable {
		text-align: left;
		width: 100%;
	}

	.stat-unit {
		font-size: 1rem;
		color: var(--text-muted);
		font-weight: 400;
	}

	.text-warning { color: var(--amber); }

	/* Cards */
	.card {
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		padding: var(--space-lg);
		margin-bottom: var(--space-lg);
	}

	.card h2 {
		font-size: var(--text-lg);
		font-weight: 600;
		color: var(--text-primary);
		margin: 0 0 var(--space-md);
	}

	.card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: var(--space-md);
	}

	.card-header h2 { margin: 0; }

	/* Two-column layout */
	.two-col {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-lg);
		margin-bottom: var(--space-lg);
	}

	.two-col .card { margin-bottom: 0; }

	/* Timeline Chart */
	.chart-wrapper {
		position: relative;
		width: 100%;
		min-height: 220px;
	}

	.timeline-svg {
		width: 100%;
		height: 220px;
	}

	.bar-tooltip {
		position: absolute;
		top: -8px;
		background: var(--bg-elevated);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		padding: var(--space-xs) var(--space-sm);
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: var(--text-xs);
		pointer-events: none;
		z-index: 10;
		white-space: nowrap;
	}

	.bar-tooltip .accent { color: var(--accent); font-weight: 600; }

	/* Search input */
	.search-input {
		padding: var(--space-xs) var(--space-sm);
		background: var(--bg-input);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		color: var(--text-primary);
		font-size: var(--text-sm);
		width: 200px;
	}

	.search-input::placeholder { color: var(--text-muted); }

	/* Tables */
	.table-container {
		overflow-x: auto;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		max-height: 450px;
		overflow-y: auto;
	}

	.data-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}

	.data-table th {
		background: var(--bg-secondary);
		padding: var(--space-sm);
		text-align: left;
		color: var(--text-secondary);
		font-weight: 600;
		border-bottom: 1px solid var(--border-default);
		white-space: nowrap;
		position: sticky;
		top: 0;
		z-index: 1;
	}

	.data-table td {
		padding: var(--space-sm);
		border-bottom: 1px solid var(--border-dim);
		color: var(--text-primary);
	}

	.clickable-row { cursor: pointer; }
	.clickable-row:hover td { background: var(--bg-tertiary); }

	.selected-row td {
		background: color-mix(in srgb, var(--accent) 10%, transparent);
		border-left: 2px solid var(--accent);
	}

	.domain-cell {
		max-width: 280px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.sort-btn {
		background: none;
		border: none;
		color: var(--text-secondary);
		font-weight: 600;
		font-size: var(--text-sm);
		cursor: pointer;
		padding: 0;
		white-space: nowrap;
	}

	.sort-btn:hover { color: var(--text-primary); }
	.sort-btn.active-sort { color: var(--accent); }

	.copy-btn {
		opacity: 0;
		transition: opacity 0.15s;
		font-size: 1.25rem;
		color: var(--accent);
		padding: var(--space-xs) var(--space-sm);
	}

	.copy-btn:hover { color: var(--cyan); }
	.clickable-row:hover .copy-btn { opacity: 1; }

	.table-footer {
		text-align: center;
		font-size: var(--text-xs);
		color: var(--text-muted);
		padding: var(--space-sm);
	}

	.mono {
		font-family: 'JetBrains Mono', monospace;
		font-size: var(--text-sm);
	}

	.text-muted { color: var(--text-muted); }

	/* OLD CODE START — type-bars replaced by HorizontalBarList component */
	/*
	.type-bars {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.type-row {
		display: grid;
		grid-template-columns: 60px 1fr 80px 50px;
		align-items: center;
		gap: var(--space-sm);
	}

	.type-label {
		font-size: var(--text-sm);
		color: var(--text-secondary);
		text-align: right;
	}

	.type-bar-track {
		height: 24px;
		background: var(--bg-input);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.type-bar-fill {
		height: 100%;
		background: var(--cyan);
		border-radius: var(--radius-sm);
		transition: width 0.3s ease;
		min-width: 2px;
	}

	.type-count {
		text-align: right;
		font-size: var(--text-sm);
		color: var(--text-primary);
	}

	.type-pct {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-align: right;
	}
	*/
	/* OLD CODE END */

	/* Device Section */
	.device-layout {
		display: grid;
		grid-template-columns: 1fr 1.5fr;
		gap: var(--space-lg);
	}

	.device-input-panel {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.device-input-row {
		display: flex;
		gap: var(--space-sm);
	}

	.input {
		flex: 1;
		padding: var(--space-sm);
		background: var(--bg-input);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		color: var(--text-primary);
		font-family: 'JetBrains Mono', monospace;
		font-size: var(--text-base);
	}

	.input::placeholder { color: var(--text-muted); }

	.domain-banner {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		background: color-mix(in srgb, var(--accent) 10%, transparent);
		border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
		border-radius: var(--radius-md);
		padding: var(--space-sm);
	}

	.domain-banner .label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
	}

	.domain-banner .mono {
		flex: 1;
		color: var(--accent);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	/* IP Links */
	.ip-link {
		background: none;
		border: none;
		color: var(--accent);
		cursor: pointer;
		padding: 0;
		font-size: var(--text-sm);
		text-decoration: underline;
		text-decoration-style: dotted;
	}

	.ip-link:hover { color: var(--cyan); }

	/* Suspicious DNS */
	.suspicious-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.suspicious-item {
		background: var(--bg-input);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-md);
	}

	.suspicious-header {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		margin-bottom: var(--space-xs);
	}

	.severity-badge {
		font-size: var(--text-xs);
		font-weight: 700;
		text-transform: uppercase;
		padding: 2px var(--space-sm);
		border-radius: var(--radius-full);
		color: #000;
	}

	.suspicious-type {
		font-size: var(--text-sm);
		color: var(--text-secondary);
		text-transform: capitalize;
	}

	.suspicious-domain {
		background: none;
		border: none;
		color: var(--accent);
		cursor: pointer;
		padding: 0;
		font-size: var(--text-base);
		text-decoration: underline;
		text-decoration-style: dotted;
		margin-bottom: var(--space-xs);
		display: block;
		text-align: left;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.suspicious-domain:hover { color: var(--cyan); }

	.suspicious-desc {
		font-size: var(--text-sm);
		color: var(--text-secondary);
		margin: var(--space-xs) 0;
		line-height: 1.4;
	}

	.suspicious-meta {
		display: flex;
		gap: var(--space-md);
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	/* Empty states */
	.empty-state {
		color: var(--text-muted);
		font-size: var(--text-base);
		text-align: center;
		padding: var(--space-xl) var(--space-md);
	}

	.ok-state { color: var(--green); }

	/* Responsive */
	@media (max-width: 900px) {
		.stats-grid { grid-template-columns: repeat(2, 1fr); }
		.two-col { grid-template-columns: 1fr; }
		.device-layout { grid-template-columns: 1fr; }
	}
</style>
