<script lang="ts">
	/**
	 * Notification Settings — Multi-channel notification management.
	 *
	 * Supports 6 channel types: Email (SMTP), Discord, Slack, Telegram,
	 * Pushover, and Webhook. Includes routing rules engine and delivery log.
	 */

	import {
		getChannels,
		createChannel,
		deleteChannel,
		testChannel,
		getDeliveryLog,
		getRules,
		createRule,
		deleteRule,
		type NotificationChannel,
		type RoutingRule,
		type DeliveryLogEntry,
	} from '$lib/api/notification-hub';

	// State
	let channels = $state<NotificationChannel[]>([]);
	let rules = $state<RoutingRule[]>([]);
	let deliveryLog = $state<DeliveryLogEntry[]>([]);
	let loading = $state(true);
	let message = $state('');
	let messageType = $state<'success' | 'error'>('success');

	// Add channel form
	let showAddForm = $state(false);
	let newChannelType = $state<string>('discord');
	let newChannelName = $state('');
	let newChannelConfig = $state<Record<string, string>>({});
	let addingChannel = $state(false);

	// Add rule form
	let showRuleForm = $state(false);
	let newRuleEventType = $state('alert');
	let newRuleChannels = $state<string[]>([]);
	let newRuleSeverity = $state(3);
	let addingRule = $state(false);

	// Testing state
	let testingChannelId = $state('');

	// Channel type configs
	const channelTypeConfigs: Record<string, { label: string; fields: { key: string; label: string; type: string; placeholder: string }[] }> = {
		email: {
			label: 'Email (SMTP)',
			fields: [
				{ key: 'smtp_host', label: 'SMTP Host', type: 'text', placeholder: 'smtp.gmail.com' },
				{ key: 'smtp_port', label: 'SMTP Port', type: 'number', placeholder: '587' },
				{ key: 'smtp_user', label: 'SMTP Username', type: 'text', placeholder: 'user@example.com' },
				{ key: 'smtp_pass', label: 'SMTP Password', type: 'password', placeholder: 'App password' },
				{ key: 'from_address', label: 'From Address', type: 'email', placeholder: 'nettap@yourdomain.com' },
				{ key: 'recipients', label: 'Recipients (comma-separated)', type: 'text', placeholder: 'admin@example.com, ops@example.com' },
			],
		},
		discord: {
			label: 'Discord',
			fields: [
				{ key: 'webhook_url', label: 'Webhook URL', type: 'url', placeholder: 'https://discord.com/api/webhooks/...' },
			],
		},
		slack: {
			label: 'Slack',
			fields: [
				{ key: 'webhook_url', label: 'Webhook URL', type: 'url', placeholder: 'https://hooks.slack.com/services/...' },
			],
		},
		telegram: {
			label: 'Telegram',
			fields: [
				{ key: 'bot_token', label: 'Bot Token', type: 'text', placeholder: '123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11' },
				{ key: 'chat_id', label: 'Chat ID', type: 'text', placeholder: '-1001234567890' },
			],
		},
		pushover: {
			label: 'Pushover',
			fields: [
				{ key: 'user_key', label: 'User Key', type: 'text', placeholder: 'your-user-key' },
				{ key: 'api_token', label: 'API Token', type: 'text', placeholder: 'your-api-token' },
			],
		},
		webhook: {
			label: 'Generic Webhook',
			fields: [
				{ key: 'url', label: 'Webhook URL', type: 'url', placeholder: 'https://your-server.com/webhook' },
			],
		},
	};

	const eventTypes = [
		{ value: 'new_device', label: 'New Device' },
		{ value: 'alert', label: 'Alert' },
		{ value: 'anomaly', label: 'Anomaly' },
		{ value: 'storage_warning', label: 'Storage Warning' },
		{ value: 'smart_warning', label: 'SMART Warning' },
		{ value: 'capture_error', label: 'Capture Error' },
		{ value: 'system_error', label: 'System Error' },
	];

	// Load data on mount
	$effect(() => {
		loadAll();
	});

	async function loadAll() {
		loading = true;
		const [chRes, ruRes, logRes] = await Promise.all([
			getChannels(),
			getRules(),
			getDeliveryLog(),
		]);
		channels = chRes.channels;
		rules = ruRes.rules;
		deliveryLog = logRes.log;
		loading = false;
	}

	function showMessage(msg: string, type: 'success' | 'error') {
		message = msg;
		messageType = type;
		setTimeout(() => { message = ''; }, 5000);
	}

	// Channel actions
	async function handleAddChannel() {
		addingChannel = true;
		const config = { ...newChannelConfig };
		// Convert recipients to array for email
		if (newChannelType === 'email' && config.recipients) {
			(config as Record<string, unknown>).recipients = config.recipients.split(',').map((s: string) => s.trim()).filter(Boolean);
		}
		const result = await createChannel(newChannelType, newChannelName, config);
		if (result) {
			showMessage(`Channel "${newChannelName}" created.`, 'success');
			showAddForm = false;
			newChannelName = '';
			newChannelConfig = {};
			await loadAll();
		} else {
			showMessage('Failed to create channel.', 'error');
		}
		addingChannel = false;
	}

	async function handleDeleteChannel(id: string) {
		if (await deleteChannel(id)) {
			showMessage('Channel deleted.', 'success');
			await loadAll();
		} else {
			showMessage('Failed to delete channel.', 'error');
		}
	}

	async function handleTestChannel(id: string) {
		testingChannelId = id;
		const success = await testChannel(id);
		if (success) {
			showMessage('Test notification sent successfully.', 'success');
		} else {
			showMessage('Test notification failed.', 'error');
		}
		testingChannelId = '';
		// Refresh delivery log
		const logRes = await getDeliveryLog();
		deliveryLog = logRes.log;
	}

	// Rule actions
	async function handleAddRule() {
		addingRule = true;
		const result = await createRule(newRuleEventType, newRuleChannels, newRuleSeverity);
		if (result) {
			showMessage('Routing rule created.', 'success');
			showRuleForm = false;
			newRuleChannels = [];
			await loadAll();
		} else {
			showMessage('Failed to create rule.', 'error');
		}
		addingRule = false;
	}

	async function handleDeleteRule(id: string) {
		if (await deleteRule(id)) {
			showMessage('Rule deleted.', 'success');
			await loadAll();
		} else {
			showMessage('Failed to delete rule.', 'error');
		}
	}

	function channelTypeBadge(type: string): string {
		return channelTypeConfigs[type]?.label ?? type;
	}

	function severityLabel(level: number): string {
		switch (level) {
			case 1: return 'Critical';
			case 2: return 'High';
			case 3: return 'Medium';
			case 4: return 'Low';
			default: return `Severity ${level}`;
		}
	}

	function toggleRuleChannel(chId: string) {
		if (newRuleChannels.includes(chId)) {
			newRuleChannels = newRuleChannels.filter(c => c !== chId);
		} else {
			newRuleChannels = [...newRuleChannels, chId];
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
		<p class="text-muted">Configure multi-channel notifications and routing rules.</p>
	</div>

	{#if message}
		<div class="alert {messageType === 'success' ? 'alert-success' : 'alert-danger'}">
			{message}
		</div>
	{/if}

	{#if loading}
		<div class="card settings-section">
			<p class="text-muted">Loading notification settings...</p>
		</div>
	{:else}
		<!-- Notification Channels -->
		<div class="card settings-section">
			<div class="card-header">
				<span class="card-title">Notification Channels ({channels.length})</span>
				<button class="btn btn-sm btn-primary" onclick={() => showAddForm = !showAddForm}>
					{showAddForm ? 'Cancel' : '+ Add Channel'}
				</button>
			</div>

			{#if showAddForm}
				<div class="add-form">
					<div class="form-group">
						<label class="label" for="channel-type">Channel Type</label>
						<select class="input" id="channel-type" bind:value={newChannelType}>
							{#each Object.entries(channelTypeConfigs) as [key, cfg]}
								<option value={key}>{cfg.label}</option>
							{/each}
						</select>
					</div>
					<div class="form-group">
						<label class="label" for="channel-name">Name</label>
						<input class="input" id="channel-name" type="text" bind:value={newChannelName} placeholder="My Discord Server" />
					</div>
					{#each channelTypeConfigs[newChannelType]?.fields ?? [] as field}
						<div class="form-group">
							<label class="label" for="cfg-{field.key}">{field.label}</label>
							<input class="input" id="cfg-{field.key}" type={field.type} bind:value={newChannelConfig[field.key]} placeholder={field.placeholder} />
						</div>
					{/each}
					<button class="btn btn-primary" onclick={handleAddChannel} disabled={addingChannel || !newChannelName}>
						{addingChannel ? 'Creating...' : 'Create Channel'}
					</button>
				</div>
			{/if}

			{#if channels.length === 0}
				<p class="text-muted section-description">No channels configured. Add one to start receiving notifications.</p>
			{:else}
				<div class="channel-list">
					{#each channels as ch}
						<div class="channel-item">
							<div class="channel-info">
								<span class="badge badge-{ch.type}">{channelTypeBadge(ch.type)}</span>
								<strong>{ch.name}</strong>
							</div>
							<div class="channel-actions">
								<button class="btn btn-sm btn-secondary" onclick={() => handleTestChannel(ch.id)} disabled={testingChannelId === ch.id}>
									{testingChannelId === ch.id ? 'Testing...' : 'Test'}
								</button>
								<button class="btn btn-sm btn-danger" onclick={() => handleDeleteChannel(ch.id)}>Delete</button>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<!-- Routing Rules -->
		<div class="card settings-section">
			<div class="card-header">
				<span class="card-title">Routing Rules ({rules.length})</span>
				<button class="btn btn-sm btn-primary" onclick={() => showRuleForm = !showRuleForm} disabled={channels.length === 0}>
					{showRuleForm ? 'Cancel' : '+ Add Rule'}
				</button>
			</div>

			<p class="section-description">Map event types to notification channels with severity filtering.</p>

			{#if showRuleForm}
				<div class="add-form">
					<div class="form-group">
						<label class="label" for="rule-event">Event Type</label>
						<select class="input" id="rule-event" bind:value={newRuleEventType}>
							{#each eventTypes as et}
								<option value={et.value}>{et.label}</option>
							{/each}
						</select>
					</div>
					<div class="form-group">
						<label class="label">Send To Channels</label>
						<div class="checkbox-group">
							{#each channels as ch}
								<label class="checkbox-label">
									<input type="checkbox" checked={newRuleChannels.includes(ch.id)} onchange={() => toggleRuleChannel(ch.id)} />
									{ch.name} ({channelTypeBadge(ch.type)})
								</label>
							{/each}
						</div>
					</div>
					<div class="form-group">
						<label class="label" for="rule-severity">Minimum Severity</label>
						<select class="input" id="rule-severity" bind:value={newRuleSeverity}>
							<option value={1}>Critical only</option>
							<option value={2}>High and above</option>
							<option value={3}>Medium and above</option>
							<option value={4}>All (including Low)</option>
						</select>
					</div>
					<button class="btn btn-primary" onclick={handleAddRule} disabled={addingRule || newRuleChannels.length === 0}>
						{addingRule ? 'Creating...' : 'Create Rule'}
					</button>
				</div>
			{/if}

			{#if rules.length === 0}
				<p class="text-muted">No routing rules configured.</p>
			{:else}
				<div class="rules-list">
					{#each rules as rule}
						<div class="rule-item">
							<div class="rule-info">
								<span class="badge">{eventTypes.find(e => e.value === rule.event_type)?.label ?? rule.event_type}</span>
								<span class="rule-arrow">--></span>
								<span class="rule-channels">{rule.channels.length} channel{rule.channels.length !== 1 ? 's' : ''}</span>
								<span class="badge badge-severity">Min: {severityLabel(rule.min_severity)}</span>
							</div>
							<button class="btn btn-sm btn-danger" onclick={() => handleDeleteRule(rule.id)}>Delete</button>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<!-- Delivery Log -->
		<div class="card settings-section">
			<div class="card-header">
				<span class="card-title">Recent Deliveries</span>
			</div>

			{#if deliveryLog.length === 0}
				<p class="text-muted section-description">No delivery attempts yet.</p>
			{:else}
				<div class="log-list">
					{#each deliveryLog.slice(0, 20) as entry}
						<div class="log-entry {entry.success ? 'log-success' : 'log-failure'}">
							<span class="log-status">{entry.success ? 'OK' : 'FAIL'}</span>
							<span class="log-channel">{entry.channel_type}</span>
							<span class="log-title">{entry.title}</span>
							<span class="log-time">{new Date(entry.timestamp).toLocaleString()}</span>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.notification-settings {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
		max-width: 800px;
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

	.add-form {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		padding: var(--space-md);
		background: var(--bg-secondary);
		border-radius: var(--radius-md);
		margin-bottom: var(--space-md);
	}

	/* Channel list */
	.channel-list, .rules-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		margin-top: var(--space-md);
	}

	.channel-item, .rule-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-sm) var(--space-md);
		background: var(--bg-secondary);
		border-radius: var(--radius-md);
		border: 1px solid var(--border-default);
	}

	.channel-info, .rule-info {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.channel-actions {
		display: flex;
		gap: var(--space-xs);
	}

	.badge {
		display: inline-block;
		padding: 2px 8px;
		font-size: var(--text-xs);
		font-weight: 600;
		border-radius: var(--radius-full);
		background: var(--bg-tertiary);
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.badge-severity {
		background: var(--accent-muted);
		color: var(--accent);
	}

	.rule-arrow {
		color: var(--text-muted);
		font-family: monospace;
	}

	.rule-channels {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	/* Checkbox group */
	.checkbox-group {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.checkbox-label {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		font-size: var(--text-sm);
		cursor: pointer;
	}

	/* Delivery log */
	.log-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin-top: var(--space-sm);
	}

	.log-entry {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xs) var(--space-sm);
		font-size: var(--text-sm);
		border-radius: var(--radius-sm);
	}

	.log-success {
		background: color-mix(in srgb, var(--status-success) 10%, transparent);
	}

	.log-failure {
		background: color-mix(in srgb, var(--status-critical) 10%, transparent);
	}

	.log-status {
		font-weight: 700;
		font-size: var(--text-xs);
		min-width: 32px;
	}

	.log-success .log-status { color: var(--status-success); }
	.log-failure .log-status { color: var(--status-critical); }

	.log-channel {
		font-weight: 600;
		min-width: 60px;
		text-transform: uppercase;
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	.log-title {
		flex: 1;
		color: var(--text-primary);
	}

	.log-time {
		color: var(--text-muted);
		font-size: var(--text-xs);
	}

	@media (max-width: 640px) {
		.channel-item, .rule-item {
			flex-direction: column;
			align-items: flex-start;
			gap: var(--space-sm);
		}

		.channel-actions {
			width: 100%;
		}
	}
</style>
