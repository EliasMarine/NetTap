<!--
  DeviceDrawerContent.svelte — Overview, Connections, and Traffic tabs.
  Fetches connections and traffic data lazily on tab activation.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import DrawerSection from '../DrawerSection.svelte';
	import KVRow from '../KVRow.svelte';
	import { getWhois } from '$api/lookup';
	import type { WhoisResult } from '$api/lookup';
	import type { Device, DeviceConnection } from '$api/devices';

	let {
		device,
		activeTab,
	}: {
		device: Device;
		activeTab: string;
	} = $props();

	// Connections state
	let connections = $state<DeviceConnection[]>([]);
	let connLoading = $state(false);
	let connError = $state('');
	let connLoaded = $state(false);

	// Traffic state (bandwidth_series comes from device detail API)
	let trafficData = $state<Array<{ timestamp: string; bytes: number }>>([]);
	let trafficLoading = $state(false);
	let trafficLoaded = $state(false);

	// WHOIS state
	let whoisResult = $state<WhoisResult | null>(null);
	let whoisLoading = $state(false);

	// Risk score colors
	const RISK_COLORS: Record<string, string> = {
		critical: 'var(--sev-critical)',
		high: 'var(--sev-high)',
		medium: 'var(--sev-medium)',
		low: 'var(--sev-low)',
		none: 'var(--text-3)',
	};

	function getRiskLevel(score: number | undefined): string {
		if (score == null) return 'none';
		if (score >= 80) return 'critical';
		if (score >= 60) return 'high';
		if (score >= 40) return 'medium';
		if (score >= 20) return 'low';
		return 'none';
	}

	function formatBytes(bytes: number): string {
		if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
		if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
		if (bytes >= 1_024) return `${(bytes / 1_024).toFixed(1)} KB`;
		return `${bytes} B`;
	}

	function timeAgo(ts: string): string {
		const diff = Date.now() - new Date(ts).getTime();
		if (diff < 60_000) return 'just now';
		if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
		if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
		return `${Math.floor(diff / 86_400_000)}d ago`;
	}

	// Lazy load connections
	$effect(() => {
		if (activeTab === 'connections' && !connLoaded) {
			connLoaded = true;
			fetchConnections();
		}
	});

	// Lazy load traffic
	$effect(() => {
		if (activeTab === 'traffic' && !trafficLoaded) {
			trafficLoaded = true;
			fetchTraffic();
		}
	});

	async function fetchConnections() {
		connLoading = true;
		connError = '';
		try {
			const res = await fetch(`/api/devices/${encodeURIComponent(device.ip)}/connections?size=20`);
			if (res.ok) {
				const data = await res.json();
				connections = data.connections || [];
			} else {
				connError = 'Failed to fetch connections';
			}
		} catch {
			connError = 'Network error';
		} finally {
			connLoading = false;
		}
	}

	async function fetchTraffic() {
		trafficLoading = true;
		try {
			const res = await fetch(`/api/devices/${encodeURIComponent(device.ip)}`);
			if (res.ok) {
				const data = await res.json();
				trafficData = data.device?.bandwidth_series || [];
			}
		} catch {
			// Silent — traffic is optional
		} finally {
			trafficLoading = false;
		}
	}

	async function lookupWhois() {
		whoisLoading = true;
		whoisResult = null;
		try {
			whoisResult = await getWhois(device.ip);
		} finally {
			whoisLoading = false;
		}
	}

	function viewInLogExplorer() {
		goto(`/logs?filter=${encodeURIComponent(device.ip)}`);
	}

	// Simple SVG sparkline for traffic
	function buildSparklinePath(data: Array<{ bytes: number }>): string {
		if (data.length < 2) return '';
		const max = Math.max(...data.map(d => d.bytes), 1);
		const w = 400;
		const h = 60;
		const points = data.map((d, i) => {
			const x = (i / (data.length - 1)) * w;
			const y = h - (d.bytes / max) * h;
			return `${x},${y}`;
		});
		return `M${points.join(' L')}`;
	}
</script>

