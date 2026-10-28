<script lang="ts">
	import { getIoTDevices, getIoTAnomalies, getDeviceBaseline } from '$lib/api/iot';
	import { getLanAnomalies } from '$lib/api/lan-security';
	import type { IoTDevice, IoTAnomaly, DeviceBaseline } from '$lib/api/iot';
	import type { LanAnomaly } from '$lib/api/lan-security';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let devices = $state<IoTDevice[]>([]);
	let anomalies = $state<IoTAnomaly[]>([]);
	let lanAnomalies = $state<LanAnomaly[]>([]);
	let selectedDevice = $state<IoTDevice | null>(null);
	let selectedBaseline = $state<DeviceBaseline | null>(null);
	let loading = $state(false);
	let error = $state('');
	let baselineLoading = $state(false);

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function severityColor(severity: string): string {
		switch (severity) {
			case 'critical': return 'var(--danger)';
			case 'high': return 'var(--danger)';
			case 'medium': return 'var(--warning)';
			default: return 'var(--text-muted)';
		}
	}

	function anomalyIcon(type: string): string {
		switch (type) {
			case 'NEW_DESTINATION': return 'globe';
			case 'NEW_COUNTRY': return 'map';
			case 'NEW_PORT': return 'server';
			case 'UNUSUAL_TIME': return 'clock';
			case 'VOLUME_SPIKE': return 'trending-up';
			case 'PROTOCOL_CHANGE': return 'shuffle';
			case 'arp_spoofing': return 'shield-off';
			case 'rogue_dhcp': return 'alert-triangle';
			case 'ip_conflict': return 'alert-circle';
			default: return 'alert';
		}
	}

	function formatBytes(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
		return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
	}

	function formatTime(iso: string): string {
		try {
			return new Date(iso).toLocaleString();
		} catch {
			return iso;
		}
	}

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchAll() {
		loading = true;
		error = '';
		try {
			const now = new Date();
			const from = new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString();
			const to = now.toISOString();

			const [devData, anomData, lanData] = await Promise.all([
				getIoTDevices(),
				getIoTAnomalies({ from, to }),
				getLanAnomalies({ from, to }),
			]);

			devices = devData.devices;
			anomalies = anomData.anomalies;
			lanAnomalies = lanData.anomalies;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to fetch IoT data';
		} finally {
			loading = false;
		}
	}

	async function selectDevice(device: IoTDevice) {
		selectedDevice = device;
		baselineLoading = true;
		try {
			const result = await getDeviceBaseline(device.mac);
			selectedBaseline = result.baseline;
		} catch {
			selectedBaseline = null;
		} finally {
			baselineLoading = false;
		}
	}

	$effect(() => {
		fetchAll();
	});
</script>

<svelte:head>
	<title>IoT Monitor | NetTap</title>
</svelte:head>

