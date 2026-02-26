<script lang="ts">
	import { getSystemHealth } from '$lib/api/system';

	let activeTab = $state<'general' | 'retention' | 'network' | 'about'>('general');

	let retentionConfig = $state({
		hot_days: 90,
		warm_days: 180,
		cold_days: 30,
		disk_threshold: 80,
		emergency_threshold: 90,
	});

	let saving = $state(false);
	let saveMessage = $state('');
	let version = $state('0.3.0');

	async function saveRetention() {
		saving = true;
		saveMessage = '';
		try {
			const res = await fetch('/api/setup/storage', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					hot_days: retentionConfig.hot_days,
					warm_days: retentionConfig.warm_days,
					cold_days: retentionConfig.cold_days,
					disk_threshold_percent: retentionConfig.disk_threshold,
					emergency_threshold_percent: retentionConfig.emergency_threshold,
				}),
			});
			if (res.ok) {
				saveMessage = 'Retention configuration saved successfully.';
			} else {
				const data = await res.json();
				saveMessage = data.error || 'Failed to save configuration.';
			}
		} catch {
			saveMessage = 'Failed to connect to server.';
		} finally {
			saving = false;
		}
	}

	$effect(() => {
		fetch('/api/setup/storage')
			.then((r) => r.json())
			.then((data) => {
				if (data.retention) {
					retentionConfig.hot_days = data.retention.hot_days ?? 90;
					retentionConfig.warm_days = data.retention.warm_days ?? 180;
					retentionConfig.cold_days = data.retention.cold_days ?? 30;
					retentionConfig.disk_threshold = data.retention.disk_threshold_percent ?? 80;
					retentionConfig.emergency_threshold = data.retention.emergency_threshold_percent ?? 90;
				}
			})
			.catch(() => {});
	});
</script>

<svelte:head>
	<title>Settings | NetTap</title>
</svelte:head>

