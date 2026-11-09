<script lang="ts">
	/**
	 * Notification Settings — Multi-channel notification management.
	 *
	 * Supports 6 channel types: Email (SMTP), Discord, Slack, Telegram,
	 * Pushover, and Webhook. Includes routing rules engine and delivery log.
	 */

	import { onDestroy, onMount } from 'svelte';
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
	import { registerPageRefresh, type LoadGuard, type LoadResult, outcome } from '$lib/stores/pageRefresh';
	import type { SeverityLevel } from '$lib/utils/severity';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import { formatTime } from '$lib/utils/time';

	// State
	let channels = $state<NotificationChannel[]>([]);
	let rules = $state<RoutingRule[]>([]);
	let deliveryLog = $state<DeliveryLogEntry[]>([]);
	// OLD CODE START — the whole page hid behind one loading card on every reload; each card now
	// shows its own loading state, once, until the first load lands
	// let loading = $state(true);
	// OLD CODE END
	let loaded = $state(false);
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
	// OLD CODE START — NET-224: every SMTP field looked required; blank now uses the server in API keys
	// const channelTypeConfigs: Record<string, { label: string; fields: { key: string; label: string; type: string; placeholder: string }[] }> = {
	// 	email: {
	// 		label: 'Email (SMTP)',
	// 		fields: [
	// 			{ key: 'smtp_host', label: 'SMTP host', type: 'text', placeholder: 'smtp.gmail.com' },
	// 			{ key: 'smtp_port', label: 'SMTP port', type: 'number', placeholder: '587' },
	// 			{ key: 'smtp_user', label: 'SMTP username', type: 'text', placeholder: 'user@example.com' },
	// 			{ key: 'smtp_pass', label: 'SMTP password', type: 'password', placeholder: 'App password' },
	// 			{ key: 'from_address', label: 'From address', type: 'email', placeholder: 'nettap@yourdomain.com' },
	// 			{ key: 'recipients', label: 'Recipients (comma-separated)', type: 'text', placeholder: 'admin@example.com, ops@example.com' },
	// 		],
	// 	},
	// OLD CODE END
	const channelTypeConfigs: Record<string, { label: string; help?: string; fields: { key: string; label: string; type: string; placeholder: string }[] }> = {
		email: {
			label: 'Email (SMTP)',
			help: 'Leave the server fields blank to use the SMTP server saved in Settings › API keys.',
			fields: [
				{ key: 'recipients', label: 'Recipients (comma-separated)', type: 'text', placeholder: 'admin@example.com, ops@example.com' },
				{ key: 'smtp_host', label: 'SMTP host (optional)', type: 'text', placeholder: 'Blank uses API keys' },
				{ key: 'smtp_port', label: 'SMTP port (optional)', type: 'number', placeholder: '587' },
				{ key: 'smtp_user', label: 'SMTP username (optional)', type: 'text', placeholder: 'user@example.com' },
				{ key: 'smtp_pass', label: 'SMTP password (optional)', type: 'password', placeholder: 'App password' },
				{ key: 'from_address', label: 'From address (optional)', type: 'email', placeholder: 'nettap@yourdomain.com' },
			],
		},
		discord: {
			label: 'Discord',
			fields: [
				{ key: 'webhook_url', label: 'Webhook URL', type: 'url', placeholder: 'https://discord.com/api/webhooks/…' },
			],
		},
		slack: {
			label: 'Slack',
			fields: [
				{ key: 'webhook_url', label: 'Webhook URL', type: 'url', placeholder: 'https://hooks.slack.com/services/…' },
			],
		},
		telegram: {
			label: 'Telegram',
			fields: [
				{ key: 'bot_token', label: 'Bot token', type: 'text', placeholder: '123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11' },
				{ key: 'chat_id', label: 'Chat ID', type: 'text', placeholder: '-1001234567890' },
			],
		},
		pushover: {
			label: 'Pushover',
			fields: [
				{ key: 'user_key', label: 'User key', type: 'text', placeholder: 'your-user-key' },
				{ key: 'api_token', label: 'API token', type: 'text', placeholder: 'your-api-token' },
			],
		},
		webhook: {
			label: 'Generic webhook',
			fields: [
				{ key: 'url', label: 'Webhook URL', type: 'url', placeholder: 'https://your-server.com/webhook' },
			],
		},
	};

	// Labels for every event type a stored rule can name
	const eventTypes = [
		{ value: 'new_device', label: 'New device' },
		{ value: 'alert', label: 'Alert' },
		{ value: 'anomaly', label: 'Anomaly' },
		{ value: 'storage_warning', label: 'Storage warning' },
		{ value: 'smart_warning', label: 'SMART warning' },
		{ value: 'capture_error', label: 'Capture error' },
		{ value: 'system_error', label: 'System error' },
	];
	// NET-224: only alerts have a sender (the daemon's dispatcher); a rule for the others never fired
	// OLD CODE: the rule form offered every entry of eventTypes
	const ruleEventTypes = eventTypes.filter((e) => e.value === 'alert');

	// OLD CODE START — the page refresh contract (PLAN §5.5): every load goes through refresh.run()
	// // Load data on mount
	// $effect(() => {
	// 	loadAll();
	// });
	// OLD CODE END

	// #96: which section's last load failed (a failed request is not "none configured")
	let failed = $state({ channels: false, rules: false, log: false });

	// OLD CODE START — the page refresh contract (PLAN §5.5): a guarded loader that reports what loaded
	// async function loadAll() {
	// 	loading = true;
	// 	const [chRes, ruRes, logRes] = await Promise.allSettled([
	// 		getChannels(),
	// 		getRules(),
	// 		getDeliveryLog(),
	// 	]);
	// 	// A failed reload keeps the last list it had and marks it stale
	// 	if (chRes.status === 'fulfilled') channels = chRes.value.channels;
	// 	if (ruRes.status === 'fulfilled') rules = ruRes.value.rules;
	// 	if (logRes.status === 'fulfilled') deliveryLog = logRes.value.log;
	// 	failed = {
	// 		channels: chRes.status === 'rejected',
	// 		rules: ruRes.status === 'rejected',
	// 		log: logRes.status === 'rejected',
	// 	};
	// 	loading = false;
	// }
	// OLD CODE END
	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const results = await Promise.allSettled([getChannels(), getRules(), getDeliveryLog()]);
		if (!guard.current(g)) return 'skipped';
		const [chRes, ruRes, logRes] = results;
		// A failed reload keeps the last list it had and marks it stale
		if (chRes.status === 'fulfilled') channels = chRes.value.channels;
		if (ruRes.status === 'fulfilled') rules = ruRes.value.rules;
		if (logRes.status === 'fulfilled') deliveryLog = logRes.value.log;
		failed = {
			channels: chRes.status === 'rejected',
			rules: ruRes.status === 'rejected',
			log: logRes.status === 'rejected',
		};
		loaded = true;
		// OLD CODE START — counted by hand; outcome() in pageRefresh is the shared rule
		// const failures = results.filter((r) => r.status === 'rejected').length;
		// return failures === 0 ? 'ok' : failures === results.length ? 'failed' : 'partial';
		// OLD CODE END
		return outcome(results);
	}

	const refresh = registerPageRefresh(load);
	onDestroy(refresh.unregister);
	onMount(() => void refresh.run());

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
		// OLD CODE: if (result) { … } else { showMessage('Failed to create channel.', 'error'); } (NET-224: no reason)
		if (result.ok) {
			showMessage(`Channel "${newChannelName}" created.`, 'success');
			showAddForm = false;
			newChannelName = '';
			newChannelConfig = {};
			await refresh.run();
		} else {
			showMessage(`Couldn't create the channel: ${result.error}.`, 'error');
		}
		addingChannel = false;
	}

	async function handleDeleteChannel(id: string) {
		if (await deleteChannel(id)) {
			showMessage('Channel deleted.', 'success');
			await refresh.run();
		} else {
			showMessage('Failed to delete channel.', 'error');
		}
	}

	async function handleTestChannel(id: string) {
		testingChannelId = id;
		// OLD CODE START — NET-224: a failed test had no reason, and only the log was reloaded
		// const success = await testChannel(id);
		// if (success) {
		// 	showMessage('Test notification sent successfully.', 'success');
		// } else {
		// 	showMessage('Test notification failed.', 'error');
		// }
		// testingChannelId = '';
		// // Refresh delivery log
		// // OLD CODE START — #96: getDeliveryLog now throws on failure
		// // const logRes = await getDeliveryLog();
		// // deliveryLog = logRes.log;
		// // OLD CODE END
		// try {
		// 	deliveryLog = (await getDeliveryLog()).log;
		// 	failed = { ...failed, log: false };
		// } catch {
		// 	failed = { ...failed, log: true };
		// }
		// OLD CODE END
		const result = await testChannel(id);
		if (result.success) {
			showMessage('Test notification sent.', 'success');
		} else {
			showMessage(`The test didn't go through${result.error ? `: ${result.error}` : ''}.`, 'error');
		}
		testingChannelId = '';
		// the channel's last delivery and the log both changed
		await refresh.run();
	}

	// Rule actions
	async function handleAddRule() {
		addingRule = true;
		const result = await createRule(newRuleEventType, newRuleChannels, newRuleSeverity);
		// OLD CODE: if (result) { … } else { showMessage('Failed to create rule.', 'error'); } (NET-224: no reason)
		if (result.ok) {
			showMessage('Routing rule created.', 'success');
			showRuleForm = false;
			newRuleChannels = [];
			await refresh.run();
		} else {
			showMessage(`Couldn't create the rule: ${result.error}.`, 'error');
		}
		addingRule = false;
	}

	async function handleDeleteRule(id: string) {
		if (await deleteRule(id)) {
			showMessage('Rule deleted.', 'success');
			await refresh.run();
		} else {
			showMessage('Failed to delete rule.', 'error');
		}
	}

	function channelTypeBadge(type: string): string {
		return channelTypeConfigs[type]?.label ?? type;
	}

	// OLD CODE START — severity is shown as a SeverityPill (colour, shape and word); unknown levels keep the text
	// function severityLabel(level: number): string {
	// 	switch (level) {
	// 		case 1: return 'Critical';
	// 		case 2: return 'High';
	// 		case 3: return 'Medium';
	// 		case 4: return 'Low';
	// 		default: return `Severity ${level}`;
	// 	}
	// }
	// OLD CODE END
	const SEVERITY: Record<number, SeverityLevel> = { 1: 'critical', 2: 'high', 3: 'medium', 4: 'low' };

	function toggleRuleChannel(chId: string) {
		if (newRuleChannels.includes(chId)) {
			newRuleChannels = newRuleChannels.filter(c => c !== chId);
		} else {
			newRuleChannels = [...newRuleChannels, chId];
		}
	}

	/** A count, or '—' when its list failed to load and there is nothing earlier to show (#96). */
	function countLabel(failedLoad: boolean, n: number, unit: string): string {
		return failedLoad && n === 0 ? `— ${unit}s` : `${n} ${unit}${n === 1 ? '' : 's'}`;
	}

	// The log has no id; its position in the reply keys the row
	const logRows = $derived(deliveryLog.slice(0, 20).map((entry, i) => ({ ...entry, key: i })));
	type LogRow = (typeof logRows)[number];
	const logColumns: Column<LogRow>[] = [
		{ key: 'success', label: 'Result', cell: resultCell, sortValue: (r) => (r.success ? 1 : 0) },
		{ key: 'channel_type', label: 'Channel', cell: channelCell },
		{ key: 'title', label: 'Notification' },
		{ key: 'timestamp', label: 'Sent at', cell: timeCell, sortValue: (r) => Date.parse(r.timestamp) || 0 },
	];
