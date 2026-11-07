<!--
  LiveConnectionDrawerContent.svelte — Drawer content for a live connection.
  Two tabs:
    1. "details" — Connection info (source/dest, protocol, bytes, duration) + GeoIP enrichment
    2. "alerts"  — Related Suricata alerts + 24h history sparkline
  Uses DrawerSection + KVRow for consistent styling with other drawer content.
-->
<script lang="ts">
	import type { LiveConnection, ConnectionDetailResponse } from '$lib/api/live';
	import { directionLabel } from '$lib/api/live';
	import { formatBytes } from '$lib/api/logs';
	import DrawerSection from '../DrawerSection.svelte';
	import KVRow from '../KVRow.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import { suricataLevel } from '$lib/utils/severity';
	import Icon from '$lib/components/ui/Icon.svelte';
	// OLD CODE: import { alertsHrefForSignature } from '$lib/utils/drilldown'; (slice 2b-2)
	import { alertsHrefForSignature, suricataCategoryHref } from '$lib/utils/drilldown';

	// ---------------------------------------------------------------------------
	// Props
	// ---------------------------------------------------------------------------

	let {
		connection,
		detail = null,
		detailLoading = false,
		detailFailed = false,
		activeTab,
	}: {
		connection: LiveConnection;
		detail: ConnectionDetailResponse | null;
		detailLoading: boolean;
		/** #96: the detail request failed, so "no alerts" / "no history" would be false */
		detailFailed?: boolean;
		activeTab: string;
	} = $props();

	// ---------------------------------------------------------------------------
	// Format helpers
	// ---------------------------------------------------------------------------

	// OLD CODE START — 2026-11-06 (O11): 1000-based, while the rest of NetTap divides by 1024
	// function formatBytes(bytes: number): string {
	// 	if (bytes >= 1_000_000_000) return (bytes / 1_000_000_000).toFixed(1) + ' GB';
	// 	if (bytes >= 1_000_000) return (bytes / 1_000_000).toFixed(1) + ' MB';
	// 	if (bytes >= 1_000) return (bytes / 1_000).toFixed(1) + ' KB';
	// 	return bytes + ' B';
	// }
	// OLD CODE END

	function formatDuration(seconds: number): string {
		if (seconds < 0.001) return '<1ms';
		if (seconds < 1) return (seconds * 1000).toFixed(0) + 'ms';
		if (seconds < 60) return seconds.toFixed(1) + 's';
		// OLD CODE START — split before rounding, so 30 min 59.6 s read "30m 60s" and 1 h 59.6 min "1h 60m"
		// if (seconds < 3600) {
		// 	const m = Math.floor(seconds / 60);
		// 	const s = Math.round(seconds % 60);
		// 	return `${m}m ${s}s`;
		// }
		// const h = Math.floor(seconds / 3600);
		// const m = Math.round((seconds % 3600) / 60);
		// return `${h}h ${m}m`;
		// OLD CODE END
		const total = Math.round(seconds);
		if (total < 3600) return `${Math.floor(total / 60)}m ${total % 60}s`;
		const totalMin = Math.round(seconds / 60);
		return `${Math.floor(totalMin / 60)}h ${totalMin % 60}m`;
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

	// Unused since the restyle: the design system allows no emoji, so the Country row no longer shows a flag.
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

	// OLD CODE START — 2026-11-06 (O2): guessed from the port; the daemon's direction is shared
	// with the feed's Dir column (directionLabel in $lib/api/live)
	// function directionLabel(): string {
	// 	return connection.dest_port < 1024 ? 'Outbound' : 'Inbound';
	// }
	// OLD CODE END

	// OLD CODE START — 2026-11-03: the badge is the shared SeverityPill, which takes the level and
	// prints the word itself, so neither the label nor the class is needed here
	// function severityLabel(sev: number): string {
	// 	switch (sev) {
	// 		case 1: return 'High';
	// 		case 2: return 'Medium';
	// 		case 3: return 'Low';
	// 		default: return 'Info';
	// 	}
	// }
	//
	// function severityClass(sev: number): string {
	// 	switch (sev) {
	// 		case 1: return 'sev-high';
	// 		case 2: return 'sev-medium';
	// 		case 3: return 'sev-low';
	// 		default: return 'sev-info';
	// 	}
	// }
	// OLD CODE END
	// OLD CODE START — the same mapping now lives once in $lib/utils/severity (NET-146)
	// function severityLevel(sev: number): SeverityLevel {
	// 	switch (sev) {
	// 		case 1: return 'high';
	// 		case 2: return 'medium';
	// 		case 3: return 'low';
	// 		default: return 'info';
	// 	}
	// }
	// OLD CODE END
	const severityLevel = suricataLevel;

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
<!-- DETAILS TAB                                                            -->
<!-- ======================================================================= -->
{#if activeTab === 'details'}
	<DrawerSection title="Connection info">
		<KVRow label="Source IP" value={`${connection.source_ip}:${connection.source_port}`} mono copyable />
		<KVRow label="Destination IP" value={`${connection.dest_ip}:${connection.dest_port}`} mono copyable />
		<KVRow label="Protocol" value={String(connection.service || connection.protocol || '').toUpperCase()} />
		<KVRow label="Direction" value={directionLabel(connection)} />
		<KVRow label="Bytes" value={formatBytes(connection.bytes)} mono />
		<KVRow label="Duration" value={formatDuration(connection.duration)} mono />
		<KVRow label="Device" value={connection.device_name || '--'} />
		<KVRow label="Timestamp" value={formatTimestamp(connection.timestamp)} mono />
	</DrawerSection>

	<DrawerSection title="GeoIP information">
		{#if detailLoading}
			<div class="loading-row">
				<span class="loading-spinner"></span>
				<span class="loading-text">Loading GeoIP data…</span>
			</div>
		{:else}
			<!-- OLD CODE START — no emoji in the design system, so the flag prefix is dropped:
			<KVRow label="Country" value={geoCountryCode ? `${countryFlag(geoCountryCode)} ${geoCountry}` : geoCountry} />
			OLD CODE END -->
			<KVRow label="Country" value={geoCountry} />
			<KVRow label="City" value={geoCity} />
			<KVRow label="Coordinates" value={formatCoordinates(geoLat, geoLon)} mono />
			<KVRow label="ASN" value={geoAsn != null ? `AS${geoAsn}` : null} mono />
			<KVRow label="Organisation" value={geoOrg} />
		{/if}
	</DrawerSection>

<!-- ======================================================================= -->
<!-- ALERTS TAB                                                              -->
<!-- ======================================================================= -->
{:else if activeTab === 'alerts'}
	<DrawerSection title="Related Suricata alerts">
		{#if detailLoading}
			<div class="loading-row">
				<span class="loading-spinner"></span>
				<span class="loading-text">Loading alerts…</span>
			</div>
		{:else if detailFailed}
			<div class="empty-section">
				<span class="empty-label">Couldn't load alerts for this connection: the request failed.</span>
			</div>
		{:else if !detail?.alerts?.length}
			<div class="empty-section">
				<span class="empty-icon"><Icon name="check" /></span>
				<span class="empty-label">No alerts for this connection</span>
			</div>
		{:else}
			<div class="alert-list">
				{#each detail.alerts as alert}
					<div class="alert-card">
						<div class="alert-header">
							<SeverityPill level={severityLevel(alert.severity)} />
							<span class="alert-time">{formatTimestamp(alert.timestamp)}</span>
						</div>
						<!-- OLD CODE: <div class="alert-sig">{alert.signature}</div> (slice 2a: not a link) -->
						<div class="alert-sig">{#if alert.signature}<a href={alertsHrefForSignature(alert.signature)}>{alert.signature}</a>{/if}</div>
						<!-- OLD CODE: <div class="alert-cat">{alert.category}</div> (slice 2b-2: links when rule.category holds it, so its page lists this alert) -->
						<div class="alert-cat">{#if alert.category && alert.rule_category?.includes(alert.category)}<a href={suricataCategoryHref(alert.category)}>{alert.category}</a>{:else}{alert.category}{/if}</div>
					</div>
				{/each}
			</div>
		{/if}
	</DrawerSection>

	<DrawerSection title="24h history">
		{#if detailLoading}
			<div class="loading-row">
				<span class="loading-spinner"></span>
				<span class="loading-text">Loading history…</span>
			</div>
		{:else if detailFailed}
			<div class="empty-section">
				<span class="empty-label">Couldn't load history for this connection: the request failed.</span>
			</div>
		{:else if !detail?.history?.timeline?.length}
			<div class="empty-section">
				<span class="empty-label">No history data available</span>
			</div>
		{:else}
			<div class="history-summary">
				<KVRow label="Total bytes (24h)" value={formatBytes(detail.history.total_bytes)} mono />
				<KVRow label="Connections (24h)" value={String(detail.history.connection_count)} mono />
			</div>

			<div class="sparkline-wrap">
				<div class="sparkline" role="img" aria-label="Bytes per interval over the last 24 hours">
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
		gap: var(--sp-2);
		padding: var(--sp-4) 0;
	}

	.loading-spinner {
		width: 16px;
		height: 16px;
		flex: none;
		border: 2px solid var(--line);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	.loading-text {
		font-size: var(--text-sm);
		color: var(--text-3);
	}

	/* Empty state */
	.empty-section {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		padding: var(--sp-4) 0;
		color: var(--text-3);
		font-size: var(--text-sm);
	}

	.empty-icon {
		display: inline-flex;
		color: var(--ok);
	}

	.empty-label {
		color: var(--text-3);
	}

	/* Alert cards */
	.alert-list {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}

	.alert-card {
		background: var(--surface-2);
		border: 1px solid var(--line);
		border-radius: var(--r-md);
		padding: var(--sp-3) var(--sp-4);
	}

	.alert-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: var(--sp-1);
	}

	.alert-time {
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.alert-sig {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		color: var(--text-1);
		overflow-wrap: anywhere;
		margin-bottom: 2px;
	}

	.alert-cat {
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	/* History summary spacing */
	.history-summary {
		margin-bottom: var(--sp-4);
	}

	/* Sparkline bar chart */
	.sparkline-wrap {
		padding: var(--sp-1) 0;
	}

	.sparkline {
		display: flex;
		align-items: flex-end;
		gap: 1px;
		height: 80px;
		padding: var(--sp-1) 0;
	}

	.spark-bar {
		flex: 1;
		min-width: 0;
		background-color: var(--accent);
		border-radius: 1px 1px 0 0;
		opacity: 0.8;
		transition: opacity var(--dur-fast);
		cursor: help;
	}

	.spark-bar:hover {
		opacity: 1;
	}

	.sparkline-labels {
		display: flex;
		justify-content: space-between;
		margin-top: var(--sp-1);
	}

	.sparkline-label {
		font-size: var(--text-xs);
		color: var(--text-3);
	}
</style>
