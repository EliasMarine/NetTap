<script lang="ts">
	import { onMount } from 'svelte';
	import { getCaptureStatus, toggleCapture, updateCaptureSettings } from '$lib/api/capture';
	import { previewCleanup, executeCleanup, type CleanupPreview } from '$lib/api/storage';

	type TabId = 'notifications' | 'retention' | 'capture' | 'api-keys' | 'network' | 'display' | 'about';

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
	let lastPruneAt = $state<string | null>(null);
	let ilmStatus = $state<{ synced: boolean; last_applied: string | null; pending_retry: boolean; policies: Record<string, string> } | null>(null);
	let retentionSaving = $state(false);
	let retentionMessage = $state('');
	let retentionError = $state(false);

	// --- Manual Cleanup state ---
	let cleanupDays = $state(60);
	let cleanupPreview = $state<CleanupPreview | null>(null);
	let cleanupPreviewing = $state(false);
	let cleanupExecuting = $state(false);
	let showCleanupConfirm = $state(false);
	let cleanupMessage = $state('');
	let cleanupError = $state(false);

	// --- Network state (excluded IPs) ---
	let excludedIps = $state<string[]>([]);
	let newExcludedIp = $state('');
	let networkSaving = $state(false);
	let networkMessage = $state('');
	let networkError = $state(false);
	let networkLoading = $state(true);

	// --- API Keys state ---
	let apiKeysStatus = $state<Record<string, boolean>>({});
	let apiKeysLoading = $state(true);
	let apiKeysSaving = $state(false);
	let apiKeysMessage = $state('');
	let apiKeysError = $state(false);
	// Track modified fields only — don't send unchanged values
	let apiKeyValues = $state<Record<string, string>>({});

	// --- Capture state ---
	let captureEnabled = $state(true);
	let captureMaxFileSize = $state(100);
	let captureContainerRunning = $state(false);
	let captureContainerStatus = $state('unknown');
	let captureLoading = $state(true);
	let captureToggling = $state(false);
	let captureSaving = $state(false);
	let captureMessage = $state('');
	let captureError = $state(false);

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
				// GET /api/setup/storage returns a FLAT StorageStatus object
				// (hot_days, warm_days, etc. are top-level, not nested under retention)
				retentionConfig.hot_days = data.hot_days ?? 90;
				retentionConfig.warm_days = data.warm_days ?? 180;
				retentionConfig.cold_days = data.cold_days ?? 30;
				retentionConfig.disk_threshold = data.disk_threshold_percent ?? 80;
				retentionConfig.emergency_threshold = data.emergency_threshold_percent ?? 90;
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
				lastPruneAt = data.last_prune_at ?? null;
				ilmStatus = data.ilm_status ?? null;
			}
		} catch {
			// Will stay null
		}
	}

	// --- Retention health helpers ---
	function timeAgo(isoString: string): string {
		const diff = Date.now() - new Date(isoString).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h ago`;
		return `${Math.floor(hours / 24)}d ago`;
	}

	let retentionHealth = $derived.by(() => {
		const ilmOk = ilmStatus?.synced ?? false;
		const ilmPending = ilmStatus?.pending_retry ?? false;
		const pruneOk = lastPruneAt ? (Date.now() - new Date(lastPruneAt).getTime()) < 600000 : false;
		const pruneStale = lastPruneAt ? (Date.now() - new Date(lastPruneAt).getTime()) > 1800000 : true;
		const diskPct = diskUsage ?? 0;
		const diskHigh = diskPct >= (retentionConfig.disk_threshold ?? 80);
		const diskCritical = diskPct >= (retentionConfig.emergency_threshold ?? 90);

		let status: 'healthy' | 'attention' | 'problem' = 'healthy';
		if ((!ilmOk && !ilmPending) || diskCritical) status = 'problem';
		else if (ilmPending || diskHigh || !pruneOk) status = 'attention';

		return { status, ilmOk, ilmPending, pruneOk, pruneStale, diskPct, diskHigh, diskCritical };
	});

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

	async function loadExcludedIps() {
		networkLoading = true;
		try {
			const res = await fetch('/api/settings/excluded-ips');
			if (res.ok) {
				const data = await res.json();
				excludedIps = data.excluded_ips ?? [];
			}
		} catch {
			// Will use empty default
		} finally {
			networkLoading = false;
		}
	}

	async function loadApiKeys() {
		apiKeysLoading = true;
		try {
			const res = await fetch('/api/settings/api-keys');
			if (res.ok) {
				const data = await res.json();
				apiKeysStatus = data.keys ?? {};
			}
		} catch {
			// Will use empty default
		} finally {
			apiKeysLoading = false;
		}
	}

	async function saveApiKeys() {
		apiKeysSaving = true;
		apiKeysMessage = '';
		apiKeysError = false;

		// Only send fields that have been modified (non-empty)
		const payload: Record<string, string> = {};
		for (const [key, value] of Object.entries(apiKeyValues)) {
			if (value.trim()) {
				payload[key] = value.trim();
			}
		}

		if (Object.keys(payload).length === 0) {
			apiKeysMessage = 'No changes to save. Enter a value in at least one field.';
			apiKeysError = true;
			apiKeysSaving = false;
			return;
		}

		try {
			const res = await fetch('/api/settings/api-keys', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload),
			});
			const data = await res.json();
			if (res.ok) {
				apiKeysMessage = `Saved ${data.saved_count ?? Object.keys(payload).length} key(s) successfully.`;
				apiKeysStatus = data.keys ?? apiKeysStatus;
				// Clear input fields after successful save
				apiKeyValues = {};
			} else {
				apiKeysMessage = data.error || 'Failed to save API keys.';
				apiKeysError = true;
			}
		} catch {
			apiKeysMessage = 'Failed to connect to server.';
			apiKeysError = true;
		} finally {
			apiKeysSaving = false;
		}
	}

	async function saveExcludedIps() {
		networkSaving = true;
		networkMessage = '';
		networkError = false;
		try {
			const res = await fetch('/api/settings/excluded-ips', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ excluded_ips: excludedIps }),
			});
			if (res.ok) {
				networkMessage = 'Excluded IPs saved. Changes take effect immediately.';
			} else {
				const data = await res.json();
				networkMessage = data.error || 'Failed to save excluded IPs.';
				networkError = true;
			}
		} catch {
			networkMessage = 'Failed to connect to server.';
			networkError = true;
		} finally {
			networkSaving = false;
		}
	}

	function addExcludedIp() {
		const ip = newExcludedIp.trim();
		if (!ip) return;
		// Basic IP format validation
		if (!/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(ip)) {
			networkMessage = 'Please enter a valid IPv4 address.';
			networkError = true;
			return;
		}
		if (excludedIps.includes(ip)) {
			networkMessage = `${ip} is already in the exclusion list.`;
			networkError = true;
			return;
		}
		excludedIps = [...excludedIps, ip];
		newExcludedIp = '';
		networkMessage = '';
	}

	function removeExcludedIp(ip: string) {
		excludedIps = excludedIps.filter((i) => i !== ip);
	}

	// --- Capture functions ---
	async function loadCaptureSettings() {
		captureLoading = true;
		try {
			const status = await getCaptureStatus();
			captureEnabled = status.enabled;
			captureMaxFileSize = status.maxFileSizeMB;
			captureContainerRunning = status.containerRunning;
			captureContainerStatus = status.containerStatus;
		} catch {
			// Will use defaults
		} finally {
			captureLoading = false;
		}
	}

	async function handleCaptureToggle() {
		captureToggling = true;
		captureMessage = '';
		captureError = false;
		try {
			const result = await toggleCapture(!captureEnabled);
			captureEnabled = result.enabled;
			captureContainerRunning = result.containerRunning;
			captureContainerStatus = result.containerStatus;
			captureMessage = captureEnabled ? 'PCAP capture enabled' : 'PCAP capture disabled';
		} catch (err) {
			captureError = true;
			captureMessage = err instanceof Error ? err.message : 'Toggle failed';
		} finally {
			captureToggling = false;
		}
	}

	async function saveCaptureSettings() {
		captureSaving = true;
		captureMessage = '';
		captureError = false;
		try {
			const result = await updateCaptureSettings({ maxFileSizeMB: captureMaxFileSize });
			captureMaxFileSize = result.maxFileSizeMB;
			captureMessage = result.restarted
				? `File size updated to ${result.maxFileSizeMB} MB. Container restarted.`
				: `File size updated to ${result.maxFileSizeMB} MB.`;
		} catch (err) {
			captureError = true;
			captureMessage = err instanceof Error ? err.message : 'Save failed';
		} finally {
			captureSaving = false;
		}
	}

	onMount(() => {
		loadNotificationConfig();
		loadRetention();
		loadDiskUsage();
		loadExcludedIps();
		loadApiKeys();
		loadAbout();
		loadDisplaySettings();
		loadCaptureSettings();
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
				const result = await res.json();
				if (result.ilm_applied) {
					retentionMessage = 'Retention settings saved and applied to OpenSearch.';
				} else {
					retentionMessage = 'Retention settings saved. OpenSearch policies will sync shortly.';
				}
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

	function formatCleanupBytes(bytes: number): string {
		if (bytes === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
	}

	async function handleCleanupPreview() {
		if (cleanupDays < 1) return;
		cleanupPreviewing = true;
		cleanupMessage = '';
		cleanupError = false;
		cleanupPreview = null;
		showCleanupConfirm = false;

		try {
			cleanupPreview = await previewCleanup(cleanupDays);
		} catch (err: unknown) {
			cleanupMessage = err instanceof Error ? err.message : 'Failed to preview cleanup';
			cleanupError = true;
		} finally {
			cleanupPreviewing = false;
		}
	}

	async function handleCleanupExecute() {
		cleanupExecuting = true;
		cleanupMessage = '';
		cleanupError = false;

		try {
			const result = await executeCleanup(cleanupDays);
			const freedStr = formatCleanupBytes(result.freed_bytes_estimate);
			cleanupMessage = `Cleanup complete: deleted ${result.deleted_indices} indices and ${result.deleted_pcap_files} PCAP files, freed ${freedStr}.`;
			if (result.errors.length > 0) {
				cleanupMessage += ` (${result.errors.length} errors)`;
			}
			cleanupError = false;
			cleanupPreview = null;
			showCleanupConfirm = false;

			// Refresh disk usage
			try {
				const res = await fetch('/api/storage/status');
				if (res.ok) {
					const data = await res.json();
					diskUsage = data.disk_usage_percent ?? diskUsage;
				}
			} catch {
				// Non-critical, disk usage will update on next load
			}
		} catch (err: unknown) {
			cleanupMessage = err instanceof Error ? err.message : 'Cleanup failed';
			cleanupError = true;
		} finally {
			cleanupExecuting = false;
		}
	}

	function cancelCleanup() {
		showCleanupConfirm = false;
		cleanupPreview = null;
		cleanupMessage = '';
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
			class:active={activeTab === 'capture'}
			onclick={() => (activeTab = 'capture')}
		>
			Capture
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
			class:active={activeTab === 'network'}
			onclick={() => (activeTab = 'network')}
		>
			Network
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

			<!-- Retention Health Status -->
			<div class="card retention-health-card">
				<div class="card-header">
					<span class="card-title">Retention Health</span>
					<span class="health-badge health-{retentionHealth.status}">
						<span class="health-dot"></span>
						{retentionHealth.status === 'healthy' ? 'Healthy' : retentionHealth.status === 'attention' ? 'Attention' : 'Problem'}
					</span>
				</div>

				<div class="health-rows">
					<div class="health-row">
						<span class="health-label">ILM Policies</span>
						<span class="health-value">
							{#if ilmStatus === null}
								<span class="text-muted">Loading...</span>
							{:else if retentionHealth.ilmPending}
								<span style="color: var(--amber);">&#x27f3; Syncing...</span>
							{:else if retentionHealth.ilmOk}
								<span style="color: var(--green);">&#x2713; All {Object.keys(ilmStatus.policies).length || 3} synced</span>
							{:else}
								<span style="color: var(--red);">&#x2717; Out of sync</span>
							{/if}
						</span>
					</div>
					<div class="health-row">
						<span class="health-label">Disk Usage</span>
						<span class="health-value">
							{#if diskUsage !== null}
								<span class="mono" style="color: {retentionHealth.diskCritical ? 'var(--red)' : retentionHealth.diskHigh ? 'var(--amber)' : 'var(--green)'}">
									{diskUsage}%
								</span>
								<span class="text-muted">(threshold: {retentionConfig.disk_threshold}%)</span>
							{:else}
								<span class="text-muted">Unavailable</span>
							{/if}
						</span>
					</div>
					<div class="health-row">
						<span class="health-label">Last Prune</span>
						<span class="health-value">
							{#if lastPruneAt}
								<span class="mono" style="color: {retentionHealth.pruneStale ? 'var(--red)' : retentionHealth.pruneOk ? 'var(--green)' : 'var(--amber)'}">
									{timeAgo(lastPruneAt)}
								</span>
							{:else}
								<span class="text-muted">Never (daemon starting...)</span>
							{/if}
						</span>
					</div>
				</div>
			</div>

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

		<!-- Manual Data Cleanup -->
		<div class="card" style="margin-top: var(--space-lg);">
			<div class="card-header">
				<span class="card-title">Manual Data Cleanup</span>
			</div>

			<p class="field-help" style="margin-bottom: var(--space-md);">
				Permanently delete OpenSearch indices and PCAP files older than a specified number of days to free up disk space.
			</p>

			{#if cleanupMessage}
				<div class="alert {cleanupError ? 'alert-danger' : 'alert-success'}" style="margin-bottom: var(--space-md);">
					{cleanupMessage}
				</div>
			{/if}

			<div class="cleanup-input-row">
				<span class="cleanup-label">Delete data older than</span>
				<div class="input-with-unit" style="width: 120px;">
					<input
						class="input"
						type="number"
						bind:value={cleanupDays}
						min={1}
						max={3650}
						disabled={cleanupExecuting}
					/>
					<span class="input-unit">days</span>
				</div>
				<button
					class="btn btn-secondary"
					onclick={handleCleanupPreview}
					disabled={cleanupPreviewing || cleanupExecuting || cleanupDays < 1}
				>
					{cleanupPreviewing ? 'Scanning...' : 'Preview Cleanup'}
				</button>
			</div>

			{#if cleanupPreview}
				<div class="cleanup-preview">
					<div class="cleanup-preview-header">
						<span class="cleanup-preview-title">Cleanup Preview</span>
						<span class="text-muted">Data before {new Date(cleanupPreview.cutoff_date).toLocaleDateString()}</span>
					</div>

					<div class="cleanup-stats">
						<div class="cleanup-stat">
							<span class="cleanup-stat-value">{cleanupPreview.total_indices}</span>
							<span class="cleanup-stat-label">Indices</span>
						</div>
						<div class="cleanup-stat">
							<span class="cleanup-stat-value">{cleanupPreview.total_pcap_files}</span>
							<span class="cleanup-stat-label">PCAP Files</span>
						</div>
						<div class="cleanup-stat">
							<span class="cleanup-stat-value">{formatCleanupBytes(cleanupPreview.estimated_freed_bytes)}</span>
							<span class="cleanup-stat-label">Space Freed</span>
						</div>
					</div>

					{#if cleanupPreview.total_indices === 0 && cleanupPreview.total_pcap_files === 0}
						<p class="text-muted" style="margin-top: var(--space-sm);">No data found older than {cleanupDays} days.</p>
					{:else}
						<div class="cleanup-confirm-section">
							{#if !showCleanupConfirm}
								<p class="text-danger" style="font-size: var(--text-sm); margin-bottom: var(--space-sm);">
									This action is irreversible. Deleted data cannot be recovered.
								</p>
								<div class="cleanup-actions">
									<button class="btn btn-secondary" onclick={cancelCleanup}>Cancel</button>
									<button class="btn btn-danger" onclick={() => showCleanupConfirm = true}>
										Delete Data
									</button>
								</div>
							{:else}
								<div class="cleanup-final-confirm">
									<p class="text-danger" style="font-weight: 600; margin-bottom: var(--space-sm);">
										Are you sure? This will permanently delete {cleanupPreview.total_indices} indices and {cleanupPreview.total_pcap_files} PCAP files ({formatCleanupBytes(cleanupPreview.estimated_freed_bytes)}).
									</p>
									<div class="cleanup-actions">
										<button class="btn btn-secondary" onclick={cancelCleanup} disabled={cleanupExecuting}>
											Cancel
										</button>
										<button class="btn btn-danger" onclick={handleCleanupExecute} disabled={cleanupExecuting}>
											{cleanupExecuting ? 'Deleting...' : 'Confirm Delete'}
										</button>
									</div>
								</div>
							{/if}
						</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>

	{:else if activeTab === 'capture'}
		<div class="settings-section">
			<div class="card">
				<div class="card-header">
					<span class="card-title">PCAP Capture</span>
				</div>

				{#if captureMessage}
					<div class="alert {captureError ? 'alert-danger' : 'alert-success'}" style="margin-bottom: var(--space-md);">
						{captureMessage}
					</div>
				{/if}

				{#if captureLoading}
					<p class="text-muted">Loading capture settings...</p>
				{:else}
					<!-- Status card -->
					<div class="capture-status-card" style="margin-bottom: var(--space-lg);">
						<div class="capture-status-row">
							<span class="label">Container Status</span>
							<span class="capture-badge" class:status-running={captureContainerRunning} class:status-stopped={!captureContainerRunning}>
								{captureContainerRunning ? 'Running' : captureContainerStatus}
							</span>
						</div>
					</div>

					<!-- Toggle -->
					<div class="form-group" style="margin-bottom: var(--space-lg);">
						<label class="label">PCAP Collection</label>
						<div class="capture-toggle-row">
							<button
								class="capture-toggle-switch"
								class:on={captureEnabled}
								onclick={handleCaptureToggle}
								disabled={captureToggling}
							>
								<span class="capture-toggle-knob" class:loading={captureToggling}></span>
							</button>
							<span class="capture-toggle-label">{captureEnabled ? 'Enabled — capturing packets' : 'Disabled — no new captures'}</span>
						</div>
						<p class="field-help">When disabled, the capture container is stopped. Existing PCAP files remain accessible.</p>
					</div>

					<!-- File size -->
					<div class="form-group" style="margin-bottom: var(--space-lg);">
						<label class="label" for="max-file-size">Max File Size</label>
						<div class="input-with-unit">
							<input
								class="input"
								id="max-file-size"
								type="number"
								bind:value={captureMaxFileSize}
								min={10}
								max={10000}
							/>
							<span class="input-unit">MB</span>
						</div>
						<p class="field-help">Individual PCAP files rotate at this size. Default: 100 MB. Range: 10–10,000 MB.</p>
					</div>

					<button class="btn btn-primary" onclick={saveCaptureSettings} disabled={captureSaving}>
						{captureSaving ? 'Saving...' : 'Save Capture Settings'}
					</button>
				{/if}
			</div>
		</div>

	{:else if activeTab === 'api-keys'}
		<div class="settings-section">
			<div class="card">
				<div class="card-header">
					<span class="card-title">API Keys &amp; Credentials</span>
				</div>

				<p class="field-help" style="margin-bottom: var(--space-lg);">
					Configure external service credentials. Keys are stored securely on disk and never displayed after saving.
					Fields showing "Configured" already have a value saved — leave the input blank to keep the existing value.
				</p>

				{#if apiKeysMessage}
					<div class="alert {apiKeysError ? 'alert-danger' : 'alert-success'}" style="margin-bottom: var(--space-md);">
						{apiKeysMessage}
					</div>
				{/if}

				{#if apiKeysLoading}
					<p class="text-muted">Loading API key status...</p>
				{:else}
					<!-- GeoIP Section -->
					<div class="api-keys-section">
						<h4 class="api-keys-section-title">GeoIP Lookups</h4>

						<div class="form-group">
							<div class="label-with-badge">
								<label class="label" for="maxmind-key">MaxMind License Key</label>
								{#if apiKeysStatus['MAXMIND_LICENSE_KEY']}
									<span class="badge badge-configured">Configured</span>
								{/if}
							</div>
							<input
								class="input"
								id="maxmind-key"
								type="password"
								bind:value={apiKeyValues['MAXMIND_LICENSE_KEY']}
								placeholder={apiKeysStatus['MAXMIND_LICENSE_KEY'] ? 'Leave blank to keep current value' : 'Enter MaxMind license key'}
							/>
							<p class="field-help">Required for GeoIP map visualizations. Get a free key at <a href="https://www.maxmind.com/en/geolite2/signup" target="_blank" rel="noopener">maxmind.com</a>.</p>
						</div>
					</div>

					<!-- IDS Rules Section -->
					<div class="api-keys-section">
						<h4 class="api-keys-section-title">IDS Rules</h4>

						<div class="form-group">
							<div class="label-with-badge">
								<label class="label" for="et-pro-key">Emerging Threats Pro Key</label>
								{#if apiKeysStatus['SURICATA_ET_PRO_KEY']}
									<span class="badge badge-configured">Configured</span>
								{/if}
							</div>
							<input
								class="input"
								id="et-pro-key"
								type="password"
								bind:value={apiKeyValues['SURICATA_ET_PRO_KEY']}
								placeholder={apiKeysStatus['SURICATA_ET_PRO_KEY'] ? 'Leave blank to keep current value' : 'Enter ET Pro key (optional)'}
							/>
							<p class="field-help">Optional. Enables Proofpoint's commercial Suricata ruleset. Free ET Open rules are used by default.</p>
						</div>
					</div>

					<!-- SMTP Section -->
					<div class="api-keys-section">
						<h4 class="api-keys-section-title">SMTP (Email Alerts)</h4>
						<p class="field-help" style="margin-bottom: var(--space-md);">
							Required for email notifications. Configure your SMTP server details below, then enable email alerts in the Notifications tab.
						</p>

						<div class="smtp-grid">
							<div class="form-group">
								<div class="label-with-badge">
									<label class="label" for="smtp-host">SMTP Host</label>
									{#if apiKeysStatus['SMTP_HOST']}
										<span class="badge badge-configured">Configured</span>
									{/if}
								</div>
								<input
									class="input"
									id="smtp-host"
									type="text"
									bind:value={apiKeyValues['SMTP_HOST']}
									placeholder={apiKeysStatus['SMTP_HOST'] ? 'Leave blank to keep current' : 'smtp.gmail.com'}
								/>
								<p class="field-help">SMTP server hostname.</p>
							</div>

							<div class="form-group">
								<div class="label-with-badge">
									<label class="label" for="smtp-port">SMTP Port</label>
									{#if apiKeysStatus['SMTP_PORT']}
										<span class="badge badge-configured">Configured</span>
									{/if}
								</div>
								<input
									class="input"
									id="smtp-port"
									type="text"
									bind:value={apiKeyValues['SMTP_PORT']}
									placeholder={apiKeysStatus['SMTP_PORT'] ? 'Leave blank to keep current' : '587'}
								/>
								<p class="field-help">587 for STARTTLS, 465 for SSL/TLS.</p>
							</div>

							<div class="form-group">
								<div class="label-with-badge">
									<label class="label" for="smtp-username">SMTP Username</label>
									{#if apiKeysStatus['SMTP_USERNAME']}
										<span class="badge badge-configured">Configured</span>
									{/if}
								</div>
								<input
									class="input"
									id="smtp-username"
									type="text"
									bind:value={apiKeyValues['SMTP_USERNAME']}
									placeholder={apiKeysStatus['SMTP_USERNAME'] ? 'Leave blank to keep current' : 'user@example.com'}
								/>
								<p class="field-help">Your SMTP login username or email.</p>
							</div>

							<div class="form-group">
								<div class="label-with-badge">
									<label class="label" for="smtp-password">SMTP Password</label>
									{#if apiKeysStatus['SMTP_PASSWORD']}
										<span class="badge badge-configured">Configured</span>
									{/if}
								</div>
								<input
									class="input"
									id="smtp-password"
									type="password"
									bind:value={apiKeyValues['SMTP_PASSWORD']}
									placeholder={apiKeysStatus['SMTP_PASSWORD'] ? 'Leave blank to keep current' : 'App password or SMTP password'}
								/>
								<p class="field-help">For Gmail, use an App Password (not your account password).</p>
							</div>

							<div class="form-group smtp-sender-full">
								<div class="label-with-badge">
									<label class="label" for="smtp-sender">Sender Email</label>
									{#if apiKeysStatus['SMTP_SENDER_EMAIL']}
										<span class="badge badge-configured">Configured</span>
									{/if}
								</div>
								<input
									class="input"
									id="smtp-sender"
									type="email"
									bind:value={apiKeyValues['SMTP_SENDER_EMAIL']}
									placeholder={apiKeysStatus['SMTP_SENDER_EMAIL'] ? 'Leave blank to keep current' : 'nettap@example.com'}
								/>
								<p class="field-help">The "From" address on alert emails.</p>
							</div>
						</div>
					</div>

					<!-- Webhook Section -->
					<div class="api-keys-section">
						<h4 class="api-keys-section-title">Webhook</h4>

						<div class="form-group">
							<div class="label-with-badge">
								<label class="label" for="webhook-url-keys">Webhook URL</label>
								{#if apiKeysStatus['WEBHOOK_URL']}
									<span class="badge badge-configured">Configured</span>
								{/if}
							</div>
							<input
								class="input"
								id="webhook-url-keys"
								type="url"
								bind:value={apiKeyValues['WEBHOOK_URL']}
								placeholder={apiKeysStatus['WEBHOOK_URL'] ? 'Leave blank to keep current' : 'https://hooks.slack.com/services/...'}
							/>
							<p class="field-help">Also configurable in the Notifications tab. JSON alert payloads are POSTed here.</p>
						</div>
					</div>

					<button class="btn btn-primary" onclick={saveApiKeys} disabled={apiKeysSaving} style="margin-top: var(--space-md);">
						{apiKeysSaving ? 'Saving...' : 'Save API Keys'}
					</button>
				{/if}
			</div>
		</div>

	{:else if activeTab === 'network'}
		<div class="settings-section">
			<div class="card">
				<div class="card-header">
					<span class="card-title">Excluded IPs</span>
				</div>

				<p class="field-help" style="margin-bottom: var(--space-md);">
					IPs in this list are hidden from device-centric views (Devices, Top Talkers, Risk Scores) but remain visible in Log Explorer, Alerts, and raw connection data.
					Useful for filtering out your ISP gateway's public IP or infrastructure addresses that appear on every connection.
				</p>

				{#if networkMessage}
					<div class="alert {networkError ? 'alert-danger' : 'alert-success'}" style="margin-bottom: var(--space-md);">
						{networkMessage}
					</div>
				{/if}

				{#if networkLoading}
					<p class="text-muted">Loading...</p>
				{:else}
					<div class="excluded-ip-input-row">
						<input
							class="input"
							type="text"
							bind:value={newExcludedIp}
							placeholder="e.g. 99.10.70.92"
							onkeydown={(e) => { if (e.key === 'Enter') addExcludedIp(); }}
						/>
						<button class="btn btn-secondary" onclick={addExcludedIp}>Add</button>
					</div>

					{#if excludedIps.length === 0}
						<p class="text-muted" style="margin-top: var(--space-md);">No IPs excluded. All IPs appear in device views.</p>
					{:else}
						<div class="excluded-ip-list">
							{#each excludedIps as ip}
								<div class="excluded-ip-item">
									<span class="mono">{ip}</span>
									<button class="btn-icon-remove" onclick={() => removeExcludedIp(ip)} title="Remove {ip}">
										&times;
									</button>
								</div>
							{/each}
						</div>
					{/if}

					<button class="btn btn-primary" onclick={saveExcludedIps} disabled={networkSaving} style="margin-top: var(--space-md);">
						{networkSaving ? 'Saving...' : 'Save Excluded IPs'}
					</button>
				{/if}
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

	/* Excluded IPs */
	.excluded-ip-input-row {
		display: flex;
		gap: var(--space-sm);
		align-items: center;
	}

	.excluded-ip-input-row .input {
		flex: 1;
		max-width: 300px;
	}

	.excluded-ip-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
		margin-top: var(--space-md);
	}

	.excluded-ip-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-xs) var(--space-sm);
		background: var(--bg-tertiary);
		border: 1px solid var(--border-muted);
		border-radius: var(--radius-md);
	}

	.excluded-ip-item .mono {
		font-size: var(--text-sm);
		color: var(--text-primary);
	}

	.btn-icon-remove {
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 1.2rem;
		cursor: pointer;
		padding: 0 var(--space-xs);
		line-height: 1;
		border-radius: var(--radius-sm);
		transition: color var(--transition-fast), background var(--transition-fast);
	}

	.btn-icon-remove:hover {
		color: var(--red);
		background: rgba(239, 68, 68, 0.1);
	}

	/* API Keys section */
	.api-keys-section {
		margin-bottom: var(--space-lg);
		padding-bottom: var(--space-lg);
		border-bottom: 1px solid var(--border-muted);
	}

	.api-keys-section:last-of-type {
		border-bottom: none;
		margin-bottom: 0;
		padding-bottom: 0;
	}

	.api-keys-section-title {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-bottom: var(--space-md);
	}

	.label-with-badge {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.label-with-badge .label {
		margin-bottom: 0;
	}

	.badge {
		font-size: var(--text-xs);
		font-weight: 600;
		padding: 1px 8px;
		border-radius: var(--radius-full);
		white-space: nowrap;
	}

	.badge-configured {
		background: rgba(34, 197, 94, 0.15);
		color: var(--green, #22c55e);
		border: 1px solid rgba(34, 197, 94, 0.3);
	}

	.smtp-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: var(--space-md);
	}

	.smtp-sender-full {
		grid-column: 1 / -1;
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

		.smtp-grid {
			grid-template-columns: 1fr;
		}
	}

	/* Capture tab */
	.capture-status-card {
		background: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md, 8px);
		padding: var(--space-md);
	}

	.capture-status-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.capture-badge {
		font-size: var(--text-sm);
		padding: var(--space-xs) var(--space-sm);
		border-radius: var(--radius-sm, 4px);
		font-weight: 500;
	}
	.capture-badge.status-running {
		background: var(--green-dim);
		color: var(--green);
	}
	.capture-badge.status-stopped {
		background: var(--red-dim);
		color: var(--red);
	}

	.capture-toggle-row {
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	.capture-toggle-label {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	.capture-toggle-switch {
		position: relative;
		width: 44px;
		height: 24px;
		border-radius: 12px;
		border: 1px solid var(--border-default);
		background: var(--bg-tertiary);
		cursor: pointer;
		transition: background 0.2s, border-color 0.2s;
		padding: 0;
		flex-shrink: 0;
		color: var(--text-primary);
	}
	.capture-toggle-switch.on {
		background: var(--green-dim);
		border-color: var(--green);
	}
	.capture-toggle-switch:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.capture-toggle-knob {
		position: absolute;
		top: 2px;
		left: 2px;
		width: 18px;
		height: 18px;
		border-radius: 50%;
		background: var(--text-secondary);
		transition: transform 0.2s, background 0.2s;
	}
	.capture-toggle-switch.on .capture-toggle-knob {
		transform: translateX(20px);
		background: var(--green);
	}
	.capture-toggle-knob.loading {
		animation: capture-pulse 0.8s ease-in-out infinite;
	}

	@keyframes capture-pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.4; }
	}

	/* Manual Data Cleanup */
	.cleanup-input-row {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		margin-bottom: var(--space-md);
		flex-wrap: wrap;
	}

	.cleanup-label {
		color: var(--text-secondary);
		font-size: var(--text-sm);
		white-space: nowrap;
	}

	.cleanup-preview {
		background: var(--bg-tertiary);
		border: 1px solid var(--border);
		border-radius: var(--radius-md);
		padding: var(--space-md);
		margin-top: var(--space-sm);
	}

	.cleanup-preview-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: var(--space-md);
	}

	.cleanup-preview-title {
		font-weight: 600;
		color: var(--text-primary);
	}

	.cleanup-stats {
		display: flex;
		gap: var(--space-lg);
		margin-bottom: var(--space-md);
	}

	.cleanup-stat {
		display: flex;
		flex-direction: column;
		align-items: center;
	}

	.cleanup-stat-value {
		font-size: var(--text-xl);
		font-weight: 700;
		color: var(--text-primary);
	}

	.cleanup-stat-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.cleanup-confirm-section {
		border-top: 1px solid var(--border);
		padding-top: var(--space-md);
		margin-top: var(--space-sm);
	}

	.cleanup-actions {
		display: flex;
		gap: var(--space-sm);
	}

	.cleanup-final-confirm {
		background: var(--bg-secondary);
		border: 1px solid var(--red);
		border-radius: var(--radius-md);
		padding: var(--space-md);
	}

	/* Retention Health Card */
	.retention-health-card {
		margin-bottom: var(--space-lg);
	}

	.health-badge {
		display: inline-flex;
		align-items: center;
		gap: var(--space-xs);
		font-size: var(--text-sm);
		font-weight: 600;
		padding: 2px var(--space-sm);
		border-radius: var(--radius-full);
	}

	.health-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
	}

	.health-healthy {
		color: var(--green);
		background: var(--green-dim);
	}
	.health-healthy .health-dot {
		background: var(--green);
		box-shadow: 0 0 6px var(--green);
	}

	.health-attention {
		color: var(--amber);
		background: var(--amber-dim);
	}
	.health-attention .health-dot {
		background: var(--amber);
		box-shadow: 0 0 6px var(--amber);
	}

	.health-problem {
		color: var(--red);
		background: var(--red-dim);
	}
	.health-problem .health-dot {
		background: var(--red);
		box-shadow: 0 0 6px var(--red);
	}

	.health-rows {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.health-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-xs) 0;
	}

	.health-row + .health-row {
		border-top: 1px solid var(--border-dim);
	}

	.health-label {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	.health-value {
		font-size: var(--text-sm);
		display: flex;
		align-items: center;
		gap: var(--space-xs);
	}
</style>