</script>

{#snippet resultCell(entry: LogRow)}
	<span class={['res', entry.success ? 'is-live' : 'is-high']}>{entry.success ? 'Sent' : 'Failed'}</span>
{/snippet}
{#snippet channelCell(entry: LogRow)}<span class="tag">{entry.channel_type}</span>{/snippet}
{#snippet timeCell(entry: LogRow)}<span class="num">{formatTime(entry.timestamp)}</span>{/snippet}

<svelte:head>
	<title>Notifications | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a class="back" href="/settings"><Icon name="back" />Settings</a>
		<h1 class="page-title">Notifications</h1>
		<p class="page-sub">Where NetTap sends its notifications, and which events go to which channel</p>
	</div>
</div>

{#if message}
	<div class={['notice', messageType === 'success' ? 'is-ok' : 'is-error']} role={messageType === 'success' ? 'status' : 'alert'}>
		<Icon name={messageType === 'success' ? 'check' : 'warn'} />{message}
	</div>
{/if}

<div class="grid">
	<Card title="Notification channels" sub={countLabel(failed.channels, channels.length, 'channel')} class="c-6">
		{#snippet actions()}
			<button class={['btn', !showAddForm && 'primary']} type="button" onclick={() => (showAddForm = !showAddForm)}>
				{showAddForm ? 'Cancel' : 'Add channel'}
			</button>
		{/snippet}

		{#if showAddForm}
			<div class="add-form">
				{#if channelTypeConfigs[newChannelType]?.help}
					<p class="field-help form-help">{channelTypeConfigs[newChannelType].help}</p>
				{/if}
				<div class="form-grid">
					<div class="field">
						<label class="label" for="channel-type">Channel type</label>
						<select class="select" id="channel-type" bind:value={newChannelType}>
							{#each Object.entries(channelTypeConfigs) as [key, cfg]}
								<option value={key}>{cfg.label}</option>
							{/each}
						</select>
					</div>
					<div class="field">
						<label class="label" for="channel-name">Name</label>
						<input class="input" id="channel-name" type="text" bind:value={newChannelName} placeholder="My Discord server" />
					</div>
					{#each channelTypeConfigs[newChannelType]?.fields ?? [] as field}
						<div class="field">
							<label class="label" for="cfg-{field.key}">{field.label}</label>
							<input class="input" id="cfg-{field.key}" type={field.type} bind:value={newChannelConfig[field.key]} placeholder={field.placeholder} />
						</div>
					{/each}
				</div>
				<div class="form-actions">
					<button class="btn primary" type="button" onclick={handleAddChannel} disabled={addingChannel || !newChannelName}>
						{addingChannel ? 'Creating…' : 'Create channel'}
					</button>
				</div>
			</div>
		{/if}

		{#if !loaded}
			<CardState state="loading" title="Loading notification channels" />
		{:else if failed.channels && channels.length === 0}
			<CardState
				state="error"
				title="Couldn't load the notification channels: the request failed."
				message="Check that NetTap is running on the System page, then try again."
				onaction={() => refresh.run()}
			/>
		{:else if channels.length === 0}
			<CardState
				state="empty"
				icon="alerts"
				title="No channels configured"
				message="Add one to start receiving notifications."
			/>
		{:else}
			{#if failed.channels}
				<div class="notice is-warn" role="status"><Icon name="warn" />Couldn't refresh the notification channels: showing the last list.</div>
			{/if}
			<ul class="rows">
				{#each channels as ch}
					<li>
						<span class="row-main">
							<span class="tag">{channelTypeBadge(ch.type)}</span><b>{ch.name}</b>
							{#if ch.enabled === false}<span class="tag">Off</span>{/if}
							{#if ch.last_delivery}
								<span class={['res', ch.last_delivery.ok ? 'is-live' : 'is-high']}>
									{ch.last_delivery.ok ? 'Sent' : 'Failed'} {formatTime(ch.last_delivery.at)}{ch.last_delivery.error ? `: ${ch.last_delivery.error}` : ''}
								</span>
							{/if}
						</span>
						<span class="actions">
							<button class="btn" type="button" onclick={() => handleTestChannel(ch.id)} disabled={testingChannelId === ch.id}>
								{testingChannelId === ch.id ? 'Testing…' : 'Test'}
							</button>
							<button class="btn" type="button" onclick={() => handleDeleteChannel(ch.id)}>Delete</button>
						</span>
					</li>
				{/each}
			</ul>
		{/if}
	</Card>

	<Card title="Routing rules" sub={countLabel(failed.rules, rules.length, 'rule')} class="c-6">
		{#snippet actions()}
			<button
				class={['btn', !showRuleForm && 'primary']}
				type="button"
				onclick={() => (showRuleForm = !showRuleForm)}
				disabled={channels.length === 0}
			>
				{showRuleForm ? 'Cancel' : 'Add rule'}
			</button>
		{/snippet}

		<p class="card-text">Map event types to notification channels with severity filtering.</p>

		{#if showRuleForm}
			<div class="add-form">
				<div class="form-grid">
					<div class="field">
						<label class="label" for="rule-event">Event type</label>
						<select class="select" id="rule-event" bind:value={newRuleEventType}>
							{#each ruleEventTypes as et}
								<option value={et.value}>{et.label}</option>
							{/each}
						</select>
					</div>
					<div class="field">
						<label class="label" for="rule-severity">Minimum severity</label>
						<select class="select" id="rule-severity" bind:value={newRuleSeverity}>
							<option value={1}>Critical only</option>
							<option value={2}>High and above</option>
							<option value={3}>Medium and above</option>
							<option value={4}>All (including low)</option>
						</select>
					</div>
				</div>
				<fieldset class="field channel-picks">
					<legend class="label">Send to channels</legend>
					{#each channels as ch}
						<label class="check-row">
							<input type="checkbox" checked={newRuleChannels.includes(ch.id)} onchange={() => toggleRuleChannel(ch.id)} />
							{ch.name} ({channelTypeBadge(ch.type)})
						</label>
					{/each}
				</fieldset>
				<div class="form-actions">
					<button class="btn primary" type="button" onclick={handleAddRule} disabled={addingRule || newRuleChannels.length === 0}>
						{addingRule ? 'Creating…' : 'Create rule'}
					</button>
				</div>
			</div>
		{/if}

		{#if !loaded}
			<CardState state="loading" title="Loading routing rules" />
		{:else if failed.rules && rules.length === 0}
			<CardState
				state="error"
				title="Couldn't load the routing rules: the request failed."
				message="Check that NetTap is running on the System page, then try again."
				onaction={() => refresh.run()}
			/>
		{:else if rules.length === 0}
			<CardState
				state="empty"
				icon="filter"
				title="No routing rules configured"
				message="Rules send each kind of event to the channels you pick."
			/>
		{:else}
			{#if failed.rules}
				<div class="notice is-warn" role="status"><Icon name="warn" />Couldn't refresh the routing rules: showing the last list.</div>
			{/if}
			<ul class="rows">
				{#each rules as rule}
					<li>
						<span class="row-main">
							<span class="tag">{eventTypes.find(e => e.value === rule.event_type)?.label ?? rule.event_type}</span>
							<span>to {rule.channels.length} channel{rule.channels.length !== 1 ? 's' : ''} · minimum</span>
							{#if SEVERITY[rule.min_severity]}
								<SeverityPill level={SEVERITY[rule.min_severity]} />
							{:else}
								<span>severity {rule.min_severity}</span>
							{/if}
						</span>
						<button class="btn" type="button" onclick={() => handleDeleteRule(rule.id)}>Delete</button>
					</li>
				{/each}
			</ul>
		{/if}
	</Card>

	<Card title="Recent deliveries" sub="Up to 20 delivery attempts, as NetTap reports them" class="c-12">
		{#if !loaded}
			<CardState state="loading" title="Loading delivery log" />
		{:else if failed.log && deliveryLog.length === 0}
			<CardState
				state="error"
				title="Couldn't load the delivery log: the request failed."
				message="Check that NetTap is running on the System page, then try again."
				onaction={() => refresh.run()}
			/>
		{:else if deliveryLog.length === 0}
			<CardState
				state="empty"
				icon="logs"
				title="No delivery attempts yet"
				message="Each notification NetTap sends, and each test, appears here."
			/>
		{:else}
			{#if failed.log}
				<div class="notice is-warn" role="status"><Icon name="warn" />Couldn't refresh the delivery log: showing the last entries.</div>
			{/if}
			<DataTable columns={logColumns} rows={logRows} ariaLabel="Recent notification deliveries" rowKey={(r) => r.key} />
		{/if}
	</Card>
</div>

<style>
	.card-text { color: var(--text-2); font-size: var(--text-sm); margin-bottom: var(--sp-4); }
	.add-form { padding: var(--sp-4); margin-bottom: var(--sp-4); border-radius: var(--r-md); background: var(--surface-2); border: 1px solid var(--line); }
	.channel-picks { border: 0; padding: 0; margin: var(--sp-4) 0 0; gap: var(--sp-2); }
	.rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
	.rows li { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); flex-wrap: wrap; padding: var(--sp-3) 0; font-size: var(--text-sm); }
	.rows li + li { border-top: 1px solid var(--line); }
	.row-main { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; min-width: 0; color: var(--text-2); }
	.row-main b { color: var(--text-1); }
	.notice { margin-bottom: var(--sp-3); }
	.form-help { margin: 0 0 var(--sp-3); }
</style>