<div class="settings-page">
	<div class="settings-header">
		<h2>Settings</h2>
		<p class="text-muted">Configure your NetTap appliance.</p>
	</div>

	<div class="settings-tabs">
		<button
			class="tab"
			class:active={activeTab === 'general'}
			onclick={() => (activeTab = 'general')}
		>
			General
		</button>
		<button
			class="tab"
			class:active={activeTab === 'retention'}
			onclick={() => (activeTab = 'retention')}
		>
			Retention
		</button>
		<button
			class="tab"
			class:active={activeTab === 'network'}
			onclick={() => (activeTab = 'network')}
		>
			Network
		</button>
		<button
			class="tab"
			class:active={activeTab === 'about'}
			onclick={() => (activeTab = 'about')}
		>
			About
		</button>
	</div>

	{#if activeTab === 'general'}
		<div class="settings-section">
			<div class="card">
				<div class="card-header">
					<span class="card-title">General Settings</span>
				</div>
				<div class="form-group">
					<label class="label" for="api-port">API Port</label>
					<input class="input" id="api-port" type="number" value={8880} disabled />
					<p class="field-help">The daemon API port. Restart required to change.</p>
				</div>
				<div class="form-group">
					<label class="label" for="log-level">Log Level</label>
					<select class="input" id="log-level">
						<option value="DEBUG">Debug</option>
						<option value="INFO" selected>Info</option>
						<option value="WARNING">Warning</option>
						<option value="ERROR">Error</option>
					</select>
					<p class="field-help">Daemon logging verbosity. Applied on next restart.</p>
				</div>
				<div class="form-group">
					<label class="label" for="check-interval">Storage Check Interval (seconds)</label>
					<input class="input" id="check-interval" type="number" value={300} min={60} max={3600} />
					<p class="field-help">How often the daemon checks disk usage. Default: 300s.</p>
				</div>
			</div>
		</div>
	{:else if activeTab === 'retention'}
		<div class="settings-section">
			<div class="card">
				<div class="card-header">
					<span class="card-title">Data Retention Policy</span>
				</div>

				{#if saveMessage}
					<div class="alert {saveMessage.includes('success') ? 'alert-success' : 'alert-danger'}" style="margin-bottom: var(--space-md);">
						{saveMessage}
					</div>
				{/if}

				<div class="retention-grid">
					<div class="form-group">
						<label class="label" for="hot-days">Hot Tier (Zeek metadata)</label>
						<div class="input-with-unit">
							<input class="input" id="hot-days" type="number" bind:value={retentionConfig.hot_days} min={7} max={365} />
							<span class="input-unit">days</span>
						</div>
						<p class="field-help">Structured metadata logs from Zeek.</p>
					</div>
					<div class="form-group">
						<label class="label" for="warm-days">Warm Tier (Suricata alerts)</label>
						<div class="input-with-unit">
							<input class="input" id="warm-days" type="number" bind:value={retentionConfig.warm_days} min={7} max={730} />
							<span class="input-unit">days</span>
						</div>
						<p class="field-help">IDS alerts and rule matches.</p>
					</div>
					<div class="form-group">
						<label class="label" for="cold-days">Cold Tier (PCAP files)</label>
						<div class="input-with-unit">
							<input class="input" id="cold-days" type="number" bind:value={retentionConfig.cold_days} min={1} max={365} />
							<span class="input-unit">days</span>
						</div>
						<p class="field-help">Raw packet captures (alert-triggered).</p>
					</div>
				</div>

				<div class="threshold-section">
					<div class="form-group">
						<label class="label" for="disk-threshold">Disk Warning Threshold</label>
						<div class="input-with-unit">
							<input class="input" id="disk-threshold" type="number" bind:value={retentionConfig.disk_threshold} min={50} max={95} />
							<span class="input-unit">%</span>
						</div>
						<p class="field-help">Start pruning old data when disk usage exceeds this.</p>
					</div>
					<div class="form-group">
						<label class="label" for="emergency-threshold">Emergency Threshold</label>
						<div class="input-with-unit">
							<input class="input" id="emergency-threshold" type="number" bind:value={retentionConfig.emergency_threshold} min={60} max={99} />
							<span class="input-unit">%</span>
						</div>
						<p class="field-help">Aggressive pruning regardless of tier when disk exceeds this.</p>
					</div>
				</div>

				<button class="btn btn-primary" onclick={saveRetention} disabled={saving}>
					{saving ? 'Saving...' : 'Save Retention Config'}
				</button>
			</div>
		</div>
	{:else if activeTab === 'network'}
		<div class="settings-section">
			<div class="card">
				<div class="card-header">
					<span class="card-title">Network Configuration</span>
				</div>
				<div class="alert alert-info">
					Network interface configuration is managed through the setup wizard. To reconfigure your bridge interfaces, re-run the <a href="/setup">setup wizard</a>.
				</div>
				<div class="form-group" style="margin-top: var(--space-md);">
					<label class="label" for="bridge-iface">Bridge Interface</label>
					<input class="input mono" id="bridge-iface" value="br0" disabled />
				</div>
				<div class="form-group">
					<label class="label" for="mgmt-iface">Management Interface</label>
					<p class="field-help" id="mgmt-iface">The management interface is auto-detected. Access the dashboard via any IP assigned to this appliance on a non-bridge interface.</p>
				</div>
			</div>
		</div>
	{:else if activeTab === 'about'}
		<div class="settings-section">
			<div class="card">
				<div class="card-header">
					<span class="card-title">About NetTap</span>
				</div>
				<div class="about-grid">
					<div class="about-row">
						<span class="about-label">Version</span>
						<span class="about-value mono">{version}</span>
					</div>
					<div class="about-row">
						<span class="about-label">Project</span>
						<span class="about-value">NetTap Network Visibility Appliance</span>
					</div>
					<div class="about-row">
						<span class="about-label">License</span>
						<span class="about-value">Open Source</span>
					</div>
					<div class="about-row">
						<span class="about-label">Stack</span>
						<span class="about-value">Zeek + Suricata + Arkime + OpenSearch</span>
					</div>
					<div class="about-row">
						<span class="about-label">Analysis</span>
						<span class="about-value">TShark (GPL-2.0, containerized) + CyberChef (Apache 2.0)</span>
					</div>
				</div>
			</div>
		</div>
	{/if}
</div>

<style>
	.settings-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.settings-header h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		margin-bottom: var(--space-xs);
	}

	.settings-tabs {
		display: flex;
		gap: 2px;
		border-bottom: 1px solid var(--border-default);
		padding-bottom: 0;
	}

	.tab {
		padding: var(--space-sm) var(--space-md);
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-secondary);
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		cursor: pointer;
		transition: all var(--transition-fast);
		margin-bottom: -1px;
	}

	.tab:hover {
		color: var(--text-primary);
	}

	.tab.active {
		color: var(--accent);
		border-bottom-color: var(--accent);
	}

	.settings-section {
		max-width: 720px;
	}

	.field-help {
		font-size: var(--text-xs);
		color: var(--text-muted);
		margin-top: var(--space-xs);
	}

	.retention-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--space-md);
		margin-bottom: var(--space-lg);
	}

	.threshold-section {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: var(--space-md);
		margin-bottom: var(--space-lg);
	}

	.input-with-unit {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.input-with-unit .input {
		flex: 1;
	}

	.input-unit {
		font-size: var(--text-sm);
		color: var(--text-muted);
		font-weight: 500;
		white-space: nowrap;
	}

	.about-grid {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.about-row {
		display: flex;
		padding: var(--space-sm) 0;
		border-bottom: 1px solid var(--border-muted);
	}

	.about-row:last-child {
		border-bottom: none;
	}

	.about-label {
		width: 120px;
		font-size: var(--text-sm);
		color: var(--text-muted);
		font-weight: 500;
		flex-shrink: 0;
	}

	.about-value {
		font-size: var(--text-sm);
		color: var(--text-primary);
	}

	@media (max-width: 768px) {
		.retention-grid {
			grid-template-columns: 1fr;
		}

		.threshold-section {
			grid-template-columns: 1fr;
		}
	}
</style>