<div class="iot-page">
	<!-- Header -->
	<div class="page-header">
		<div class="header-left">
			<h2>IoT & LAN Security</h2>
			<p class="text-muted">IoT device monitoring, behavioral baselines, and LAN anomalies</p>
		</div>
		<div class="header-actions">
			<button class="btn btn-primary btn-sm" onclick={fetchAll} disabled={loading}>
				{loading ? 'Loading...' : 'Refresh'}
			</button>
		</div>
	</div>

	{#if error}
		<div class="alert alert-danger">{error}</div>
	{/if}

	{#if loading && devices.length === 0}
		<div class="loading-state">
			<div class="spinner"></div>
			<p class="text-muted">Loading IoT data...</p>
		</div>
	{:else}
		<!-- Stats summary -->
		<div class="stats-grid">
			<div class="stat-card">
				<span class="stat-label">IoT Devices</span>
				<span class="stat-value">{devices.length}</span>
			</div>
			<div class="stat-card" class:alert-stat={anomalies.length > 0}>
				<span class="stat-label">IoT Anomalies</span>
				<span class="stat-value">{anomalies.length}</span>
			</div>
			<div class="stat-card" class:alert-stat={lanAnomalies.length > 0}>
				<span class="stat-label">LAN Anomalies</span>
				<span class="stat-value">{lanAnomalies.length}</span>
			</div>
		</div>

		<!-- IoT device grid -->
		{#if devices.length > 0}
			<div class="card">
				<h3 class="card-title">IoT Devices</h3>
				<div class="device-grid">
					{#each devices as device}
						<button
							class="device-card"
							class:selected={selectedDevice?.mac === device.mac}
							onclick={() => selectDevice(device)}
						>
							<div class="device-name">{device.manufacturer || 'Unknown'}</div>
							<div class="device-mac mono">{device.mac}</div>
							{#if device.ip}
								<div class="device-ip mono">{device.ip}</div>
							{/if}
							{#if device.hostname}
								<div class="device-hostname">{device.hostname}</div>
							{/if}
						</button>
					{/each}
				</div>
			</div>
		{:else}
			<div class="card empty-state">
				<p class="text-muted">No IoT devices classified yet. Devices are automatically classified based on manufacturer (Ring, Nest, Wyze, etc.)</p>
			</div>
		{/if}

		<!-- Selected device baseline -->
		{#if selectedDevice}
			<div class="card">
				<h3 class="card-title">Baseline: {selectedDevice.manufacturer} ({selectedDevice.mac})</h3>
				{#if baselineLoading}
					<div class="loading-state small">
						<div class="spinner"></div>
					</div>
				{:else if selectedBaseline}
					<div class="baseline-grid">
						<div class="baseline-section">
							<h4>Known Destinations</h4>
							<div class="tag-list">
								{#each selectedBaseline.known_destinations.slice(0, 20) as dest}
									<span class="tag mono">{dest}</span>
								{/each}
								{#if selectedBaseline.known_destinations.length > 20}
									<span class="tag-more">+{selectedBaseline.known_destinations.length - 20} more</span>
								{/if}
							</div>
						</div>
						<div class="baseline-section">
							<h4>Known Ports</h4>
							<div class="tag-list">
								{#each selectedBaseline.known_ports as port}
									<span class="tag mono">{port}</span>
								{/each}
							</div>
						</div>
						<div class="baseline-section">
							<h4>Known Countries</h4>
							<div class="tag-list">
								{#each selectedBaseline.known_countries as country}
									<span class="tag">{country}</span>
								{/each}
							</div>
						</div>
						<div class="baseline-section">
							<h4>Stats</h4>
							<p class="mono">Daily avg: {formatBytes(selectedBaseline.daily_avg_bytes)}</p>
							<p class="mono">Connections: {selectedBaseline.connection_count.toLocaleString()}</p>
						</div>
					</div>
				{:else}
					<p class="text-muted" style="padding: var(--space-md) var(--space-lg);">No baseline available yet. Baselines are built from 14 days of traffic history.</p>
				{/if}
			</div>
		{/if}

		<!-- Anomaly feed -->
		{#if anomalies.length > 0 || lanAnomalies.length > 0}
			<div class="card">
				<h3 class="card-title">Anomaly Feed</h3>
				<div class="anomaly-list">
					{#each [...anomalies, ...lanAnomalies] as anomaly}
						<div class="anomaly-item">
							<span class="severity-dot" style="background: {severityColor(anomaly.severity)}"></span>
							<div class="anomaly-content">
								<div class="anomaly-header">
									<span class="anomaly-type">{anomaly.type.replace(/_/g, ' ')}</span>
									<span class="anomaly-time text-muted">{formatTime(anomaly.detected_at)}</span>
								</div>
								<p class="anomaly-desc">{anomaly.description}</p>
							</div>
						</div>
					{/each}
				</div>
			</div>
		{/if}
	{/if}
</div>

<style>
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

	.header-left h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		margin-bottom: var(--space-xs);
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	/* Stats grid */
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
		gap: var(--space-md);
	}

	.stat-card.alert-stat {
		border-color: var(--warning);
	}

	/* Card */
	.card-title {
		font-size: var(--text-lg);
		font-weight: 600;
		padding: var(--space-md) var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
	}

	.empty-state {
		padding: var(--space-xl);
		text-align: center;
	}

	/* Device grid */
	.device-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
		gap: var(--space-md);
		padding: var(--space-md) var(--space-lg);
	}

	.device-card {
		background: var(--bg-tertiary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-md);
		padding: var(--space-md);
		cursor: pointer;
		text-align: left;
		transition: border-color var(--transition-fast);
	}

	.device-card:hover {
		border-color: var(--accent);
	}

	.device-card.selected {
		border-color: var(--accent);
		background: var(--bg-secondary);
	}

	.device-name {
		font-weight: 600;
		margin-bottom: var(--space-xs);
	}

	.device-mac, .device-ip, .device-hostname {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	/* Baseline */
	.baseline-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
		gap: var(--space-md);
		padding: var(--space-md) var(--space-lg);
	}

	.baseline-section h4 {
		font-size: var(--text-sm);
		font-weight: 600;
		margin-bottom: var(--space-sm);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.tag-list {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
	}

	.tag {
		padding: var(--space-xs) var(--space-sm);
		background: var(--bg-tertiary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
	}

	.tag-more {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	/* Anomaly feed */
	.anomaly-list {
		display: flex;
		flex-direction: column;
	}

	.anomaly-item {
		display: flex;
		gap: var(--space-md);
		padding: var(--space-md) var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
	}

	.anomaly-item:last-child {
		border-bottom: none;
	}

	.severity-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		margin-top: 6px;
		flex-shrink: 0;
	}

	.anomaly-content { flex: 1; }

	.anomaly-header {
		display: flex;
		justify-content: space-between;
		gap: var(--space-sm);
		margin-bottom: var(--space-xs);
	}

	.anomaly-type {
		font-weight: 600;
		text-transform: capitalize;
	}

	.anomaly-time {
		font-size: var(--text-xs);
		white-space: nowrap;
	}

	.anomaly-desc {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	/* Loading */
	.loading-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: var(--space-3xl);
		gap: var(--space-md);
	}

	.loading-state.small {
		padding: var(--space-lg);
	}

	.spinner {
		width: 32px;
		height: 32px;
		border: 3px solid var(--border-default);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin { to { transform: rotate(360deg); } }

	@media (max-width: 768px) {
		.page-header { flex-direction: column; }
		.device-grid { grid-template-columns: repeat(2, 1fr); }
	}
</style>
