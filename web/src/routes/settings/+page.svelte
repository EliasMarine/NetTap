<script lang="ts">
	import { onMount } from 'svelte';

	type TabId = 'notifications' | 'retention' | 'display' | 'about';

	let activeTab = $state<TabId>('notifications');

	// --- Notifications state ---
	let severityThreshold = $state<string>('medium');
	let emailEnabled = $state(false);
	let emailAddress = $state('');
	let webhookUrl = $state('');
	let notifSaving = $state(false);
	let notifMessage = $state('');
	let notifError = $state(false);
	let testingSending = $state(false);
	let testMessage = $state('');
	let testError = $state(false);

	// --- Retention state ---
	let retentionConfig = $state({
		hot_days: 90,
		warm_days: 180,
		cold_days: 30,
		disk_threshold: 80,
		emergency_threshold: 90,
	});
	let diskUsage = $state<number | null>(null);
	let retentionSaving = $state(false);
	let retentionMessage = $state('');
	let retentionError = $state(false);

	// --- Display state ---
	let autoRefresh = $state('30');
	let timezone = $state('local');
	let defaultTimeRange = $state('1h');
	let displaySaving = $state(false);
	let displayMessage = $state('');

	// --- About state ---
	let version = $state('...');
	let uptime = $state('...');
	let buildInfo = $state('...');

	async function loadNotificationConfig() {
		try {
			const res = await fetch('/api/notifications/config');
			if (res.ok) {
				const data = await res.json();
				severityThreshold = data.severityThreshold ?? 'medium';
				emailEnabled = data.email?.enabled ?? false;
				emailAddress = data.email?.recipients?.[0] ?? '';
				webhookUrl = data.webhook?.url ?? '';
			}
		} catch {
			// Will use defaults
		}
	}

	async function loadRetention() {
		try {
			const res = await fetch('/api/setup/storage');
			if (res.ok) {
				const data = await res.json();
				if (data.retention) {
					retentionConfig.hot_days = data.retention.hot_days ?? 90;
					retentionConfig.warm_days = data.retention.warm_days ?? 180;
					retentionConfig.cold_days = data.retention.cold_days ?? 30;
					retentionConfig.disk_threshold = data.retention.disk_threshold_percent ?? 80;
					retentionConfig.emergency_threshold = data.retention.emergency_threshold_percent ?? 90;
				}
			}
		} catch {
			// Will use defaults
		}
	}

	async function loadDiskUsage() {
		try {
			const res = await fetch('/api/storage/status');
			if (res.ok) {
				const data = await res.json();
				diskUsage = data.disk_usage_percent ?? data.usage_percent ?? null;
			}
		} catch {
			// Will stay null
		}
	}

	async function loadAbout() {
		try {
			const [healthRes, versionsRes] = await Promise.all([
				fetch('/api/system/health'),
				fetch('/api/system/versions'),
			]);
			if (healthRes.ok) {
				const data = await healthRes.json();
				uptime = data.uptime ?? 'Unknown';
			}
			if (versionsRes.ok) {
				const data = await versionsRes.json();
				version = data.nettap ?? data.version ?? '0.3.0';
				buildInfo = data.build ?? data.commit ?? 'Development build';
			}
		} catch {
			// Will use defaults
		}
	}

	async function loadDisplaySettings() {
		try {
			const stored = localStorage.getItem('nettap-display-settings');
			if (stored) {
				const parsed = JSON.parse(stored);
				autoRefresh = parsed.autoRefresh ?? '30';
				timezone = parsed.timezone ?? 'local';
				defaultTimeRange = parsed.defaultTimeRange ?? '1h';
			}
		} catch {
			// Will use defaults
		}
	}

	onMount(() => {
		loadNotificationConfig();
		loadRetention();
		loadDiskUsage();
		loadAbout();
		loadDisplaySettings();
	});

	async function saveNotifications() {
		notifSaving = true;
		notifMessage = '';
		notifError = false;
		try {
			const res = await fetch('/api/notifications/config', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					severityThreshold,
					email: {
						enabled: emailEnabled,
						recipients: emailAddress ? [emailAddress] : [],
					},
					webhook: {
						url: webhookUrl || null,
					},
				}),
			});
			if (res.ok) {
				notifMessage = 'Notification settings saved successfully.';
			} else {
				const data = await res.json();
				notifMessage = data.error || 'Failed to save notification settings.';
				notifError = true;
			}
		} catch {
			notifMessage = 'Failed to connect to server.';
			notifError = true;
		} finally {
			notifSaving = false;
		}
	}

	async function sendTestNotification() {
		testingSending = true;
		testMessage = '';
		testError = false;
		try {
			const res = await fetch('/api/notifications/test', { method: 'POST' });
			const data = await res.json();
			if (res.ok) {
				testMessage = 'Test notification sent successfully.';
			} else {
				testMessage = data.error || 'Failed to send test notification.';
				testError = true;
			}
		} catch {
			testMessage = 'Failed to connect to server.';
			testError = true;
		} finally {
			testingSending = false;
		}
	}

	async function saveRetention() {
		retentionSaving = true;
		retentionMessage = '';
		retentionError = false;
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
				retentionMessage = 'Retention configuration saved successfully.';
			} else {
				const data = await res.json();
				retentionMessage = data.error || 'Failed to save configuration.';
				retentionError = true;
			}
		} catch {
			retentionMessage = 'Failed to connect to server.';
			retentionError = true;
		} finally {
			retentionSaving = false;
		}
	}

	function saveDisplay() {
		displaySaving = true;
		displayMessage = '';
		try {
			localStorage.setItem(
				'nettap-display-settings',
				JSON.stringify({ autoRefresh, timezone, defaultTimeRange })
			);
			displayMessage = 'Display settings saved.';
		} catch {
			displayMessage = 'Failed to save display settings.';
		} finally {
			displaySaving = false;
		}
	}

	const severityOptions: { value: string; label: string }[] = [
		{ value: 'critical', label: 'Critical only' },
		{ value: 'high', label: 'High and above' },
		{ value: 'medium', label: 'Medium and above' },
		{ value: 'low', label: 'All severities' },
	];
