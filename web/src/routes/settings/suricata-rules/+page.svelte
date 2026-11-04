<script lang="ts">
	/**
	 * Suricata Rule Management — IDS rule sources, updates, custom rules.
	 *
	 * Manage rule feeds (ET Open, abuse.ch, tgreen, etc.), trigger updates,
	 * set auto-update schedule, upload custom rules, and configure commercial
	 * license keys (ET Pro, Snort Subscriber).
	 */

	import { onDestroy, onMount } from 'svelte';
	import {
		getRuleSources,
		enableRuleSource,
		disableRuleSource,
		updateRulesNow,
		getRuleStats,
		getUpdateSchedule,
		setUpdateSchedule,
		uploadCustomRules,
		getCustomRules,
		configureCommercial,
		getCommercialConfig,
		getLiveRuleStatus,
		type LiveRuleStatus,
		type RuleSource,
		type RuleStats,
		type UpdateSchedule,
		type CommercialConfig,
	} from '$lib/api/suricata-rules';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import StatStrip from '$lib/components/ui/StatStrip.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';

	// What Suricata really runs (#58). The source toggles, schedule picker, custom rules and
	// commercial keys below are not wired into suricata-update yet, so they are shown as such.
	let live = $state<LiveRuleStatus | null>(null);
	let liveError = $state('');

	// State
	let sources = $state<RuleSource[]>([]);
	let stats = $state<RuleStats | null>(null);
	let schedule = $state<UpdateSchedule>({ interval: 'daily', enabled: true });
	let commercialConfig = $state<CommercialConfig>({ configured: false });
	let lastUpdate = $state<string | null>(null);
	// OLD CODE START — the whole page hid behind one loading line; each card now shows its own
	// loading state until the first load lands
	// let loading = $state(true);
	// OLD CODE END
	let loaded = $state(false);
	let updating = $state(false);
	let message = $state('');
	let messageType = $state<'success' | 'error'>('success');

	// Custom rules
	let customRulesContent = $state('');
	let savingCustomRules = $state(false);

	// Commercial form
	let showCommercialForm = $state(false);
	let commercialType = $state('etpro');
	let commercialKey = $state('');
	let savingCommercial = $state(false);

	// Toggling state (track which source is being toggled)
	let togglingSource = $state('');

	function showMessage(text: string, type: 'success' | 'error' = 'success') {
		message = text;
		messageType = type;
		setTimeout(() => { message = ''; }, 5000);
	}

	function sourceName(url: string): string {
		if (url.includes('emergingthreats.net')) return 'Emerging Threats Open';
		if (url.includes('sslbl.abuse.ch')) return 'abuse.ch SSL Blacklist';
		try {
			return new URL(url).hostname;
		} catch {
			return url;
		}
	}

	function scheduleText(cron: string | null | undefined): string {
		if (cron === '0 0 * * *') return 'Rules refresh automatically every day at 00:00 UTC.';
		if (cron) return `Rules refresh automatically on the cron schedule "${cron}" (UTC).`;
		return 'No automatic refresh is scheduled. Use Update rules now.';
	}

	// #96: custom rules and the commercial key load on their own; a failure says so in its section
	let customFailed = $state(false);
	let commercialFailed = $state(false);

	// OLD CODE START — the page refresh contract (PLAN §5.5): one guarded loader that reports what loaded
	// async function loadLive() {
	// 	try {
	// 		live = await getLiveRuleStatus();
	// 		liveError = '';
	// 	} catch (err) {
	// 		live = null;
	// 		liveError = err instanceof Error ? err.message : 'unknown error';
	// 	}
	// }
	//
	// async function loadData() {
	// 	loading = true;
	// 	await loadLive();
	// 	const [sourcesRes, statsRes, scheduleRes, customRes, commRes] = await Promise.allSettled([
	// 		getRuleSources(),
	// 		getRuleStats(),
	// 		getUpdateSchedule(),
	// 		getCustomRules(),
	// 		getCommercialConfig(),
	// 	]);
	// 	if (sourcesRes.status === 'fulfilled') {
	// 		sources = sourcesRes.value.sources;
	// 		lastUpdate = sourcesRes.value.last_update;
	// 	}
	// 	if (statsRes.status === 'fulfilled') stats = statsRes.value;
	// 	if (scheduleRes.status === 'fulfilled') schedule = scheduleRes.value;
	// 	if (customRes.status === 'fulfilled') customRulesContent = customRes.value;
	// 	customFailed = customRes.status === 'rejected';
	// 	if (commRes.status === 'fulfilled') commercialConfig = commRes.value;
	// 	commercialFailed = commRes.status === 'rejected';
	// 	loading = false;
	// }
	// OLD CODE END
	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const [liveRes] = await Promise.allSettled([getLiveRuleStatus()]);
		const [sourcesRes, statsRes, scheduleRes, customRes, commRes] = await Promise.allSettled([
			getRuleSources(),
			getRuleStats(),
			getUpdateSchedule(),
			getCustomRules(),
			getCommercialConfig(),
		]);
		if (!guard.current(g)) return 'skipped';
		if (liveRes.status === 'fulfilled') {
			live = liveRes.value;
			liveError = '';
		} else {
			live = null;
			liveError = liveRes.reason instanceof Error ? liveRes.reason.message : 'unknown error';
		}
		if (sourcesRes.status === 'fulfilled') {
			sources = sourcesRes.value.sources;
			lastUpdate = sourcesRes.value.last_update;
		}
		if (statsRes.status === 'fulfilled') stats = statsRes.value;
		if (scheduleRes.status === 'fulfilled') schedule = scheduleRes.value;
		if (customRes.status === 'fulfilled') customRulesContent = customRes.value;
		customFailed = customRes.status === 'rejected';
		if (commRes.status === 'fulfilled') commercialConfig = commRes.value;
		commercialFailed = commRes.status === 'rejected';
		loaded = true;
		// Only these feed what the page shows; the source list, stats and schedule replies only
		// back the controls that aren't wired up yet (#58)
		const shown = [liveRes, customRes, commRes];
		const failures = shown.filter((r) => r.status === 'rejected').length;
		return failures === 0 ? 'ok' : failures === shown.length ? 'failed' : 'partial';
	}

	const refresh = registerPageRefresh(load);
	onDestroy(refresh.unregister);
	onMount(() => void refresh.run());

	// OLD CODE START — #96: one failed request left every section on its defaults
	/*
	async function loadData() {
		loading = true;
		await loadLive();
		try {
			const [sourcesRes, statsRes, scheduleRes, customRes, commRes] = await Promise.all([
				getRuleSources(),
				getRuleStats(),
				getUpdateSchedule(),
				getCustomRules(),
				getCommercialConfig(),
			]);
			sources = sourcesRes.sources;
			lastUpdate = sourcesRes.last_update;
			stats = statsRes;
			schedule = scheduleRes;
			customRulesContent = customRes;
			commercialConfig = commRes;
		} catch (err) {
			showMessage('Failed to load rule data', 'error');
		} finally {
			loading = false;
		}
	}
	*/
	// OLD CODE END

	async function toggleSource(source: RuleSource) {
		togglingSource = source.id;
		try {
			const success = source.enabled
				? await disableRuleSource(source.id)
				: await enableRuleSource(source.id);
			if (success) {
				source.enabled = !source.enabled;
				showMessage(`${source.id} ${source.enabled ? 'enabled' : 'disabled'}`);
			} else {
				showMessage(`Failed to toggle ${source.id}`, 'error');
			}
		} catch {
			showMessage(`Error toggling ${source.id}`, 'error');
		} finally {
			togglingSource = '';
		}
	}

	async function handleUpdateNow() {
		updating = true;
		try {
			const result = await updateRulesNow();
			if (result.success) {
				showMessage('Rules updated and reloaded successfully');
				await refresh.run();
			} else {
				showMessage('Rule update failed: ' + result.output.slice(0, 200), 'error');
			}
		} catch {
			showMessage('Failed to trigger rule update', 'error');
		} finally {
			updating = false;
		}
	}

	async function handleScheduleChange(e: Event) {
		const target = e.target as HTMLSelectElement;
		const interval = target.value;
		try {
			schedule = await setUpdateSchedule(interval);
			showMessage(`Update schedule set to ${interval}`);
		} catch {
			showMessage('Failed to update schedule', 'error');
		}
	}

	async function handleSaveCustomRules() {
		savingCustomRules = true;
		try {
			const result = await uploadCustomRules(customRulesContent);
			if (result.success) {
				showMessage(`Saved ${result.rules_written} custom rules`);
			} else {
				showMessage('Failed to save custom rules', 'error');
			}
		} catch {
			showMessage('Error saving custom rules', 'error');
		} finally {
			savingCustomRules = false;
		}
	}

	async function handleSaveCommercial() {
		if (!commercialKey || commercialKey.length < 8) {
			showMessage('Licence key must be at least 8 characters', 'error');
			return;
		}
		savingCommercial = true;
		try {
			const result = await configureCommercial(commercialType, commercialKey);
			if (result.success) {
				showMessage(`${commercialType === 'etpro' ? 'ET Pro' : 'Snort Subscriber'} configured`);
				commercialConfig = await getCommercialConfig();
				showCommercialForm = false;
				commercialKey = '';
			} else {
				showMessage('Failed to configure commercial source', 'error');
			}
		} catch {
			showMessage('Error configuring commercial source', 'error');
		} finally {
			savingCommercial = false;
		}
	}

	function formatDate(iso: string | null): string {
		if (!iso) return 'Never';
		try {
			return new Date(iso).toLocaleString();
		} catch {
			return iso;
		}
	}

	// OLD CODE START — the page refresh contract (PLAN §5.5): the first load goes through refresh.run()
	// // Load data on mount
	// $effect(() => {
	// 	loadData();
	// });
	// OLD CODE END

	const liveStats = $derived(
		live
			? [
					{ key: 'rules', label: 'Enabled rules', value: live.enabled_rules.toLocaleString() },
					{ key: 'sources', label: 'Sources', value: String(live.sources.length) },
					{ key: 'updated', label: 'Last updated', value: formatDate(live.last_updated) },
				]
			: [],
	);
	const retryMessage = 'Check that Suricata is running on the System page, then try again.';
