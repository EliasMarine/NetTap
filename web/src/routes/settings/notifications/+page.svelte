<script lang="ts">
	/**
	 * Notification Settings — Configure email, webhook, and in-app notification channels.
	 *
	 * Reads current config from environment defaults and allows the user to
	 * test and save notification preferences.
	 */

	// Notification config form state
	let emailEnabled = $state(false);
	let smtpHost = $state('');
	let smtpPort = $state(587);
	let smtpUser = $state('');
	let smtpPass = $state('');
	let smtpFrom = $state('nettap@localhost');
	let notifyEmail = $state('');

	let webhookEnabled = $state(false);
	let webhookUrl = $state('');

	let inAppEnabled = $state(true);
	let severityThreshold = $state(3);

	let saving = $state(false);
	let testing = $state(false);
	let saveMessage = $state('');
	let testMessage = $state('');

	// Load current config on mount
	$effect(() => {
		loadConfig();
	});

	async function loadConfig() {
		try {
			const res = await fetch('/api/notifications/config');
			if (res.ok) {
				const data = await res.json();
				emailEnabled = data.email?.enabled ?? false;
				smtpHost = data.email?.smtpHost ?? '';
				smtpPort = data.email?.smtpPort ?? 587;
				smtpUser = data.email?.smtpUser ?? '';
				smtpFrom = data.email?.smtpFrom ?? 'nettap@localhost';
				notifyEmail = data.email?.recipients?.join(', ') ?? '';
				webhookEnabled = data.webhook?.enabled ?? false;
				webhookUrl = data.webhook?.url ?? '';
				inAppEnabled = data.inApp?.enabled ?? true;
				severityThreshold = data.severityThreshold ?? 3;
			}
		} catch {
			// Config endpoint may not exist yet; use defaults
		}
	}

	async function saveConfig() {
		saving = true;
		saveMessage = '';
		try {
			const res = await fetch('/api/notifications/config', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					email: {
						enabled: emailEnabled,
						recipients: notifyEmail.split(',').map((s) => s.trim()).filter(Boolean),
						smtpHost,
						smtpPort,
						smtpUser,
						smtpPass: smtpPass || undefined,
						smtpFrom,
					},
					webhook: {
						enabled: webhookEnabled,
						url: webhookUrl,
					},
					inApp: {
						enabled: inAppEnabled,
					},
					severityThreshold,
				}),
			});

			if (res.ok) {
				saveMessage = 'Notification settings saved successfully.';
			} else {
				const data = await res.json().catch(() => ({}));
				saveMessage = data.error || 'Failed to save settings.';
			}
		} catch {
			saveMessage = 'Failed to connect to server.';
		} finally {
			saving = false;
		}
	}

	async function sendTestNotification() {
		testing = true;
		testMessage = '';
		try {
			const res = await fetch('/api/notifications/test', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					email: emailEnabled
						? {
								recipients: notifyEmail.split(',').map((s) => s.trim()).filter(Boolean),
								smtpHost,
								smtpPort,
								smtpUser,
								smtpPass: smtpPass || undefined,
								smtpFrom,
							}
						: undefined,
					webhook: webhookEnabled
						? { url: webhookUrl }
						: undefined,
				}),
			});

			if (res.ok) {
				testMessage = 'Test notification sent successfully.';
			} else {
				const data = await res.json().catch(() => ({}));
				testMessage = data.error || 'Test notification failed.';
			}
		} catch {
			testMessage = 'Failed to send test notification.';
		} finally {
			testing = false;
		}
	}

	function severityLabel(level: number): string {
		switch (level) {
			case 1: return 'Critical only';
			case 2: return 'High and above';
			case 3: return 'Medium and above';
			case 4: return 'All (including Low)';
			default: return 'Medium and above';
		}
	}
</script>

<svelte:head>
	<title>Notification Settings | NetTap</title>
</svelte:head>