</script>

<svelte:head>
	<title>Settings | NetTap</title>
</svelte:head>

<div class="settings-page">
	<div class="page-header">
		<div>
			<h2 class="page-title">Settings</h2>
			<p class="text-muted">Configure your NetTap appliance.</p>
		</div>
	</div>

	<div class="tabs">
		<button
			class="tab"
			class:active={activeTab === 'notifications'}
			onclick={() => (activeTab = 'notifications')}
		>
			Notifications
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
			class:active={activeTab === 'display'}
			onclick={() => (activeTab = 'display')}
		>
			Display
		</button>
		<button
			class="tab"
			class:active={activeTab === 'about'}
			onclick={() => (activeTab = 'about')}
		>
			About
		</button>
	</div>

	{#if activeTab === 'notifications'}
		<div class="settings-section">
			<div class="card">
				<div class="card-header">
					<span class="card-title">Notification Preferences</span>
				</div>

				{#if notifMessage}
					<div class="alert {notifError ? 'alert-danger' : 'alert-success'}" style="margin-bottom: var(--space-md);">
						{notifMessage}
					</div>
				{/if}

				<div class="form-group">
					<label class="label" for="severity-threshold">Alert Severity Threshold</label>
					<select class="select" id="severity-threshold" bind:value={severityThreshold}>
						{#each severityOptions as opt}
							<option value={opt.value}>{opt.label}</option>
						{/each}
					</select>
					<p class="field-help">Only notify for alerts at or above this severity level.</p>
				</div>

				<div class="form-group">
					<label class="label">Email Notifications</label>
					<div class="toggle-row">
						<label class="toggle-label" for="email-toggle">
							<div class="toggle-text">
								<span class="toggle-title">Enable email alerts</span>
								<span class="toggle-description">Send alert notifications to the email address below. Requires SMTP to be configured in API Keys.</span>
							</div>
							<div class="toggle-switch">
								<input
									type="checkbox"
									id="email-toggle"
									class="toggle-input"
									bind:checked={emailEnabled}
								/>
								<span class="toggle-slider"></span>
							</div>
						</label>
					</div>
				</div>

				{#if emailEnabled}
					<div class="form-group">
						<label class="label" for="email-address">Recipient Email</label>
						<input class="input" id="email-address" type="email" bind:value={emailAddress} placeholder="admin@example.com" />
					</div>
				{/if}

				<div class="form-group">
					<label class="label" for="webhook-url">Webhook URL</label>
					<input class="input" id="webhook-url" type="url" bind:value={webhookUrl} placeholder="https://hooks.example.com/nettap" />
					<p class="field-help">POST JSON payloads will be sent to this URL for each alert.</p>
				</div>

				<div class="btn-row">
					<button class="btn btn-primary" onclick={saveNotifications} disabled={notifSaving}>
						{notifSaving ? 'Saving...' : 'Save Notification Settings'}
					</button>
					<button class="btn btn-secondary" onclick={sendTestNotification} disabled={testingSending}>
						{testingSending ? 'Sending...' : 'Send Test Notification'}
					</button>
				</div>

				{#if testMessage}
					<div class="alert {testError ? 'alert-danger' : 'alert-success'}" style="margin-top: var(--space-md);">
						{testMessage}
					</div>
				{/if}
			</div>
		</div>

	{:else if activeTab === 'retention'}
		<div class="settings-section">
			<div class="card">
				<div class="card-header">
					<span class="card-title">Data Retention Policy</span>
				</div>

				{#if retentionMessage}
					<div class="alert {retentionError ? 'alert-danger' : 'alert-success'}" style="margin-bottom: var(--space-md);">
						{retentionMessage}
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

				{#if diskUsage !== null}
					<div class="disk-usage-bar">
						<div class="disk-usage-header">
							<span class="label" style="margin-bottom: 0;">Current Disk Usage</span>
							<span class="disk-usage-value" class:text-danger={diskUsage >= retentionConfig.disk_threshold} class:text-warning={diskUsage >= 60 && diskUsage < retentionConfig.disk_threshold}>{diskUsage}%</span>
						</div>
						<div class="disk-bar-track">
							<div
								class="disk-bar-fill"
								class:bar-danger={diskUsage >= retentionConfig.disk_threshold}
								class:bar-warning={diskUsage >= 60 && diskUsage < retentionConfig.disk_threshold}
								style="width: {Math.min(diskUsage, 100)}%"
							></div>
							<div class="disk-bar-marker" style="left: {retentionConfig.disk_threshold}%" title="Warning threshold"></div>
						</div>
					</div>
				{/if}

				<button class="btn btn-primary" onclick={saveRetention} disabled={retentionSaving}>
					{retentionSaving ? 'Saving...' : 'Save Retention Config'}
				</button>
			</div>
		</div>

	{:else if activeTab === 'display'}
		<div class="settings-section">
			<div class="card">
				<div class="card-header">
					<span class="card-title">Display Preferences</span>
				</div>

				{#if displayMessage}
					<div class="alert alert-success" style="margin-bottom: var(--space-md);">
						{displayMessage}
					</div>
				{/if}

				<div class="form-group">
					<label class="label" for="auto-refresh">Auto-Refresh Interval</label>
					<select class="select" id="auto-refresh" bind:value={autoRefresh}>
						<option value="0">Off</option>
						<option value="10">10 seconds</option>
						<option value="30">30 seconds</option>
						<option value="60">1 minute</option>
						<option value="300">5 minutes</option>
					</select>
					<p class="field-help">How often dashboards auto-refresh data.</p>
				</div>

				<div class="form-group">
					<label class="label" for="timezone">Timezone</label>
					<select class="select" id="timezone" bind:value={timezone}>
						<option value="utc">UTC</option>
						<option value="local">Local (browser)</option>
					</select>
					<p class="field-help">Timezone used for displaying timestamps.</p>
				</div>

				<div class="form-group">
					<label class="label" for="default-range">Default Time Range</label>
					<select class="select" id="default-range" bind:value={defaultTimeRange}>
						<option value="15m">Last 15 minutes</option>
						<option value="1h">Last 1 hour</option>
						<option value="4h">Last 4 hours</option>
						<option value="24h">Last 24 hours</option>
						<option value="7d">Last 7 days</option>
					</select>
					<p class="field-help">Default time window for traffic and alert views.</p>
				</div>

				<button class="btn btn-primary" onclick={saveDisplay} disabled={displaySaving}>
					{displaySaving ? 'Saving...' : 'Save Display Settings'}
				</button>
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
						<span class="about-label">Uptime</span>
						<span class="about-value mono">{uptime}</span>
					</div>
					<div class="about-row">
						<span class="about-label">License</span>
						<span class="about-value">Apache 2.0</span>
					</div>
					<div class="about-row">
						<span class="about-label">Stack</span>
						<span class="about-value">Zeek + Suricata + Arkime + OpenSearch</span>
					</div>
					<div class="about-row">
						<span class="about-label">Build</span>
						<span class="about-value mono">{buildInfo}</span>
					</div>
				</div>

				<div class="about-links">
					<a href="https://github.com/EliasMarine/NetTap" target="_blank" rel="noopener" class="btn btn-secondary">
						GitHub Repository
					</a>
					<a href="https://github.com/EliasMarine/NetTap/wiki" target="_blank" rel="noopener" class="btn btn-secondary">
						Documentation
					</a>
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

	.settings-section {
		max-width: 720px;
	}

	.field-help {
		font-size: var(--text-xs);
		color: var(--text-muted);
		margin-top: var(--space-xs);
	}

	.btn-row {
		display: flex;
		gap: var(--space-sm);
		align-items: center;
	}

	/* Retention grid */
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

	/* Disk usage bar */
	.disk-usage-bar {
		margin-bottom: var(--space-lg);
	}

	.disk-usage-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: var(--space-xs);
	}

	.disk-usage-value {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
	}

	.disk-bar-track {
		position: relative;
		height: 8px;
		background: var(--bg-tertiary);
		border-radius: var(--radius-full);
		overflow: visible;
	}

	.disk-bar-fill {
		height: 100%;
		border-radius: var(--radius-full);
		background: var(--accent);
		transition: width var(--transition-normal);
	}

	.disk-bar-fill.bar-warning {
		background: var(--amber);
	}

	.disk-bar-fill.bar-danger {
		background: var(--red);
	}

	.disk-bar-marker {
		position: absolute;
		top: -3px;
		width: 2px;
		height: 14px;
		background: var(--text-muted);
		border-radius: 1px;
		transform: translateX(-1px);
	}

	/* About section */
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

	.about-links {
		display: flex;
		gap: var(--space-sm);
		margin-top: var(--space-lg);
	}

	/* Toggle switch */
	.toggle-row {
		padding: var(--space-sm) 0;
	}

	.toggle-label {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-md);
		cursor: pointer;
	}

	.toggle-text {
		display: flex;
		flex-direction: column;
		gap: 2px;
		flex: 1;
	}

	.toggle-title {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
	}

	.toggle-description {
		font-size: var(--text-xs);
		color: var(--text-muted);
		line-height: 1.4;
	}

	.toggle-switch {
		position: relative;
		width: 44px;
		height: 24px;
		flex-shrink: 0;
	}

	.toggle-input {
		opacity: 0;
		width: 0;
		height: 0;
		position: absolute;
	}

	.toggle-slider {
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		bottom: 0;
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		border-radius: 12px;
		transition: all var(--transition-fast);
		cursor: pointer;
	}

	.toggle-slider::before {
		content: '';
		position: absolute;
		width: 18px;
		height: 18px;
		left: 2px;
		bottom: 2px;
		background-color: var(--text-muted);
		border-radius: 50%;
		transition: all var(--transition-fast);
	}

	.toggle-input:checked + .toggle-slider {
		background-color: var(--accent);
		border-color: var(--accent);
	}

	.toggle-input:checked + .toggle-slider::before {
		transform: translateX(20px);
		background-color: white;
	}

	.toggle-input:focus-visible + .toggle-slider {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}

	@media (max-width: 768px) {
		.retention-grid {
			grid-template-columns: 1fr;
		}

		.threshold-section {
			grid-template-columns: 1fr;
		}

		.btn-row {
			flex-direction: column;
			align-items: stretch;
		}

		.about-links {
			flex-direction: column;
		}
	}
</style>
