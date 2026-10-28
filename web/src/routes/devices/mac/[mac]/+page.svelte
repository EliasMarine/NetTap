<script lang="ts">
	/**
	 * Device Detail Page (MAC-based) — Shows comprehensive info for a single
	 * device from the device registry, keyed by MAC address.
	 *
	 * - Device name, IP(s), MAC, manufacturer, category, first/last seen
	 * - Traffic breakdown: top destinations, protocols, bandwidth over time
	 * - DNS queries made by this device
	 * - Suricata alerts for this device
	 */

	import { page } from '$app/stores';
	import { getRegistryDevice, getDeviceTraffic } from '$api/devices-registry';
	import type { RegistryDevice, DeviceTraffic } from '$api/devices-registry';
	import TimeSeriesChart from '$components/charts/TimeSeriesChart.svelte';
	import IPAddress from '$components/IPAddress.svelte';

	let device = $state<RegistryDevice | null>(null);
	let traffic = $state<DeviceTraffic | null>(null);
	let loading = $state(true);
	let error = $state(false);

	let mac = $derived($page.params.mac);

	async function fetchData() {
		if (!mac) return;
		loading = true;
		error = false;
		try {
			const [d, t] = await Promise.allSettled([
				getRegistryDevice(mac),
				getDeviceTraffic(mac),
			]);
			device = d.status === 'fulfilled' ? d.value : null;
			traffic = t.status === 'fulfilled' ? t.value : null;
			if (!device) error = true;
		} catch {
			error = true;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		fetchData();
	});

	function formatBytes(bytes: number): string {
		if (!bytes || bytes <= 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		const value = bytes / Math.pow(1024, i);
		return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[i]}`;
	}

	function formatBytesShort(bytes: number): string {
		if (!bytes || bytes <= 0) return '0';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		const value = bytes / Math.pow(1024, i);
		return `${value.toFixed(value >= 10 ? 0 : 1)}${units[i]}`;
	}

	function severityBadge(severity: number): { label: string; cls: string } {
		switch (severity) {
			case 1: return { label: 'HIGH', cls: 'badge badge-danger' };
			case 2: return { label: 'MEDIUM', cls: 'badge badge-warning' };
			case 3: return { label: 'LOW', cls: 'badge badge-accent' };
			default: return { label: 'INFO', cls: 'badge' };
		}
	}

	function categoryBadgeClass(cat: string): string {
		switch (cat) {
			case 'computer': return 'badge badge-info';
			case 'phone': return 'badge badge-success';
			case 'iot': return 'badge badge-warning';
			case 'infrastructure': return 'badge badge-accent';
			default: return 'badge badge-muted';
		}
	}

	let chartData = $derived(
		traffic?.bandwidth_series?.map((p) => ({
			time: p.timestamp,
			value: p.bytes,
		})) ?? []
	);

	let maxDestBytes = $derived(
		traffic?.top_destinations?.length
			? Math.max(...traffic.top_destinations.map((d) => d.bytes))
			: 1
	);
</script>

<svelte:head>
	<title>{device?.display_name || mac} | NetTap</title>
</svelte:head>

<div class="device-detail-page">
	<!-- Back link -->
	<a href="/devices" class="back-link">
		<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
			<polyline points="15 18 9 12 15 6" />
		</svg>
		Back to Devices
	</a>

	{#if loading && !device}
		<div class="loading-state">
			<div class="spinner"></div>
			<p class="text-muted">Loading device details...</p>
		</div>
	{:else if error || !device}
		<div class="empty-state">
			<p class="empty-text">Device not found</p>
			<p class="empty-hint">The device with MAC address {mac} could not be found in the registry.</p>
		</div>
	{:else}
		<!-- Device header -->
		<div class="device-header">
			<div class="header-info">
				<h2>{device.display_name || device.mac}</h2>
				<div class="header-badges">
					<span class={categoryBadgeClass(device.category)}>
						{device.category || 'unknown'}
					</span>
					{#if device.is_new}
						<span class="badge badge-info">New</span>
					{/if}
				</div>
			</div>
			<button class="btn btn-secondary btn-sm" onclick={fetchData} disabled={loading}>
				Refresh
			</button>
		</div>

		<!-- Info cards row -->
		<div class="grid grid-cols-2 info-row-grid">
			<!-- Identity card -->
			<div class="card">
				<div class="card-header">
					<span class="card-title">Identity</span>
				</div>
				<div class="info-grid">
					<div class="info-row">
						<span class="info-label">MAC Address</span>
						<span class="info-value mono">{device.mac}</span>
					</div>
					<div class="info-row">
						<span class="info-label">IP Address(es)</span>
						<span class="info-value mono">
							{#if device.ips.length > 0}
								{device.ips.join(', ')}
							{:else}
								--
							{/if}
						</span>
					</div>
					{#if device.manufacturer}
						<div class="info-row">
							<span class="info-label">Manufacturer</span>
							<span class="info-value">{device.manufacturer}</span>
						</div>
					{/if}
					{#if device.friendly_name}
						<div class="info-row">
							<span class="info-label">Friendly Name</span>
							<span class="info-value">{device.friendly_name}</span>
						</div>
					{/if}
					{#if device.hostnames.length > 0}
						<div class="info-row">
							<span class="info-label">Hostnames</span>
							<span class="info-value mono">{device.hostnames.join(', ')}</span>
						</div>
					{/if}
				</div>
			</div>

			<!-- Activity card -->
			<div class="card">
				<div class="card-header">
					<span class="card-title">Activity</span>
				</div>
				<div class="info-grid">
					<div class="info-row">
						<span class="info-label">First Seen</span>
						<span class="info-value mono">
							{device.first_seen ? new Date(device.first_seen).toLocaleString() : '--'}
						</span>
					</div>
					<div class="info-row">
						<span class="info-label">Last Seen</span>
						<span class="info-value mono">
							{device.last_seen ? new Date(device.last_seen).toLocaleString() : '--'}
						</span>
					</div>
					{#if traffic}
						<div class="info-row">
							<span class="info-label">Total Traffic</span>
							<span class="info-value mono">{formatBytes(traffic.total_bytes)}</span>
						</div>
						<div class="info-row">
							<span class="info-label">Inbound / Outbound</span>
							<span class="info-value mono">
								{formatBytesShort(traffic.inbound_bytes)} in / {formatBytesShort(traffic.outbound_bytes)} out
							</span>
						</div>
						<div class="info-row">
							<span class="info-label">Connections</span>
							<span class="info-value mono">{traffic.connection_count.toLocaleString()}</span>
						</div>
					{/if}
				</div>
			</div>
		</div>

		<!-- Bandwidth chart -->
		{#if chartData.length > 0}
			<div class="card chart-card">
				<div class="card-header">
					<span class="card-title">Bandwidth Over Time</span>
				</div>
				<TimeSeriesChart
					data={chartData}
					height={220}
					color="var(--accent)"
					label="Bytes"
					formatValue={formatBytesShort}
				/>
			</div>
		{/if}

		<!-- Bottom row: Destinations + DNS + Alerts -->
		<div class="grid grid-cols-2 tables-grid">
			<!-- Top Destinations -->
			{#if traffic?.top_destinations?.length}
				<div class="card table-card">
					<div class="card-header">
						<span class="card-title">Top Destinations</span>
					</div>
					<div class="dest-bars">
						{#each traffic.top_destinations.slice(0, 8) as dest, i}
							<div class="dest-row">
								<span class="dest-rank">{i + 1}</span>
								<span class="dest-ip mono"><IPAddress ip={dest.ip} /></span>
								<div class="dest-bar-track">
									<div
										class="dest-bar-fill"
										style="width: {(dest.bytes / maxDestBytes) * 100}%;"
									></div>
								</div>
								<span class="dest-value mono">{formatBytesShort(dest.bytes)}</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- DNS Queries -->
			{#if traffic?.dns_queries?.length}
				<div class="card table-card">
					<div class="card-header">
						<span class="card-title">DNS Queries</span>
					</div>
					<div class="table-scroll">
						<table class="data-table">
							<thead>
								<tr>
									<th>Domain</th>
									<th>Count</th>
								</tr>
							</thead>
							<tbody>
								{#each traffic.dns_queries.slice(0, 15) as query}
									<tr>
										<td class="mono">{query.domain}</td>
										<td class="mono">{query.count.toLocaleString()}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			{/if}
		</div>

		<!-- Alerts for this device -->
		{#if traffic?.alerts?.length}
			<div class="card table-card">
				<div class="card-header">
					<span class="card-title">Alerts</span>
					<span class="card-subtitle">{traffic.alerts.length} alert{traffic.alerts.length !== 1 ? 's' : ''}</span>
				</div>
				<div class="table-scroll">
					<table class="data-table">
						<thead>
							<tr>
								<th>Severity</th>
								<th>Signature</th>
								<th>Time</th>
							</tr>
						</thead>
						<tbody>
							{#each traffic.alerts.slice(0, 20) as alert}
								{@const sev = severityBadge(alert.severity)}
								<tr>
									<td><span class={sev.cls}>{sev.label}</span></td>
									<td class="signature-cell">{alert.signature}</td>
									<td class="mono">{new Date(alert.timestamp).toLocaleString()}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}

		<!-- Protocols -->
		{#if traffic?.top_protocols?.length}
			<div class="card">
				<div class="card-header">
					<span class="card-title">Protocols</span>
				</div>
				<div class="protocol-pills">
					{#each traffic.top_protocols as proto}
						<span class="pill">{proto.name} <span class="mono">{proto.count.toLocaleString()}</span></span>
					{/each}
				</div>
			</div>
		{/if}
	{/if}
</div>

<style>
	.device-detail-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.back-link {
		display: inline-flex;
		align-items: center;
		gap: var(--space-xs);
		font-size: var(--text-sm);
		color: var(--text-muted);
		text-decoration: none;
	}

	.back-link:hover {
		color: var(--accent);
	}

	.device-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-md);
	}

	.header-info h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		margin-bottom: var(--space-xs);
	}

	.header-badges {
		display: flex;
		gap: var(--space-sm);
	}

	.info-grid {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.info-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-xs) 0;
		border-bottom: 1px solid var(--border-muted);
	}

	.info-row:last-child {
		border-bottom: none;
	}

	.info-label {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	.info-value {
		font-size: var(--text-sm);
		color: var(--text-primary);
		font-weight: 500;
		text-align: right;
	}

	.chart-card {
		min-height: 300px;
	}

	.table-card {
		min-height: 200px;
	}

	.table-scroll {
		overflow-x: auto;
	}

	.signature-cell {
		max-width: 300px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* Destination bars */
	.dest-bars {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.dest-row {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xs) 0;
	}

	.dest-rank {
		flex-shrink: 0;
		width: 20px;
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-align: right;
	}

	.dest-ip {
		flex-shrink: 0;
		width: 120px;
		font-size: var(--text-xs);
	}

	.dest-bar-track {
		flex: 1;
		height: 16px;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.dest-bar-fill {
		height: 100%;
		border-radius: var(--radius-sm);
		background: linear-gradient(90deg, var(--cyan), var(--blue));
		transition: width 0.4s ease-out;
		min-width: 2px;
	}

	.dest-value {
		flex-shrink: 0;
		width: 60px;
		font-size: var(--text-xs);
		text-align: right;
	}

	/* Protocol pills */
	.protocol-pills {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-sm);
	}

	/* Loading/empty */
	.loading-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: var(--space-3xl);
		gap: var(--space-md);
	}

	.spinner {
		width: 32px;
		height: 32px;
		border: 3px solid var(--border-default);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	@media (max-width: 768px) {
		.device-header {
			flex-direction: column;
		}
	}
</style>
