<script lang="ts">
	import { getSystemHealth } from '$lib/api/system';

	let activeTab = $state<'general' | 'retention' | 'network' | 'api-keys' | 'updates' | 'about'>('general');

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

	// -- API Keys state --
	let apiKeyStatus = $state<Record<string, boolean>>({});
	let apiKeySaving = $state(false);
	let apiKeySaveMessage = $state('');
	let apiKeySaveError = $state(false);

	// Password visibility toggles
	let showMaxMind = $state(false);
	let showSmtpPassword = $state(false);
	let showSuricataKey = $state(false);

	// -- Auto Updates state --
	let autoUpdateConfig = $state({
		suricata_rules_daily: true,
		geoip_weekly: true,
		containers_auto: false,
	});
	let autoUpdateSaving = $state(false);
	let autoUpdateMessage = $state('');

	// API key form values
	let maxmindKey = $state('');
	let smtpHost = $state('');
	let smtpPort = $state('587');
	let smtpUsername = $state('');
	let smtpPassword = $state('');
	let smtpSenderEmail = $state('');
	let webhookUrl = $state('');
	let suricataEtProKey = $state('');

	async function loadApiKeyStatus() {
		try {
			const res = await fetch('/api/settings/api-keys');
			if (res.ok) {
				const data = await res.json();
				apiKeyStatus = data.keys || {};
			}
		} catch {
			// Silently fail — status indicators will show as "Not Set"
		}
	}

	async function saveApiKeys(keys: Record<string, string>) {
		apiKeySaving = true;
		apiKeySaveMessage = '';
		apiKeySaveError = false;
		try {
			const res = await fetch('/api/settings/api-keys', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(keys),
			});
			const data = await res.json();
			if (res.ok) {
				apiKeySaveMessage = 'API keys saved successfully.';
				apiKeySaveError = false;
				apiKeyStatus = data.keys || apiKeyStatus;
			} else {
				apiKeySaveMessage = data.error || 'Failed to save API keys.';
				apiKeySaveError = true;
			}
		} catch {
			apiKeySaveMessage = 'Failed to connect to server.';
			apiKeySaveError = true;
		} finally {
			apiKeySaving = false;
		}
	}

	async function saveMaxMindKey() {
		if (!maxmindKey.trim()) return;
		await saveApiKeys({ MAXMIND_LICENSE_KEY: maxmindKey });
		maxmindKey = '';
	}

	async function saveSmtpSettings() {
		const keys: Record<string, string> = {};
		if (smtpHost.trim()) keys.SMTP_HOST = smtpHost;
		if (smtpPort.trim()) keys.SMTP_PORT = smtpPort;
		if (smtpUsername.trim()) keys.SMTP_USERNAME = smtpUsername;
		if (smtpPassword.trim()) keys.SMTP_PASSWORD = smtpPassword;
		if (smtpSenderEmail.trim()) keys.SMTP_SENDER_EMAIL = smtpSenderEmail;
		if (Object.keys(keys).length === 0) return;
		await saveApiKeys(keys);
		smtpPassword = '';
	}

	async function saveWebhookUrl() {
		if (!webhookUrl.trim()) return;
		await saveApiKeys({ WEBHOOK_URL: webhookUrl });
	}

	async function saveSuricataKey() {
		if (!suricataEtProKey.trim()) return;
		await saveApiKeys({ SURICATA_ET_PRO_KEY: suricataEtProKey });
		suricataEtProKey = '';
	}

	async function saveAutoUpdateConfig() {
		autoUpdateSaving = true;
		autoUpdateMessage = '';
		try {
			const res = await fetch('/api/settings/api-keys', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					AUTO_UPDATE_SURICATA_RULES: autoUpdateConfig.suricata_rules_daily ? 'true' : 'false',
					AUTO_UPDATE_GEOIP: autoUpdateConfig.geoip_weekly ? 'true' : 'false',
					AUTO_UPDATE_CONTAINERS: autoUpdateConfig.containers_auto ? 'true' : 'false',
				}),
			});
			if (res.ok) {
				autoUpdateMessage = 'Auto-update settings saved successfully.';
			} else {
				const data = await res.json();
				autoUpdateMessage = data.error || 'Failed to save auto-update settings.';
			}
		} catch {
			autoUpdateMessage = 'Failed to connect to server.';
		} finally {
			autoUpdateSaving = false;
		}
	}

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

		loadApiKeyStatus();
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
			class:active={activeTab === 'api-keys'}
			onclick={() => (activeTab = 'api-keys')}
		>
			API Keys
		</button>
		<button
			class="tab"
			class:active={activeTab === 'updates'}
			onclick={() => (activeTab = 'updates')}
		>
			Auto Updates
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
	{:else if activeTab === 'api-keys'}
		<div class="settings-section">
			{#if apiKeySaveMessage}
				<div class="alert {apiKeySaveError ? 'alert-danger' : 'alert-success'}" style="margin-bottom: var(--space-md);">
					{apiKeySaveMessage}
				</div>
			{/if}

			<!-- MaxMind GeoIP License Key -->
			<div class="card" style="margin-bottom: var(--space-md);">
				<div class="card-header">
					<span class="card-title">MaxMind GeoIP License Key</span>
					{#if apiKeyStatus.MAXMIND_LICENSE_KEY}
						<span class="badge badge-success">Configured</span>
					{:else}
						<span class="badge badge-muted">Not Set</span>
					{/if}
				</div>
				<div class="form-group">
					<label class="label" for="maxmind-key">License Key</label>
					<div class="password-field">
						<input
							class="input"
							id="maxmind-key"
							type={showMaxMind ? 'text' : 'password'}
							bind:value={maxmindKey}
							placeholder={apiKeyStatus.MAXMIND_LICENSE_KEY ? '********** (configured)' : 'Enter license key'}
						/>
						<button class="btn-toggle" type="button" onclick={() => (showMaxMind = !showMaxMind)}>
							{showMaxMind ? 'Hide' : 'Show'}
						</button>
					</div>
					<p class="field-help">Get a free license key at <a href="https://www.maxmind.com/en/geolite2/signup" target="_blank" rel="noopener">maxmind.com/en/geolite2/signup</a></p>
				</div>
				<button class="btn btn-primary" onclick={saveMaxMindKey} disabled={apiKeySaving || !maxmindKey.trim()}>
					{apiKeySaving ? 'Saving...' : 'Save'}
				</button>
			</div>

			<!-- SMTP Settings -->
			<div class="card" style="margin-bottom: var(--space-md);">
				<div class="card-header">
					<span class="card-title">SMTP Settings</span>
					{#if apiKeyStatus.SMTP_HOST && apiKeyStatus.SMTP_USERNAME}
						<span class="badge badge-success">Configured</span>
					{:else}
						<span class="badge badge-muted">Not Set</span>
					{/if}
				</div>
				<p class="field-help" style="margin-bottom: var(--space-md);">Required for email notifications and scheduled reports.</p>
				<div class="smtp-grid">
					<div class="form-group">
						<label class="label" for="smtp-host">SMTP Host</label>
						<input class="input" id="smtp-host" type="text" bind:value={smtpHost} placeholder={apiKeyStatus.SMTP_HOST ? '(configured)' : 'smtp.example.com'} />
					</div>
					<div class="form-group">
						<label class="label" for="smtp-port">SMTP Port</label>
						<input class="input" id="smtp-port" type="number" bind:value={smtpPort} min={1} max={65535} />
					</div>
					<div class="form-group">
						<label class="label" for="smtp-username">SMTP Username</label>
						<input class="input" id="smtp-username" type="text" bind:value={smtpUsername} placeholder={apiKeyStatus.SMTP_USERNAME ? '(configured)' : 'user@example.com'} />
					</div>
					<div class="form-group">
						<label class="label" for="smtp-password">SMTP Password</label>
						<div class="password-field">
							<input
								class="input"
								id="smtp-password"
								type={showSmtpPassword ? 'text' : 'password'}
								bind:value={smtpPassword}
								placeholder={apiKeyStatus.SMTP_PASSWORD ? '********** (configured)' : 'Enter password'}
							/>
							<button class="btn-toggle" type="button" onclick={() => (showSmtpPassword = !showSmtpPassword)}>
								{showSmtpPassword ? 'Hide' : 'Show'}
							</button>
						</div>
					</div>
					<div class="form-group smtp-full-width">
						<label class="label" for="smtp-sender">Sender Email</label>
						<input class="input" id="smtp-sender" type="email" bind:value={smtpSenderEmail} placeholder={apiKeyStatus.SMTP_SENDER_EMAIL ? '(configured)' : 'nettap@example.com'} />
					</div>
				</div>
				<button class="btn btn-primary" onclick={saveSmtpSettings} disabled={apiKeySaving}>
					{apiKeySaving ? 'Saving...' : 'Save SMTP Settings'}
				</button>
			</div>

			<!-- Webhook URL -->
			<div class="card" style="margin-bottom: var(--space-md);">
				<div class="card-header">
					<span class="card-title">Webhook URL</span>
					{#if apiKeyStatus.WEBHOOK_URL}
						<span class="badge badge-success">Configured</span>
					{:else}
						<span class="badge badge-muted">Not Set</span>
					{/if}
				</div>
				<div class="form-group">
					<label class="label" for="webhook-url">Webhook Endpoint</label>
					<input class="input" id="webhook-url" type="url" bind:value={webhookUrl} placeholder={apiKeyStatus.WEBHOOK_URL ? '(configured)' : 'https://hooks.example.com/nettap'} />
					<p class="field-help">POST JSON payloads will be sent to this URL for alerts.</p>
				</div>
				<button class="btn btn-primary" onclick={saveWebhookUrl} disabled={apiKeySaving || !webhookUrl.trim()}>
					{apiKeySaving ? 'Saving...' : 'Save'}
				</button>
			</div>

			<!-- Suricata Rule Update Token -->
			<div class="card">
				<div class="card-header">
					<span class="card-title">Suricata Rule Update Token</span>
					{#if apiKeyStatus.SURICATA_ET_PRO_KEY}
						<span class="badge badge-success">Configured</span>
					{:else}
						<span class="badge badge-muted">Not Set</span>
					{/if}
				</div>
				<div class="form-group">
					<label class="label" for="suricata-key">ET Pro Key</label>
					<div class="password-field">
						<input
							class="input"
							id="suricata-key"
							type={showSuricataKey ? 'text' : 'password'}
							bind:value={suricataEtProKey}
							placeholder={apiKeyStatus.SURICATA_ET_PRO_KEY ? '********** (configured)' : 'Enter ET Pro key'}
						/>
						<button class="btn-toggle" type="button" onclick={() => (showSuricataKey = !showSuricataKey)}>
							{showSuricataKey ? 'Hide' : 'Show'}
						</button>
					</div>
					<p class="field-help">Optional. Only needed for Emerging Threats Pro ruleset.</p>
				</div>
				<button class="btn btn-primary" onclick={saveSuricataKey} disabled={apiKeySaving || !suricataEtProKey.trim()}>
					{apiKeySaving ? 'Saving...' : 'Save'}
				</button>
			</div>
		</div>
	{:else if activeTab === 'updates'}
		<div class="settings-section">
			<div class="card">
				<div class="card-header">
					<span class="card-title">Automatic Updates</span>
				</div>

				{#if autoUpdateMessage}
					<div class="alert {autoUpdateMessage.includes('success') ? 'alert-success' : 'alert-danger'}" style="margin-bottom: var(--space-md);">
						{autoUpdateMessage}
					</div>
				{/if}

				<div class="auto-update-options">
					<div class="toggle-row">
						<label class="toggle-label" for="suricata-rules-toggle">
							<div class="toggle-text">
								<span class="toggle-title">Auto-update Suricata rules (daily)</span>
								<span class="toggle-description">Automatically download and apply the latest Emerging Threats ruleset every day. Keeps IDS signatures current against new threats.</span>
							</div>
							<div class="toggle-switch">
								<input
									type="checkbox"
									id="suricata-rules-toggle"
									class="toggle-input"
									bind:checked={autoUpdateConfig.suricata_rules_daily}
								/>
								<span class="toggle-slider"></span>
							</div>
						</label>
					</div>

					<div class="toggle-row">
						<label class="toggle-label" for="geoip-toggle">
							<div class="toggle-text">
								<span class="toggle-title">Auto-update GeoIP database (weekly)</span>
								<span class="toggle-description">Automatically download the latest MaxMind GeoIP database each week. Requires a configured MaxMind license key.</span>
							</div>
							<div class="toggle-switch">
								<input
									type="checkbox"
									id="geoip-toggle"
									class="toggle-input"
									bind:checked={autoUpdateConfig.geoip_weekly}
								/>
								<span class="toggle-slider"></span>
							</div>
						</label>
					</div>

					<div class="toggle-row">
						<label class="toggle-label" for="containers-toggle">
							<div class="toggle-text">
								<span class="toggle-title">Auto-update containers</span>
								<span class="toggle-description">Automatically pull and restart Docker containers when new images are available. Disabled by default to prevent unexpected downtime. Manual updates recommended.</span>
							</div>
							<div class="toggle-switch">
								<input
									type="checkbox"
									id="containers-toggle"
									class="toggle-input"
									bind:checked={autoUpdateConfig.containers_auto}
								/>
								<span class="toggle-slider"></span>
							</div>
						</label>
					</div>
				</div>

				<button class="btn btn-primary" onclick={saveAutoUpdateConfig} disabled={autoUpdateSaving}>
					{autoUpdateSaving ? 'Saving...' : 'Save Auto-Update Settings'}
				</button>
			</div>

			<div class="card" style="margin-top: var(--space-md);">
				<div class="card-header">
					<span class="card-title">Manual Updates</span>
				</div>
				<p class="field-help" style="margin-bottom: var(--space-md);">
					View installed versions, check for updates, and apply them from the Software Updates page.
				</p>
				<a href="/system/updates" class="btn btn-secondary">
					Open Software Updates
				</a>
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

	/* API Keys tab */
	.password-field {
		display: flex;
		gap: var(--space-xs);
		align-items: center;
	}

	.password-field .input {
		flex: 1;
	}

	.btn-toggle {
		padding: var(--space-xs) var(--space-sm);
		font-family: var(--font-sans);
		font-size: var(--text-xs);
		color: var(--text-muted);
		background: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		cursor: pointer;
		white-space: nowrap;
		transition: all var(--transition-fast);
	}

	.btn-toggle:hover {
		color: var(--text-primary);
		background: var(--bg-secondary);
	}

	.card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.badge-muted {
		font-size: var(--text-xs);
		padding: 2px 8px;
		border-radius: var(--radius-sm);
		background: var(--bg-tertiary);
		color: var(--text-muted);
		font-weight: 500;
	}

	.smtp-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: var(--space-md);
		margin-bottom: var(--space-lg);
	}

	.smtp-full-width {
		grid-column: 1 / -1;
	}

	/* Auto Updates tab */
	.auto-update-options {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		margin-bottom: var(--space-lg);
	}

	.toggle-row {
		padding: var(--space-md) 0;
		border-bottom: 1px solid var(--border-muted);
	}

	.toggle-row:last-child {
		border-bottom: none;
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

		.smtp-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
