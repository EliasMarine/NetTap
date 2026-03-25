<!--
  LiveConnectionDrawerContent.svelte — Drawer content for a live connection.
  Two tabs:
    1. "details" — Connection info (source/dest, protocol, bytes, duration) + GeoIP enrichment
    2. "alerts"  — Related Suricata alerts + 24h history sparkline
  Uses DrawerSection + KVRow for consistent styling with other drawer content.
-->
<script lang="ts">
	import type { LiveConnection, ConnectionDetailResponse } from '$lib/api/live';
	import DrawerSection from '../DrawerSection.svelte';
	import KVRow from '../KVRow.svelte';

	// ---------------------------------------------------------------------------
	// Props
	// ---------------------------------------------------------------------------

	let {
		connection,
		detail = null,
		detailLoading = false,
		activeTab,
	}: {
		connection: LiveConnection;
		detail: ConnectionDetailResponse | null;
		detailLoading: boolean;
		activeTab: string;
	} = $props();

	// ---------------------------------------------------------------------------
	// Format helpers
	// ---------------------------------------------------------------------------

	function formatBytes(bytes: number): string {
		if (bytes >= 1_000_000_000) return (bytes / 1_000_000_000).toFixed(1) + ' GB';
		if (bytes >= 1_000_000) return (bytes / 1_000_000).toFixed(1) + ' MB';
		if (bytes >= 1_000) return (bytes / 1_000).toFixed(1) + ' KB';
		return bytes + ' B';
	}

	function formatDuration(seconds: number): string {
		if (seconds < 0.001) return '<1ms';
		if (seconds < 1) return (seconds * 1000).toFixed(0) + 'ms';
		if (seconds < 60) return seconds.toFixed(1) + 's';
		if (seconds < 3600) {
			const m = Math.floor(seconds / 60);
			const s = Math.round(seconds % 60);
			return `${m}m ${s}s`;
		}
		const h = Math.floor(seconds / 3600);
		const m = Math.round((seconds % 3600) / 60);
		return `${h}h ${m}m`;
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

	function countryFlag(code: string): string {
		if (!code || code.length !== 2) return '';
		const base = 0x1F1E6; // Regional Indicator Symbol Letter A
		const upper = code.toUpperCase();
		return String.fromCodePoint(
			upper.codePointAt(0)! - 65 + base,
			upper.codePointAt(1)! - 65 + base
		);
	}

	function formatCoordinates(lat: number | null, lon: number | null): string {
		if (lat == null || lon == null) return '--';
		return `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
	}

	function directionLabel(): string {
		return connection.dest_port < 1024 ? 'Outbound' : 'Inbound';
	}

	function severityLabel(sev: number): string {
		switch (sev) {
			case 1: return 'HIGH';
			case 2: return 'MEDIUM';
			case 3: return 'LOW';
			default: return 'INFO';
		}
	}

	function severityClass(sev: number): string {
		switch (sev) {
			case 1: return 'severity-high';
			case 2: return 'severity-medium';
			case 3: return 'severity-low';
			default: return 'severity-info';
		}
	}

	// ---------------------------------------------------------------------------
	// Sparkline helpers
	// ---------------------------------------------------------------------------

	let timelineMax = $derived.by(() => {
		if (!detail?.history?.timeline?.length) return 1;
		return Math.max(...detail.history.timeline.map(t => t.bytes), 1);
	});

	// ---------------------------------------------------------------------------
	// GeoIP: prefer detail.geo when loaded, fall back to connection fields
	// ---------------------------------------------------------------------------

	let geoCountry = $derived(detail?.geo?.country || connection.country_name || connection.country || '--');
	let geoCountryCode = $derived(detail?.geo?.country_code || connection.country || '');
	let geoCity = $derived(detail?.geo?.city || connection.dest_city || '--');
	let geoLat = $derived(detail?.geo?.lat ?? connection.dest_lat);
	let geoLon = $derived(detail?.geo?.lon ?? connection.dest_lon);
	let geoAsn = $derived(detail?.geo?.asn ?? connection.dest_asn);
	let geoOrg = $derived(detail?.geo?.organization || connection.dest_org || '--');
</script>

<!-- ======================================================================= -->
<!-- DETAILS TAB                                                             -->
<!-- ======================================================================= -->
{#if activeTab === 'details'}
	<DrawerSection title="Connection Info">
		<KVRow label="Source IP" value={`${connection.source_ip}:${connection.source_port}`} mono copyable />
		<KVRow label="Destination IP" value={`${connection.dest_ip}:${connection.dest_port}`} mono copyable />
		<KVRow label="Protocol" value={(connection.service || connection.protocol || '').toUpperCase()} />
		<KVRow label="Direction" value={directionLabel()} />
		<KVRow label="Bytes" value={formatBytes(connection.bytes)} mono />
		<KVRow label="Duration" value={formatDuration(connection.duration)} mono />
		<KVRow label="Device" value={connection.device_name || '--'} />
		<KVRow label="Timestamp" value={formatTimestamp(connection.timestamp)} mono />
	</DrawerSection>

	<DrawerSection title="GeoIP Information">
		{#if detailLoading}
			<div class="loading-row">
				<span class="loading-spinner"></span>
				<span class="loading-text">Loading GeoIP data...</span>
			</div>
		{:else}
			<KVRow label="Country" value={geoCountryCode ? `${countryFlag(geoCountryCode)} ${geoCountry}` : geoCountry} />
			<KVRow label="City" value={geoCity} />
			<KVRow label="Coordinates" value={formatCoordinates(geoLat, geoLon)} mono />
			<KVRow label="ASN" value={geoAsn != null ? `AS${geoAsn}` : null} mono />
			<KVRow label="Organization" value={geoOrg} />
		{/if}
	</DrawerSection>

<!-- ======================================================================= -->
<!-- ALERTS TAB                                                              -->
<!-- ======================================================================= -->
{:else if activeTab === 'alerts'}
	<DrawerSection title="Related Suricata Alerts">
		{#if detailLoading}
			<div class="loading-row">
				<span class="loading-spinner"></span>
				<span class="loading-text">Loading alerts...</span>
			</div>
		{:else if !detail?.alerts?.length}
			<div class="empty-section">
				<span class="empty-icon">&#x2714;</span>
				<span class="empty-label">No alerts for this connection</span>
			</div>
		{:else}
			<div class="alert-list">
				{#each detail.alerts as alert}
					<div class="alert-card">
						<div class="alert-header">
							<span class="badge {severityClass(alert.severity)}">{severityLabel(alert.severity)}</span>
							<span class="alert-time">{formatTimestamp(alert.timestamp)}</span>
						</div>
						<div class="alert-sig">{alert.signature}</div>
						<div class="alert-cat">{alert.category}</div>
					</div>
				{/each}
			</div>
		{/if}
	</DrawerSection>

	<DrawerSection title="24h History">
		{#if detailLoading}
			<div class="loading-row">
				<span class="loading-spinner"></span>
				<span class="loading-text">Loading history...</span>
			</div>
		{:else if !detail?.history?.timeline?.length}
			<div class="empty-section">
				<span class="empty-label">No history data available</span>
			</div>
		{:else}
			<div class="history-summary">
				<KVRow label="Total Bytes (24h)" value={formatBytes(detail.history.total_bytes)} mono />
				<KVRow label="Connections (24h)" value={String(detail.history.connection_count)} mono />
			</div>

			<div class="sparkline-wrap">
				<div class="sparkline">
					{#each detail.history.timeline as bucket}
						{@const heightPct = Math.max((bucket.bytes / timelineMax) * 100, 2)}
						<div
							class="spark-bar"
							style:height="{heightPct}%"
							title="{formatTimestamp(bucket.timestamp)}: {formatBytes(bucket.bytes)} / {bucket.connections} conn"
						></div>
					{/each}
				</div>
				<div class="sparkline-labels">
					<span class="sparkline-label">24h ago</span>
					<span class="sparkline-label">Now</span>
				</div>
			</div>
		{/if}
	</DrawerSection>
{/if}

<style>
	/* Loading state */
	.loading-row {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-md) 0;
	}

	.loading-text {
		font-size: var(--text-sm);
		color: var(--text-muted);
	}

	/* Empty state */
	.empty-section {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-md) 0;
		color: var(--text-muted);
		font-size: var(--text-sm);
	}

	.empty-icon {
		color: var(--green);
		font-size: var(--text-lg);
	}

	.empty-label {
		color: var(--text-muted);
	}

	/* Alert cards */
	.alert-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.alert-card {
		background: var(--bg-tertiary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-sm);
		padding: var(--space-sm) var(--space-md);
	}

	.alert-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: var(--space-xs);
	}

	.alert-time {
		font-size: var(--text-xs);
		font-family: var(--font-mono);
		color: var(--text-muted);
	}

	.alert-sig {
		font-size: var(--text-sm);
		color: var(--text-primary);
		font-weight: 500;
		margin-bottom: 2px;
	}

	.alert-cat {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	/* History summary spacing */
	.history-summary {
		margin-bottom: var(--space-md);
	}

	/* Sparkline bar chart */
	.sparkline-wrap {
		padding: var(--space-xs) 0;
	}

	.sparkline {
		display: flex;
		align-items: flex-end;
		gap: 1px;
		height: 80px;
		padding: var(--space-xs) 0;
	}

	.spark-bar {
		flex: 1;
		min-width: 0;
		background-color: var(--cyan);
		border-radius: 1px 1px 0 0;
		opacity: 0.8;
		transition: opacity var(--transition-fast);
		cursor: help;
	}

	.spark-bar:hover {
		opacity: 1;
	}

	.sparkline-labels {
		display: flex;
		justify-content: space-between;
		margin-top: var(--space-xs);
	}

	.sparkline-label {
		font-size: var(--text-xs);
		color: var(--text-dim);
	}
</style>
