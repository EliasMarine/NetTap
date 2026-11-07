<script lang="ts">
	/**
	 * Suricata Rule Management — IDS rule sources, updates, custom rules.
	 *
	 * Shows what Suricata downloaded and what it has loaded, triggers updates, saves an optional
	 * ET Pro code (NET-191 slice 2; Snort Subscriber is retired) and edits the owner's own
	 * alert rules (NET-191 slice 3).
	 */

	import { onDestroy, onMount } from 'svelte';
	import {
		// OLD CODE START — NET-191 slice 3: the source toggles, schedule picker and custom rules box never reached Suricata
		// getRuleSources,
		// enableRuleSource,
		// disableRuleSource,
		// OLD CODE END
		updateRulesNow,
		// OLD CODE START — NET-191 slice 3
		// getRuleStats,
		// getUpdateSchedule,
		// setUpdateSchedule,
		// uploadCustomRules,
		// getCustomRules,
		// OLD CODE END
		getOwnerRules,
		// OLD CODE START — NET-191 slice 2: the ET Pro card replaces the commercial licence form
		// configureCommercial,
		// getCommercialConfig,
		// OLD CODE END
		getEtProStatus,
		saveEtProCode,
		clearEtProCode,
		getLiveRuleStatus,
		type LiveRuleStatus,
		// OLD CODE START — NET-191 slice 3
		// type RuleSource,
		// type RuleStats,
		// OLD CODE END
		type RuleUpdateStatus,
		// OLD CODE START — NET-191 slice 3
		// type UpdateSchedule,
		// OLD CODE END
		type OwnerRules,
		// OLD CODE START — NET-191 slice 2
		// type CommercialConfig,
		// OLD CODE END
		type EtProStatus,
	} from '$lib/api/suricata-rules';
	import { registerPageRefresh, type LoadGuard, type LoadResult, outcome } from '$lib/stores/pageRefresh';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import StatStrip from '$lib/components/ui/StatStrip.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { fmt } from '$lib/utils/drilldown';
	import { formatTime } from '$lib/utils/time';
	import { loadFailed } from '$lib/utils/load-failed';
	import OwnerRulesCard from './OwnerRulesCard.svelte';

	// What Suricata really runs (#58)
	let live = $state<LiveRuleStatus | null>(null);
	let liveError = $state('');

	// State
	// OLD CODE START — NET-191 slice 3: these only backed the source toggles and schedule picker, which Suricata never read
	// let sources = $state<RuleSource[]>([]);
	// let stats = $state<RuleStats | null>(null);
	// let schedule = $state<UpdateSchedule>({ interval: 'daily', enabled: true });
	// OLD CODE END
	// OLD CODE START — NET-191 slice 2: the ET Pro status replaces the commercial config
	// let commercialConfig = $state<CommercialConfig>({ configured: false });
	// OLD CODE END
	let etpro = $state<EtProStatus | null>(null);
	// OLD CODE START — NET-191 slice 3: set from the retired source list, never shown
	// let lastUpdate = $state<string | null>(null);
	// OLD CODE END
	// OLD CODE START — the whole page hid behind one loading line; each card now shows its own
	// loading state until the first load lands
	// let loading = $state(true);
	// OLD CODE END
	let loaded = $state(false);
	let updating = $state(false);
	let message = $state('');
	let messageType = $state<'success' | 'error'>('success');

	// OLD CODE START — NET-191 slice 3: the owner rules editor replaces the read-only custom rules box
	// // Custom rules
	// let customRulesContent = $state('');
	// let savingCustomRules = $state(false);
	// OLD CODE END

	// Your own rules (NET-191 slice 3): loaded here with the page, edited in OwnerRulesCard
	let owner = $state<OwnerRules | null>(null);
	let savingOwner = $state(false);

	// OLD CODE START — NET-191 slice 2: the ET Pro form replaces the commercial licence form
	// // Commercial form
	// let showCommercialForm = $state(false);
	// let commercialType = $state('etpro');
	// let commercialKey = $state('');
	// let savingCommercial = $state(false);
	// OLD CODE END

	// ET Pro form. The code lives only in the input until a save succeeds, then it is cleared.
	const ETPRO_CODE = /^[A-Za-z0-9]{16,64}$/;
	const APPLY_POLL_MS = 15_000;
	let etproCode = $state('');
	let etproCodeError = $state('');
	let savingEtPro = $state(false);
	let removingEtPro = $state(false);
	let confirmingRemove = $state(false);
	// Why the last save or remove failed, shown in the card until the next attempt
	let etproError = $state('');

	// OLD CODE START — NET-191 slice 3: the source toggles are retired
	// // Toggling state (track which source is being toggled)
	// let togglingSource = $state('');
	// OLD CODE END

	function showMessage(text: string, type: 'success' | 'error' = 'success') {
		message = text;
		messageType = type;
		setTimeout(() => { message = ''; }, 5000);
	}

	// suricata-update's source names (NET-191 slice 2); anything else shows its own name
	const SOURCE_NAMES = new Map([
		['et/open', 'Emerging Threats Open'],
		['et/pro', 'Emerging Threats Pro'],
		['abuse.ch/sslbl-blacklist', 'abuse.ch SSL Blacklist'],
		['echap/stalkerware', 'Echap stalkerware indicators'],
		['ipfire/dbl', 'IPFire DBL (malware and phishing only)'],
	]);

	/** One line on the last rule update, worst news first. */
	function updateNotice(u: RuleUpdateStatus | undefined): { tone: 'is-ok' | 'is-warn' | 'is-error' | null; text: string } {
		const reason = u?.reason || 'no reason was recorded';
		if (u?.recovery_pending) {
			return { tone: 'is-error', text: `Restoring the last good rules isn't confirmed: ${reason}. It is retried at the next update or restart.` };
		}
		if (u?.state === 'failed' || u?.state === 'interrupted') {
			return { tone: 'is-warn', text: `The last rule update failed ${formatTime(u.attempt)}: ${reason}. Suricata keeps running the last good rules.` };
		}
		if (u?.stale) {
			return { tone: 'is-warn', text: `No successful rule update in 48 hours (last ${u.last_success ? formatTime(u.last_success) : 'never'}).` };
		}
		if (u?.missing_sources?.length) {
			const names = u.missing_sources.map((s) => SOURCE_NAMES.get(s) ?? s).join(', ');
			return { tone: 'is-warn', text: `The last update worked, but these sources weren't enabled: ${names}.` };
		}
		if (u?.state === 'active' || u?.state === 'prepared') {
			const later = u.state === 'prepared' ? ' Suricata loads them when it next starts.' : '';
			return { tone: 'is-ok', text: `Rules last updated ${formatTime(u.last_success)}.${later}` };
		}
		return { tone: null, text: 'No rule update has been recorded yet.' };
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
	// OLD CODE START — NET-191 slice 3: the owner rules load replaces the custom rules load
	// let customFailed = $state(false);
	// OLD CODE END
	let ownerFailed = $state(false);
	// OLD CODE START — NET-191 slice 2
	// let commercialFailed = $state(false);
	// OLD CODE END
	let etproFailed = $state(false);

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
		// OLD CODE START — NET-191 slice 2: the ET Pro status replaces the commercial config
		// const [sourcesRes, statsRes, scheduleRes, customRes, commRes] = await Promise.allSettled([
		// 	getRuleSources(),
		// 	getRuleStats(),
		// 	getUpdateSchedule(),
		// 	getCustomRules(),
		// 	getCommercialConfig(),
		// ]);
		// OLD CODE END
		// OLD CODE START — NET-191 slice 3: the source list, stats and schedule fed nothing on screen
		// const [sourcesRes, statsRes, scheduleRes, customRes, etproRes] = await Promise.allSettled([
		// 	getRuleSources(),
		// 	getRuleStats(),
		// 	getUpdateSchedule(),
		// 	getCustomRules(),
		// 	getEtProStatus(),
		// ]);
		// OLD CODE END
		const [ownerRes, etproRes] = await Promise.allSettled([getOwnerRules(), getEtProStatus()]);
		if (!guard.current(g)) return 'skipped';
		if (liveRes.status === 'fulfilled') {
			live = liveRes.value;
			liveError = '';
		} else {
			live = null;
			liveError = liveRes.reason instanceof Error ? liveRes.reason.message : 'unknown error';
		}
		// OLD CODE START — NET-191 slice 3
		// if (sourcesRes.status === 'fulfilled') {
		// 	sources = sourcesRes.value.sources;
		// 	lastUpdate = sourcesRes.value.last_update;
		// }
		// if (statsRes.status === 'fulfilled') stats = statsRes.value;
		// if (scheduleRes.status === 'fulfilled') schedule = scheduleRes.value;
		// if (customRes.status === 'fulfilled') customRulesContent = customRes.value;
		// customFailed = customRes.status === 'rejected';
		// OLD CODE END
		// A failed refresh keeps the last rules and says so; the card keeps what the owner is typing
		if (ownerRes.status === 'fulfilled') owner = ownerRes.value;
		ownerFailed = ownerRes.status === 'rejected';
		// OLD CODE START — NET-191 slice 2
		// if (commRes.status === 'fulfilled') commercialConfig = commRes.value;
		// commercialFailed = commRes.status === 'rejected';
		// OLD CODE END
		// A failed refresh keeps the last ET Pro status and says so
		if (etproRes.status === 'fulfilled') etpro = etproRes.value;
		etproFailed = etproRes.status === 'rejected';
		loaded = true;
		// OLD CODE START — NET-191 slice 3: the source list, stats and schedule are no longer loaded
		// // Only these feed what the page shows; the source list, stats and schedule replies only
		// // back the controls that aren't wired up yet (#58)
		// OLD CODE END
		// OLD CODE START — NET-191 slice 2
		// const shown = [liveRes, customRes, commRes];
		// OLD CODE END
		// OLD CODE START — NET-191 slice 3
		// const shown = [liveRes, customRes, etproRes];
		// OLD CODE END
		const shown = [liveRes, ownerRes, etproRes];
		// OLD CODE START — counted by hand; outcome() in pageRefresh is the shared rule
		// const failures = shown.filter((r) => r.status === 'rejected').length;
		// return failures === 0 ? 'ok' : failures === shown.length ? 'failed' : 'partial';
		// OLD CODE END
		return outcome(shown);
	}

	const refresh = registerPageRefresh(load);
	onDestroy(refresh.unregister);
	onMount(() => void refresh.run());

	// While Suricata restarts with a new or removed code, look again every 15 s. The effect's
	// teardown clears the interval when applying turns false and when the page goes.
	const applying = $derived(etpro?.applying === true);
	$effect(() => {
		if (!applying) return;
		// runIfIdle: one load can take ~20 s while Suricata restarts, and run() would cancel it every tick
		const poll = setInterval(() => void refresh.runIfIdle(), APPLY_POLL_MS);
		return () => clearInterval(poll);
	});
	// One request at a time: a rule update, an ET Pro save or remove, or the restart they cause
	// OLD CODE START — NET-191 slice 3: saving your own rules reloads Suricata under the same rules lock
	// const busy = $derived(updating || savingEtPro || removingEtPro || applying);
	// OLD CODE END
	const busy = $derived(updating || savingEtPro || removingEtPro || applying || savingOwner);
	// Suricata can't read the owner rules folder yet (the daemon says null), so a save would load nothing
	const ownerUnmounted = $derived(live?.owner_rules === null);

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

	// OLD CODE START — NET-191 slice 3: suricata-update never read these toggles
	/*
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
	*/
	// OLD CODE END

	async function handleUpdateNow() {
		updating = true;
		try {
			const result = await updateRulesNow();
			// OLD CODE START — NET-191 slice 2: a failure didn't refresh the status line, and "still running" read as failed
			// if (result.success) {
			// 	showMessage('Rules updated and reloaded successfully');
			// 	await refresh.run();
			// } else {
			// 	showMessage('Rule update failed: ' + result.output.slice(0, 200), 'error');
			// }
			// OLD CODE END
			if (result.running) {
				showMessage('The rule update is still running. Refresh this page in a few minutes to see the result.');
			} else if (result.success) {
				showMessage('Rules updated and reloaded successfully');
			} else {
				showMessage('Rule update failed: ' + (result.status?.reason || result.output.slice(0, 200)), 'error');
			}
			await refresh.run();
		} catch {
			showMessage('Failed to trigger rule update', 'error');
		} finally {
			updating = false;
		}
	}

	// OLD CODE START — NET-191 slice 3: Suricata's cron never read this schedule, and the custom rules box never loaded its rules
	/*
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
	*/
	// OLD CODE END

	// OLD CODE START — NET-191 slice 2: the ET Pro form replaces the commercial licence form
	// async function handleSaveCommercial() {
	// 	if (!commercialKey || commercialKey.length < 8) {
	// 		showMessage('Licence key must be at least 8 characters', 'error');
	// 		return;
	// 	}
	// 	savingCommercial = true;
	// 	try {
	// 		const result = await configureCommercial(commercialType, commercialKey);
	// 		if (result.success) {
	// 			showMessage(`${commercialType === 'etpro' ? 'ET Pro' : 'Snort Subscriber'} configured`);
	// 			commercialConfig = await getCommercialConfig();
	// 			showCommercialForm = false;
	// 			commercialKey = '';
	// 		} else {
	// 			showMessage('Failed to configure commercial source', 'error');
	// 		}
	// 	} catch {
	// 		showMessage('Error configuring commercial source', 'error');
	// 	} finally {
	// 		savingCommercial = false;
	// 	}
	// }
	// OLD CODE END

	// A failure shows in the card (the top banner is off-screen and fades); the status is read again
	// either way, and the buttons stay off until it lands
	async function handleSaveEtPro(e: SubmitEvent) {
		e.preventDefault();
		confirmingRemove = false;
		etproError = '';
		const code = etproCode.trim();
		if (!ETPRO_CODE.test(code)) {
			etproCodeError = 'An ET Pro code is 16 to 64 letters and digits.';
			return;
		}
		etproCodeError = '';
		savingEtPro = true;
		try {
			const result = await saveEtProCode(code);
			if (result.ok) {
				etproCode = '';
				showMessage('Code saved. Suricata is restarting with ET Pro.');
			} else {
				etproError = result.error ?? "Couldn't save the ET Pro code.";
			}
		} catch {
			etproError = "Couldn't save the ET Pro code: the request failed.";
		} finally {
			await refresh.run();
			savingEtPro = false;
		}
	}

	// The first click asks; the same button then confirms, so focus stays put
	async function handleRemoveEtPro() {
		if (!confirmingRemove) {
			confirmingRemove = true;
			return;
		}
		etproError = '';
		removingEtPro = true;
		try {
			const result = await clearEtProCode();
			if (result.ok) {
				showMessage(result.cleared ? 'Code removed. Suricata is restarting with ET Open.' : 'No ET Pro code was set.');
			} else {
				etproError = result.error ?? "Couldn't remove the ET Pro code.";
			}
		} catch {
			etproError = "Couldn't remove the ET Pro code: the request failed.";
		} finally {
			await refresh.run();
			removingEtPro = false;
			confirmingRemove = false;
		}
	}

	// OLD CODE START — the browser's locale printed "11/6/2026, 10:37:23 PM" (NET-192 PR 4: formatTime)
	// function formatDate(iso: string | null): string {
	// 	if (!iso) return 'Never';
	// 	try {
	// 		return new Date(iso).toLocaleString();
	// 	} catch {
	// 		return iso;
	// 	}
	// }
	// OLD CODE END
	const formatDate = (iso: string | null) => (iso ? formatTime(iso) : 'Never');

	// OLD CODE START — the page refresh contract (PLAN §5.5): the first load goes through refresh.run()
	// // Load data on mount
	// $effect(() => {
	// 	loadData();
	// });
	// OLD CODE END

	// OLD CODE START — NET-191 slice 3: "downloaded" (the rules file) and "active" (what the engine loaded) were one figure
	// const liveStats = $derived(
	// 	live
	// 		? [
	// 				{ key: 'rules', label: 'Enabled rules', value: fmt(live.enabled_rules) },
	// 				// OLD CODE START — NET-191 slice 2: counts suricata-update's enabled sources when the daemon sends them
	// 				// { key: 'sources', label: 'Sources', value: String(live.sources.length) },
	// 				// OLD CODE END
	// 				{ key: 'sources', label: 'Sources', value: String(live.enabled_sources?.length || live.sources.length) },
	// 				{ key: 'updated', label: 'Last updated', value: formatDate(live.last_updated) },
	// 			]
	// 		: [],
	// );
	// OLD CODE END
	const liveStats = $derived(
		live
			? [
					{ key: 'rules', label: 'Rules downloaded', value: fmt(live.enabled_rules) },
					{ key: 'active', label: 'Rules active', value: live.engine ? fmt(live.engine.loaded) : 'Unknown' },
					{ key: 'owner', label: 'Your rules', value: live.owner_rules == null ? 'Not connected' : fmt(live.owner_rules) },
					{ key: 'sources', label: 'Sources', value: String(live.enabled_sources?.length || live.sources.length) },
				]
			: [],
	);
	const retryMessage = 'Check that Suricata is running on the System page, then try again.';
	const update = $derived(updateNotice(live?.update));
	const enabledSources = $derived(live?.enabled_sources ?? []);
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
		<!-- OLD CODE START — NET-191 slice 2: an update could start while an ET Pro change ran or Suricata restarted
		<button class="btn primary" type="button" onclick={handleUpdateNow} disabled={updating}>
		OLD CODE END -->
		<button class="btn primary" type="button" onclick={handleUpdateNow} disabled={busy}>
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
			<!-- NET-191 slice 3: "downloaded" is the rules file, "active" is what Suricata's engine says it loaded -->
			{#if !live.engine}
				<p class="notice is-warn engine-line" role="status">
					<Icon name="warn" /><span>Suricata didn't answer, so how many rules it has loaded is unknown.</span>
				</p>
			{/if}
			<dl class="facts engine-facts">
				<dt>Rules that failed to load</dt>
				<dd class="num">{live.engine ? fmt(live.engine.failed) : 'Unknown'}</dd>
				<dt>Rules last loaded</dt>
				<dd class="num">{live.engine?.reload_time ? formatTime(live.engine.reload_time) : 'Unknown'}</dd>
				<dt>Rules file updated</dt>
				<dd class="num">{formatDate(live.last_updated)}</dd>
			</dl>
			{#if update.tone}
				<p class={['notice', 'update-line', update.tone]} role="status">
					<Icon name={update.tone === 'is-ok' ? 'check' : 'warn'} /><span>{update.text}</span>
				</p>
			{:else}
				<p class="card-text update-line">{update.text}</p>
			{/if}
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
		{:else if enabledSources.length > 0}
			<p class="card-text">Turning feeds on or off from this page is not available yet.</p>
			<ul class="rows">
				{#each enabledSources as name}
					<li class="two"><b>{SOURCE_NAMES.get(name) ?? name}</b><span class="mono">{name}</span></li>
				{/each}
			</ul>
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

	<!-- OLD CODE START — NET-191 slice 3: the read-only box never reached Suricata; the "Your own rules" editor below loads its rules
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
	OLD CODE END -->

	<OwnerRulesCard
		{loaded}
		{owner}
		failed={ownerFailed}
		unmounted={ownerUnmounted}
		{busy}
		reload={() => refresh.run()}
		bind:saving={savingOwner}
	/>

	<!-- OLD CODE START — NET-191 slice 2: Snort Subscriber is retired and the ET Pro card below is wired to suricata-update
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
	OLD CODE END -->

	<Card title="ET Pro" sub="Emerging Threats Pro from Proofpoint · optional, needs a paid code" class="c-6">
		{#if !loaded}
			<CardState state="loading" title="Loading the ET Pro status" />
		{:else if !etpro}
			<CardState
				state="error"
				title="Couldn't read the ET Pro status: the request failed."
				message="Try again in a moment. If it keeps failing, check the System page."
				onaction={() => refresh.run()}
			/>
		{:else}
			<p class="card-text">
				With a code, NetTap downloads ET Pro instead of ET Open. The code is checked with Proofpoint before it is saved,
				stays on this device and is never shown again.
			</p>
			{#if etproFailed}
				<p class="notice is-warn" role="status"><Icon name="warn" /><span>{loadFailed('the ET Pro status', true)}</span></p>
			{/if}
			{#if etpro.applying}
				<p class="notice is-warn" role="status">
					<Icon name="warn" /><span>Suricata is restarting with the new rules. This takes a few minutes; this page refreshes by itself.</span>
				</p>
			{:else if etpro.activation?.state === 'active' && etpro.configured && etpro.active}
				<p class="notice is-ok" role="status">
					<Icon name="check" /><span>ET Pro rules are active: {fmt(etpro.activation.etpro_rules)} rules loaded.</span>
				</p>
			{:else if etpro.activation && etpro.activation.state !== 'active'}
				<p class="notice is-warn" role="status"><Icon name="warn" /><span>{etpro.activation.message}</span></p>
			{/if}
			<dl class="facts">
				<dt>Code</dt>
				<dd>{etpro.configured ? 'Saved' : 'Not set'}</dd>
				<dt>In use</dt>
				<dd>{etpro.active ? (live?.etpro_rules != null ? `Yes — ${fmt(live.etpro_rules)} ET Pro rules active` : 'Yes') : 'No'}</dd>
				<dt>Last update</dt>
				<dd>{etpro.last_update_ok === true ? 'OK' : etpro.last_update_ok === false ? 'Failed' : 'Unknown'}</dd>
			</dl>
			<form class="etpro-form" onsubmit={handleSaveEtPro} novalidate>
				<div class="field">
					<label class="label" for="etpro-code">ET Pro code</label>
					<input
						class="input mono"
						id="etpro-code"
						type="password"
						autocomplete="off"
						spellcheck="false"
						bind:value={etproCode}
						aria-invalid={etproCodeError ? 'true' : undefined}
						aria-describedby={etproCodeError ? 'etpro-code-error' : undefined}
					/>
					{#if etproCodeError}<p class="field-error" id="etpro-code-error" role="alert">{etproCodeError}</p>{/if}
				</div>
				{#if etproError}
					<p class="notice is-error" role="alert"><Icon name="warn" /><span>{etproError}</span></p>
				{/if}
				<div class="form-actions">
					{#if etpro.configured}
						<button class="btn" type="button" onclick={handleRemoveEtPro} disabled={busy}>
							{confirmingRemove ? 'Confirm: remove and restart Suricata' : 'Remove code'}
						</button>
						{#if confirmingRemove}
							<button class="btn" type="button" onclick={() => (confirmingRemove = false)} disabled={removingEtPro}>Cancel</button>
						{/if}
					{/if}
					<button class="btn primary" type="submit" disabled={busy}>
						{savingEtPro ? 'Checking the code…' : 'Save code'}
					</button>
				</div>
			</form>
		{/if}
	</Card>
</div>

<style>
	.card-text { color: var(--text-2); font-size: var(--text-sm); line-height: 1.5; margin-bottom: var(--sp-4); }
	.notice { margin-bottom: var(--sp-3); }
	.rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--sp-3); font-size: var(--text-sm); }
	.rows .mono { overflow-wrap: anywhere; }
	/* OLD CODE START — NET-191 slice 2: the commercial form is retired
	.commercial-form { margin-top: var(--sp-4); }
	OLD CODE END */
	.etpro-form { margin-top: var(--sp-4); }
	.etpro-form .notice { margin: var(--sp-3) 0 0; }
	.update-line { margin: var(--sp-4) 0 0; }
	/* NET-191 slice 3 */
	.engine-line { margin: var(--sp-4) 0 0; }
	.engine-facts { margin-top: var(--sp-4); }
</style>