</script>

<svelte:head>
	<title>Suricata rules | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a class="back" href="/settings"><Icon name="back" />Settings</a>
		<h1 class="page-title">Suricata rules</h1>
		<p class="page-sub">The threat detection rules Suricata runs, where they come from and when they refresh</p>
	</div>
	<div class="head-actions">
		<button class="btn primary" type="button" onclick={handleUpdateNow} disabled={updating}>
			<Icon name="refresh" />{updating ? 'Updating…' : 'Update rules now'}
		</button>
	</div>
</div>

{#if message}
	<div class={['notice', messageType === 'error' ? 'is-error' : 'is-ok']} role={messageType === 'error' ? 'alert' : 'status'}>
		<Icon name={messageType === 'error' ? 'warn' : 'check'} />{message}
	</div>
{/if}

<div class="grid">
	<Card title="Rules Suricata runs" sub="Read from the Suricata container · rule count, feeds and last update" hero class="c-12">
		{#if !loaded}
			<CardState state="loading" title="Loading Suricata's rules" />
		{:else if !live}
			<CardState
				state="error"
				title="Could not read Suricata's rules: {liveError}"
				message={retryMessage}
				onaction={() => refresh.run()}
			/>
		{:else}
			<StatStrip stats={liveStats} />
		{/if}
	</Card>

	<!-- Rule sources: what the rule updater really downloads (#58) -->
	<Card title="Rule sources" sub="The feeds Suricata's rule updater downloads" class="c-6">
		{#if !loaded}
			<CardState state="loading" title="Loading rule sources" />
		{:else if !live}
			<CardState
				state="error"
				title="Couldn't read the rule sources: the request failed."
				message={retryMessage}
				onaction={() => refresh.run()}
			/>
		{:else if live.sources.length === 0}
			<CardState
				state="empty"
				icon="threats"
				title="No rule sources listed"
				message="No sources are listed in the rule updater's configuration."
			/>
		{:else}
			<p class="card-text">Turning feeds on or off from this page is not available yet.</p>
			<ul class="rows">
				{#each live.sources as url}
					<li class="two"><b>{sourceName(url)}</b><span class="mono">{url}</span></li>
				{/each}
			</ul>
		{/if}
	</Card>

	<!-- Update schedule: the real cron entry in the Suricata container (#58) -->
	<Card title="Update schedule" sub="Container time (UTC)" class="c-6">
		{#if !loaded}
			<CardState state="loading" title="Loading the update schedule" />
		{:else if !live}
			<CardState
				state="error"
				title="Couldn't read the update schedule: the request failed."
				message={retryMessage}
				onaction={() => refresh.run()}
			/>
		{:else}
			<p class="card-text">{scheduleText(live.schedule)}</p>
		{/if}
	</Card>

	<Card title="Custom rules" sub="One rule per line · lines starting with # are comments" class="c-6">
		<p class="card-text">Add your own Suricata rules.</p>
		<div class="notice is-warn" role="status">
			<Icon name="warn" />Not connected to Suricata yet: rules saved here are not loaded, so saving is off.
		</div>
		{#if customFailed}
			<div class="notice is-error" role="status"><Icon name="warn" />Couldn't load the saved custom rules: the request failed.</div>
		{/if}
		<div class="field">
			<label class="label" for="custom-rules">Rules</label>
			<textarea
				id="custom-rules"
				class="textarea mono"
				readonly
				bind:value={customRulesContent}
				placeholder='alert tcp any any -> any any (msg:"Custom rule"; sid:9999001; rev:1;)'
				rows="8"
			></textarea>
		</div>
		<div class="form-actions">
			<button class="btn" type="button" onclick={handleSaveCustomRules} disabled>
				{savingCustomRules ? 'Saving…' : 'Save custom rules'}
			</button>
		</div>
	</Card>

	<Card title="Commercial rule sources" sub="ET Pro or Snort Subscriber licence keys" class="c-6">
		<p class="card-text">Configure ET Pro or Snort Subscriber licence keys for premium rule feeds.</p>
		<div class="notice is-warn" role="status">
			<Icon name="warn" />Not connected to Suricata yet: a key saved here would not add any rules, so this is off.
		</div>
		{#if commercialFailed}
			<div class="notice is-error" role="status"><Icon name="warn" />Couldn't load the commercial licence status: the request failed.</div>
		{/if}
		{#if commercialConfig.configured}
			<dl class="facts">
				<dt>Active</dt>
				<dd>{commercialConfig.source_type === 'etpro' ? 'ET Pro' : 'Snort Subscriber'}</dd>
				<dt>Key</dt>
				<dd class="mono">{commercialConfig.license_key_masked}</dd>
				<dt>Configured</dt>
				<dd class="num">{formatDate(commercialConfig.configured_at ?? null)}</dd>
			</dl>
		{/if}
		{#if showCommercialForm}
			<div class="form-grid commercial-form">
				<div class="field">
					<label class="label" for="commercial-type">Source type</label>
					<select class="select" id="commercial-type" bind:value={commercialType}>
						<option value="etpro">ET Pro (Proofpoint)</option>
						<option value="snort">Snort Subscriber (Cisco Talos)</option>
					</select>
				</div>
				<div class="field">
					<label class="label" for="commercial-key">Licence key or Oink code</label>
					<input
						class="input mono"
						id="commercial-key"
						type="password"
						bind:value={commercialKey}
						placeholder="Enter your licence key"
					/>
				</div>
			</div>
			<div class="form-actions">
				<button class="btn" type="button" onclick={() => { showCommercialForm = false; }}>Cancel</button>
				<button class="btn primary" type="button" onclick={handleSaveCommercial} disabled={savingCommercial}>
					{savingCommercial ? 'Saving…' : 'Save'}
				</button>
			</div>
		{:else}
			<div class="form-actions">
				<button class="btn" type="button" disabled onclick={() => { showCommercialForm = true; }}>
					{commercialConfig.configured ? 'Update licence' : 'Add commercial licence'}
				</button>
			</div>
		{/if}
	</Card>
</div>

<style>
	.card-text { color: var(--text-2); font-size: var(--text-sm); line-height: 1.5; margin-bottom: var(--sp-4); }
	.notice { margin-bottom: var(--sp-3); }
	.rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--sp-3); font-size: var(--text-sm); }
	.rows .mono { overflow-wrap: anywhere; }
	.commercial-form { margin-top: var(--sp-4); }
</style>