{#if activeTab === 'overview'}
	<div class="overview-content">
		<DrawerSection title="Identity" defaultExpanded>
			{#if device.unifi_name}
				<KVRow label="UniFi name" value={device.unifi_name} />
			{/if}
			<KVRow label="IP address" value={device.ip} mono copyable />
			<KVRow label="MAC address" value={device.mac} mono copyable />
			<KVRow label="Hostname" value={device.hostname} />
			<KVRow label="Manufacturer" value={device.manufacturer} />
			{#if device.os_hint}
				<KVRow label="OS hint" value={device.os_hint} />
			{/if}
		</DrawerSection>

		<DrawerSection title="Activity" defaultExpanded>
			<KVRow label="First seen" value={device.first_seen ? timeAgo(device.first_seen) : null} />
			<KVRow label="Last seen" value={device.last_seen ? timeAgo(device.last_seen) : null} />
			<KVRow label="Total bytes" value={formatBytes(device.total_bytes)} mono />
			<KVRow label="Connections" value={device.connection_count} mono />
			<KVRow label="Alerts" value={device.alert_count} mono />
		</DrawerSection>

		{#if device.protocols?.length > 0}
			<DrawerSection title="Protocols" defaultExpanded={false}>
				<div class="protocol-pills">
					{#each device.protocols as proto}
						<span class="tag">{proto}</span>
					{/each}
				</div>
			</DrawerSection>
		{/if}

		<!-- WHOIS inline -->
		{#if whoisResult}
			<DrawerSection title="WHOIS — {device.ip}" defaultExpanded>
				{#if whoisResult.error}
					<p class="error-text">{whoisResult.error}</p>
				{:else}
					{#each Object.entries(whoisResult.parsed) as [key, val]}
						<KVRow label={key} value={val} copyable />
					{/each}
				{/if}
			</DrawerSection>
		{/if}
	</div>

{:else if activeTab === 'connections'}
	<div class="connections-content">
		{#if connLoading}
			<div class="loading-state">
				<div class="loading-spinner"></div>
				<p class="dim">Loading connections…</p>
			</div>
		{:else if connError}
			<div class="error-state">
				<p class="error-text">{connError}</p>
				<button class="btn" type="button" onclick={fetchConnections}>Retry</button>
			</div>
		{:else if connections.length === 0}
			<div class="empty-state">
				<p class="dim">No recent connections found</p>
			</div>
		{:else}
			<div class="conn-list">
				{#each connections as conn}
					<div class="conn-item">
						<div class="conn-time">{conn.ts ? timeAgo(conn.ts) : '--'}</div>
						<div class="conn-detail">
							{#if conn.proto}
								<span class="tag">{String(conn.proto).toUpperCase()}</span>
							{/if}
							{#if conn.service}
								<span class="tag">{conn.service}</span>
							{/if}
							<span class="conn-dest mono">
								→ {conn['destination.ip'] || conn['resp_h'] || '--'}
							</span>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>

{:else if activeTab === 'traffic'}
	<div class="traffic-content">
		{#if trafficLoading}
			<div class="loading-state">
				<div class="loading-spinner"></div>
				<p class="dim">Loading traffic data…</p>
			</div>
		{:else if trafficData.length < 2}
			<div class="empty-state">
				<p class="dim">No bandwidth data available</p>
			</div>
		{:else}
			<DrawerSection title="Bandwidth (recent)" defaultExpanded>
				<div class="sparkline-container">
					<svg viewBox="0 0 400 60" preserveAspectRatio="none" class="sparkline-svg" role="img" aria-label="Recent bandwidth, peak {formatBytes(Math.max(...trafficData.map(d => d.bytes)))}">
						<path d={buildSparklinePath(trafficData)} fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke" />
					</svg>
				</div>
				<div class="traffic-stats">
					<span class="traffic-stat">
						Peak: <strong class="num">{formatBytes(Math.max(...trafficData.map(d => d.bytes)))}</strong>
					</span>
				</div>
			</DrawerSection>
		{/if}
	</div>
{/if}

<style>
	.overview-content, .connections-content, .traffic-content {
		display: flex;
		flex-direction: column;
	}

	.protocol-pills {
		display: flex;
		flex-wrap: wrap;
		gap: var(--sp-1);
	}

	.conn-list {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.conn-item {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		padding: var(--sp-2);
		border-radius: var(--r-sm);
		transition: background-color var(--dur-fast);
	}

	.conn-item:hover {
		background-color: var(--surface-2);
	}

	.conn-time {
		font-size: var(--text-xs);
		color: var(--text-3);
		white-space: nowrap;
		width: 60px;
		flex-shrink: 0;
	}

	.conn-detail {
		display: flex;
		align-items: center;
		gap: var(--sp-1);
		flex-wrap: wrap;
		flex: 1;
		min-width: 0;
	}

	.conn-dest {
		font-size: var(--text-sm);
		color: var(--text-1);
	}

	.sparkline-container {
		background-color: var(--surface-2);
		border: 1px solid var(--line);
		border-radius: var(--r-md);
		padding: var(--sp-2);
	}

	.sparkline-svg {
		width: 100%;
		height: 60px;
	}

	.traffic-stats {
		display: flex;
		gap: var(--sp-4);
		margin-top: var(--sp-2);
		font-size: var(--text-xs);
		color: var(--text-2);
	}

	.traffic-stat strong {
		color: var(--text-1);
		font-weight: 600;
	}

	/* Common */
	.loading-state {
		font-size: var(--text-sm);
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--sp-2);
		padding: var(--sp-8) 0;
	}

	.error-state, .empty-state {
		font-size: var(--text-sm);
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--sp-2);
		padding: var(--sp-8) 0;
		text-align: center;
	}

	.error-text { color: var(--sev-critical); font-size: var(--text-sm); }

	.loading-spinner {
		width: 24px;
		height: 24px;
		border: 2px solid var(--line);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}
</style>