<div class="notification-settings">
	<div class="settings-header">
		<div class="header-with-back">
			<a href="/settings" class="back-link">
				<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<polyline points="15 18 9 12 15 6" />
				</svg>
				Settings
			</a>
		</div>
		<h2>Notification Settings</h2>
		<p class="text-muted">Configure how and when you receive alerts from NetTap.</p>
	</div>

	{#if saveMessage}
		<div class="alert {saveMessage.includes('success') ? 'alert-success' : 'alert-danger'}">
			{saveMessage}
		</div>
	{/if}

	<!-- Severity Threshold -->
	<div class="card settings-section">
		<div class="card-header">
			<span class="card-title">Severity Threshold</span>
		</div>
		<p class="section-description">Only send external notifications (email, webhook) for alerts at or above this severity level. In-app notifications are always stored.</p>
		<div class="form-group">
			<label class="label" for="severity-threshold">Minimum Severity</label>
			<select class="input" id="severity-threshold" bind:value={severityThreshold}>
				<option value={1}>Critical only (severity 1)</option>
				<option value={2}>High and above (severity 1-2)</option>
				<option value={3}>Medium and above (severity 1-3)</option>
				<option value={4}>All notifications (severity 1-4)</option>
			</select>
			<p class="field-help">Current: {severityLabel(severityThreshold)}</p>
		</div>
	</div>

	<!-- In-App Notifications -->
	<div class="card settings-section">
		<div class="card-header">
			<span class="card-title">In-App Notifications</span>
			<label class="toggle-label">
				<input type="checkbox" bind:checked={inAppEnabled} class="toggle-input" />
				<span class="toggle-switch"></span>
			</label>
		</div>
		<p class="section-description">
			Display notifications in the dashboard bell icon. Stored locally on the appliance.
		</p>
	</div>

	<!-- Email Notifications -->
	<div class="card settings-section">
		<div class="card-header">
			<span class="card-title">Email Notifications</span>
			<label class="toggle-label">
				<input type="checkbox" bind:checked={emailEnabled} class="toggle-input" />
				<span class="toggle-switch"></span>
			</label>
		</div>
		{#if emailEnabled}
			<div class="email-fields">
				<div class="smtp-grid">
					<div class="form-group">
						<label class="label" for="smtp-host">SMTP Host</label>
						<input class="input" id="smtp-host" type="text" bind:value={smtpHost} placeholder="smtp.gmail.com" />
					</div>
					<div class="form-group">
						<label class="label" for="smtp-port">SMTP Port</label>
						<input class="input" id="smtp-port" type="number" bind:value={smtpPort} min={1} max={65535} />
					</div>
				</div>
				<div class="smtp-grid">
					<div class="form-group">
						<label class="label" for="smtp-user">SMTP Username</label>
						<input class="input" id="smtp-user" type="text" bind:value={smtpUser} placeholder="user@example.com" />
					</div>
					<div class="form-group">
						<label class="label" for="smtp-pass">SMTP Password</label>
						<input class="input" id="smtp-pass" type="password" bind:value={smtpPass} placeholder="App password" />
						<p class="field-help">Leave blank to keep existing password.</p>
					</div>
				</div>
				<div class="form-group">
					<label class="label" for="smtp-from">From Address</label>
					<input class="input" id="smtp-from" type="email" bind:value={smtpFrom} placeholder="nettap@yourdomain.com" />
				</div>
				<div class="form-group">
					<label class="label" for="notify-email">Recipient Email(s)</label>
					<input class="input" id="notify-email" type="text" bind:value={notifyEmail} placeholder="admin@example.com, backup@example.com" />
					<p class="field-help">Comma-separated list of email addresses to notify.</p>
				</div>
			</div>
		{:else}
			<p class="section-description">
				Send alert notifications via email. Enable to configure SMTP settings.
			</p>
		{/if}
	</div>

	<!-- Webhook Notifications -->
	<div class="card settings-section">
		<div class="card-header">
			<span class="card-title">Webhook Notifications</span>
			<label class="toggle-label">
				<input type="checkbox" bind:checked={webhookEnabled} class="toggle-input" />
				<span class="toggle-switch"></span>
			</label>
		</div>
		{#if webhookEnabled}
			<div class="form-group">
				<label class="label" for="webhook-url">Webhook URL</label>
				<input class="input mono" id="webhook-url" type="url" bind:value={webhookUrl} placeholder="https://hooks.slack.com/services/..." />
				<p class="field-help">POST request with JSON payload will be sent to this URL for each notification.</p>
			</div>
		{:else}
			<p class="section-description">
				Send notifications to a webhook endpoint (e.g. Slack, Discord, custom HTTP endpoint).
			</p>
		{/if}
	</div>

	<!-- Actions -->
	<div class="actions-row">
		<button class="btn btn-primary" onclick={saveConfig} disabled={saving}>
			{saving ? 'Saving...' : 'Save Settings'}
		</button>
		<button class="btn btn-secondary" onclick={sendTestNotification} disabled={testing}>
			{testing ? 'Sending...' : 'Send Test Notification'}
		</button>
	</div>

	{#if testMessage}
		<div class="alert {testMessage.includes('success') ? 'alert-success' : 'alert-danger'}">
			{testMessage}
		</div>
	{/if}
</div>

<style>
	.notification-settings {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
		max-width: 720px;
	}

	.settings-header h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		margin-bottom: var(--space-xs);
	}

	.header-with-back {
		margin-bottom: var(--space-sm);
	}

	.back-link {
		display: inline-flex;
		align-items: center;
		gap: var(--space-xs);
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	.back-link:hover {
		color: var(--text-primary);
		text-decoration: none;
	}

	.settings-section {
		padding: var(--space-lg);
	}

	.section-description {
		font-size: var(--text-sm);
		color: var(--text-secondary);
		margin-bottom: var(--space-md);
	}

	.field-help {
		font-size: var(--text-xs);
		color: var(--text-muted);
		margin-top: var(--space-xs);
	}

	.smtp-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-md);
	}

	.email-fields {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	/* Toggle switch */
	.toggle-label {
		display: flex;
		align-items: center;
		cursor: pointer;
	}

	.toggle-input {
		position: absolute;
		opacity: 0;
		width: 0;
		height: 0;
	}

	.toggle-switch {
		position: relative;
		width: 40px;
		height: 22px;
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-full);
		transition: all var(--transition-fast);
	}

	.toggle-switch::after {
		content: '';
		position: absolute;
		top: 2px;
		left: 2px;
		width: 16px;
		height: 16px;
		background-color: var(--text-muted);
		border-radius: 50%;
		transition: all var(--transition-fast);
	}

	.toggle-input:checked + .toggle-switch {
		background-color: var(--accent-muted);
		border-color: var(--accent);
	}

	.toggle-input:checked + .toggle-switch::after {
		transform: translateX(18px);
		background-color: var(--accent);
	}

	/* Actions */
	.actions-row {
		display: flex;
		gap: var(--space-md);
	}

	@media (max-width: 640px) {
		.smtp-grid {
			grid-template-columns: 1fr;
		}

		.actions-row {
			flex-direction: column;
		}
	}
</style>
