<script lang="ts">
	import {
		getVersions,
		getAvailableUpdates,
		checkForUpdates,
		applyUpdates,
		getUpdateStatus,
		getUpdateHistory,
		rollbackComponent,
	} from '$api/updates.js';
	import type {
		ComponentVersion,
		AvailableUpdate,
		UpdateStatus,
		UpdateResult,
	} from '$api/updates.js';
	import { onDestroy, onMount } from 'svelte';
	import Collapsible from '$lib/components/Collapsible.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import Meter from '$lib/components/ui/Meter.svelte';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { loadFailed } from '$lib/utils/load-failed';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let versions = $state<Record<string, ComponentVersion>>({});
	let lastScan = $state('');
	let availableUpdates = $state<AvailableUpdate[]>([]);
	let lastCheck = $state('');
	let updateStatus = $state<UpdateStatus | null>(null);
	let updateHistory = $state<UpdateResult[]>([]);
	let loading = $state(true);
	let checking = $state(false);
	let applying = $state(false);
	// #96: a failed request never reads as "Up to Date" or a finished update
	let versionsFailed = $state(false);
	let updatesFailed = $state(false);
	let historyFailed = $state(false);
	let actionError = $state('');
	// sources the daemon couldn't reach while checking ("component-versions" = all of them)
	let failedChecks = $state<string[]>([]);
	// components the daemon's last check covered (null: an older daemon that doesn't say)
	let checkedComponents = $state<string[] | null>(null);

	// names a reader can follow; anything else is a component name, as in the table below
	let failedChecksNote = $derived(
		failedChecks.includes('component-versions')
			? "Couldn't read the installed versions, so no component could be checked for updates."
			: `Couldn't check ${failedChecks.join(', ')} for updates.`,
	);

	function checkFailed(key: string, name: string): boolean {
		return updatesFailed || failedChecks.some((c) => c === key || c === name || c === 'component-versions');
	}

	// Update modal/panel state
	let showUpdatePanel = $state(false);
	let selectedComponents = $state<Set<string>>(new Set());
	let updateInProgress = $state(false);
	let updateCompleted = $state(false);

	// OLD CODE START — the Name / Status sort buttons; each table now sorts by any column header
	// // Sort state
	// let sortBy = $state<'name' | 'status'>('name');
	// OLD CODE END

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	const versionEntries = $derived.by(() => {
		// OLD CODE START — the daemon sends a list, so each key was its index ("0", "1"…) and no
		// row ever matched its update: every row read "Up to Date" beside "7 updates available"
		// const entries = Object.entries(versions).map(([key, v]) => ({ key, ...v }));
		// OLD CODE END
		const entries = Object.values(versions).map((v) => ({ key: v.name, ...v }));

		// OLD CODE START — sorting moved to the DataTable headers (by name until one is clicked)
		// if (sortBy === 'status') {
		// 	const statusOrder: Record<string, number> = { error: 0, unknown: 1, ok: 2 };
		// 	entries.sort((a, b) => (statusOrder[a.status] ?? 1) - (statusOrder[b.status] ?? 1));
		// } else {
		// 	entries.sort((a, b) => a.name.localeCompare(b.name));
		// }
		// OLD CODE END

		return entries;
	});

	type VersionEntry = (typeof versionEntries)[number];
	type RowStatus = 'Error' | 'Unknown' | 'Update available' | 'Not checked' | 'Up to date';

	/** What a versions row says about its component (same order of checks the table had). */
	function rowStatus(entry: VersionEntry): RowStatus {
		if (entry.status === 'error') return 'Error';
		if (entry.status === 'unknown') return 'Unknown';
		if (updatesMap.has(entry.key)) return 'Update available';
		if (checkFailed(entry.key, entry.name)) return 'Unknown';
		// no check since the daemon started: no update listed doesn't mean none exists;
		// nothing checks the OS, Docker, Python…: no listed update doesn't make them current
		if (!lastCheck || (checkedComponents && !checkedComponents.includes(entry.name))) return 'Not checked';
		return 'Up to date';
	}

	// the most urgent first when sorted descending
	const STATUS_RANK: Record<RowStatus, number> = { Error: 4, 'Update available': 3, Unknown: 2, 'Not checked': 1, 'Up to date': 0 };

	const versionColumns: Column<VersionEntry>[] = [
		{ key: 'name', label: 'Component', cell: componentCell, class: 'vtcol-name' },
		{ key: 'current_version', label: 'Current version', cell: currentCell, class: 'vtcol-current' },
		{ key: 'latest', label: 'Latest available', sortValue: (e) => updatesMap.get(e.key)?.latest_version ?? '', cell: latestCell, class: 'vtcol-latest' },
		{ key: 'status', label: 'Status', sortValue: (e) => STATUS_RANK[rowStatus(e)], cell: statusCell, class: 'vtcol-status' },
		// rows NetTap can update here first, then rows that say how their update arrives
		{ key: 'action', label: 'Action', sortValue: (e) => { const u = updatesMap.get(e.key); return u ? (u.applies_with ? 1 : 2) : 0; }, cell: actionCell, class: 'vtcol-action' },
	];

	const historyColumns: Column<UpdateResult>[] = [
		{ key: 'success', label: 'Result', sortValue: (r) => (r.success ? 1 : 0), cell: historyResultCell },
		{ key: 'component', label: 'Component' },
		{ key: 'version', label: 'Version', sortValue: (r) => r.new_version, cell: historyVersionCell },
		{ key: 'completed_at', label: 'Date', sortValue: (r) => Date.parse(r.completed_at) || 0, cell: historyDateCell },
		{ key: 'duration', label: 'Duration', numeric: true, sortValue: (r) => (Date.parse(r.completed_at) || 0) - (Date.parse(r.started_at) || 0), cell: historyDurationCell },
		{ key: 'error', label: 'Error', sortValue: (r) => r.error ?? '', cell: historyErrorCell },
		{ key: 'rollback', label: 'Action', sortValue: (r) => (r.rollback_available ? 1 : 0), cell: historyActionCell },
	];

	const groupedVersions = $derived.by(() => {
		const groups: Record<string, typeof versionEntries> = {
			core: [],
			docker: [],
			system: [],
			database: [],
			os: [],
		};

		for (const entry of versionEntries) {
			const category = entry.category || 'system';
			if (!groups[category]) groups[category] = [];
			groups[category].push(entry);
		}

		return groups;
	});

	const categoryLabels: Record<string, string> = {
		core: 'Core Components',
		docker: 'Docker Images',
		system: 'System Packages',
		database: 'Databases',
		os: 'Operating System',
	};

	const updatesAvailableCount = $derived(availableUpdates.length);
	// updates NetTap can apply here; the others say how they arrive (applies_with)
	const applicableCount = $derived(availableUpdates.filter((u) => !u.applies_with).length);

	const updatesMap = $derived.by(() => {
		const map = new Map<string, AvailableUpdate>();
		for (const u of availableUpdates) {
			map.set(u.component, u);
		}
		return map;
	});

	const selectedCount = $derived(selectedComponents.size);

	// polling can stop before the daemon says the batch finished: that isn't "complete"
	// a finished batch whose Malcolm update rolled back is "completed" too: its results decide
	const finishedTitle = $derived(
		updateStatus?.state === 'completed'
			? updateStatus.results.some((r) => !r.success)
				? 'Update failed'
				: 'Update complete'
			: updateStatus?.state === 'error'
				? 'Update failed'
				: 'Update not confirmed',
	);

	// A Malcolm update takes 10–40 minutes, a rules update about one: poll every 3 s, give up after 3 hours
	const POLL_INTERVAL_MS = 3000;
	const MAX_POLLS = (3 * 60 * 60 * 1000) / POLL_INTERVAL_MS;
	const MAX_POLL_FAILURES = 20;
	// bumped to stop a running poll loop: a newer one took over, or the page closed
	let pollRun = 0;

	const successCount = $derived(
		updateStatus?.results.filter((r) => r.success).length ?? 0
	);
	const failCount = $derived(
		updateStatus?.results.filter((r) => !r.success).length ?? 0
	);

	// ---------------------------------------------------------------------------
	// Pure helpers (also exported for testing via UpdateSystem.test.ts)
	// ---------------------------------------------------------------------------

	function versionStatusLabel(
		component: string,
		updates: Map<string, AvailableUpdate>
	): string {
		if (updates.has(component)) return 'Update Available';
		return 'Up to Date';
	}

	function versionStatusClass(
		component: string,
		updates: Map<string, AvailableUpdate>,
		status: string
	): string {
		if (status === 'error') return 'badge badge-danger';
		if (status === 'unknown') return 'badge badge-muted';
		if (updates.has(component)) return 'badge badge-warning';
		return 'badge badge-success';
	}

	// OLD CODE START — colour-coded legacy badges; the update type is now a plain tag with its word
	// function updateTypeBadgeClass(type: string): string {
	// 	switch (type) {
	// 		case 'major':
	// 			return 'badge badge-danger';
	// 		case 'minor':
	// 			return 'badge badge-warning';
	// 		case 'patch':
	// 			return 'badge badge-success';
	// 		default:
	// 			return 'badge badge-muted';
	// 	}
	// }
	// OLD CODE END

	function formatSizeMB(mb: number): string {
		if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
		return `${mb.toFixed(1)} MB`;
	}

	function timeAgo(isoString: string): string {
		if (!isoString) return 'Never';
		const now = Date.now();
		const then = new Date(isoString).getTime();
		const diff = now - then;

		if (diff < 0) return 'Just now';

		const minutes = Math.floor(diff / 60000);
		if (minutes < 1) return 'Just now';
		if (minutes < 60) return `${minutes}m ago`;

		const hours = Math.floor(minutes / 60);
		if (hours < 24) return `${hours}h ago`;

		const days = Math.floor(hours / 24);
		if (days < 30) return `${days}d ago`;

		const months = Math.floor(days / 30);
		return `${months}mo ago`;
	}

	function truncateChangelog(text: string, maxLength = 200): string {
		if (!text) return '';
		if (text.length <= maxLength) return text;
		return text.slice(0, maxLength) + '...';
	}

	function componentStatusIcon(
		component: string,
		status: UpdateStatus | null
	): 'pending' | 'updating' | 'success' | 'failed' {
		if (!status) return 'pending';
		const result = status.results.find((r) => r.component === component);
		if (result) {
			return result.success ? 'success' : 'failed';
		}
		if (status.current_component === component) return 'updating';
		return 'pending';
	}

	function formatDuration(startIso: string, endIso: string): string {
		if (!startIso || !endIso) return '--';
		const start = new Date(startIso).getTime();
		const end = new Date(endIso).getTime();
		const diff = Math.max(0, end - start);
		const seconds = Math.floor(diff / 1000);
		if (seconds < 60) return `${seconds}s`;
		const minutes = Math.floor(seconds / 60);
		const remainingSeconds = seconds % 60;
		return `${minutes}m ${remainingSeconds}s`;
	}

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	// OLD CODE START — the page refresh contract (PLAN.md §5.5): the top bar's Refresh runs this
	// loader, which says what loaded and drops a reply that lands after the page has gone
	// async function fetchAll() {
	// OLD CODE END
	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		loading = true;
		// OLD CODE START — #96: the getters faked empty lists on failure (every row read
		// "Up to Date"), and one failure blanked the rest; they now throw
		// try {
		// 	const [versionsRes, updatesRes, historyRes] = await Promise.all([
		// 		getVersions(),
		// 		getAvailableUpdates(),
		// 		getUpdateHistory(),
		// 	]);
		// 	versions = versionsRes.versions;
		// 	lastScan = versionsRes.last_scan;
		// 	availableUpdates = updatesRes.updates;
		// 	lastCheck = updatesRes.last_check;
		// 	updateHistory = historyRes;
		// } catch {
		// 	// Keep existing state on error
		// } finally {
		// 	loading = false;
		// }
		// OLD CODE END
		const results = await Promise.allSettled([
			getVersions(),
			getAvailableUpdates(),
			getUpdateHistory(),
		]);
		if (!guard.current(g)) return 'skipped';
		const [versionsRes, updatesRes, historyRes] = results;
		if (versionsRes.status === 'fulfilled') {
			versions = versionsRes.value.versions;
			lastScan = versionsRes.value.last_scan;
		}
		if (updatesRes.status === 'fulfilled') {
			availableUpdates = updatesRes.value.updates;
			lastCheck = updatesRes.value.last_check;
			failedChecks = updatesRes.value.failed_checks ?? [];
			checkedComponents = updatesRes.value.checked ?? null;
		}
		if (historyRes.status === 'fulfilled') updateHistory = historyRes.value;
		historyFailed = historyRes.status === 'rejected';
		versionsFailed = versionsRes.status === 'rejected';
		updatesFailed = updatesRes.status === 'rejected';
		loading = false;
		const failures = results.filter((r) => r.status === 'rejected').length;
		return failures === 0 ? 'ok' : failures === results.length ? 'failed' : 'partial';
	}

	const refresh = registerPageRefresh(load);
	onDestroy(refresh.unregister);

	async function handleCheckForUpdates() {
		checking = true;
		actionError = '';
		try {
			const res = await checkForUpdates();
			availableUpdates = res.updates;
			lastCheck = new Date().toISOString();
			updatesFailed = false;
			failedChecks = res.failed_checks ?? [];
			checkedComponents = res.checked ?? null;
		} catch {
			// OLD CODE START — #96: a failed check was silent
			// // Keep existing state
			// OLD CODE END
			actionError = "Couldn't check for updates: the request failed.";
		} finally {
			checking = false;
		}
	}

	function openUpdatePanel(selectAll = true) {
		showUpdatePanel = true;
		updateInProgress = false;
		updateCompleted = false;
		updateStatus = null;
		if (selectAll) {
			// OLD CODE START — selected updates NetTap can't apply (applies_with)
			// selectedComponents = new Set(availableUpdates.map((u) => u.component));
			// OLD CODE END
			selectedComponents = new Set(
				availableUpdates.filter((u) => !u.applies_with).map((u) => u.component),
			);
		}
	}

	function openSingleUpdate(component: string) {
		showUpdatePanel = true;
		updateInProgress = false;
		updateCompleted = false;
		updateStatus = null;
		selectedComponents = new Set([component]);
	}

	function closeUpdatePanel() {
		showUpdatePanel = false;
		selectedComponents = new Set();
		updateInProgress = false;
		updateCompleted = false;
		updateStatus = null;
	}

	function toggleComponent(component: string) {
		const next = new Set(selectedComponents);
		if (next.has(component)) {
			next.delete(component);
		} else {
			next.add(component);
		}
		selectedComponents = next;
	}

	async function handleApplyUpdates() {
		if (selectedComponents.size === 0) return;
		applying = true;
		updateInProgress = true;
		updateCompleted = false;
		actionError = '';

		try {
			const status = await applyUpdates([...selectedComponents]);

			// 409: another tab (or this one before a reload) already started an update; follow it
			if (status.already_running) {
				await followUpdate(status);
				return;
			}

			// #96: the client answers a failed request with an empty 'error' status, which
			// read as an "Update Complete" with no results
			if (status.state === 'error' && status.results.length === 0) {
				updateInProgress = false;
				actionError = "Couldn't start the update: the request failed.";
				return;
			}
			updateStatus = status;

			// Poll for completion if in_progress
			if (status.state === 'in_progress') {
				await pollUpdateStatus();
			} else {
				updateInProgress = false;
				updateCompleted = true;
			}
		} catch {
			updateInProgress = false;
			// OLD CODE START — #96: a failed request read as a finished update
			// updateCompleted = true;
			// OLD CODE END
			actionError = "Couldn't start the update: the request failed.";
		} finally {
			applying = false;
		}
	}

	// OLD CODE START — the daemon applied updates before answering, so 2 minutes was the cap; it now
	// answers at once and a Malcolm update runs 10–40 minutes
	// async function pollUpdateStatus() {
	// 	let attempts = 0;
	// 	const maxAttempts = 120; // max 2 minutes of polling
	//
	// 	while (attempts < maxAttempts) {
	// 		await new Promise((resolve) => setTimeout(resolve, 1000));
	// 		attempts++;
	//
	// 		try {
	// 			const status = await getUpdateStatus();
	// 			updateStatus = status;
	//
	// 			if (status.state !== 'in_progress') {
	// 				updateInProgress = false;
	// 				updateCompleted = true;
	// 				// Refresh versions after update completes
	// 				await fetchAll();
	// 				return;
	// 			}
	// 		} catch {
	// 			// Continue polling on error
	// 		}
	// 	}
	//
	// 	updateInProgress = false;
	// 	updateCompleted = true;
	// 	// #96: the loop gave up without seeing the update finish
	// 	actionError = "Couldn't confirm the update finished: its status didn't report completion within 2 minutes.";
	// }
	// OLD CODE END
	async function pollUpdateStatus() {
		const run = ++pollRun;
		let failures = 0;

		for (let attempt = 0; attempt < MAX_POLLS; attempt++) {
			await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
			if (run !== pollRun) return;

			let status: UpdateStatus;
			try {
				status = await getUpdateStatus();
			} catch {
				// OpenSearch restarts during a Malcolm update, but the daemon should keep answering
				if (++failures < MAX_POLL_FAILURES) continue;
				updateInProgress = false;
				updateCompleted = true;
				actionError = 'Lost contact with NetTap while the update was running: reload the page to see where it got to.';
				return;
			}
			if (run !== pollRun) return;
			failures = 0;
			updateStatus = status;
			if (status.state === 'in_progress') continue;

			updateInProgress = false;
			updateCompleted = true;
			if (status.state === 'error') {
				actionError = "The update couldn't run: NetTap reported an error.";
			} else if (status.state !== 'completed') {
				// idle: the daemon restarted and lost track of the batch
				actionError = "Couldn't confirm the update finished: NetTap stopped reporting it. Check the versions below.";
			}
			await refresh.run();
			return;
		}

		updateInProgress = false;
		updateCompleted = true;
		actionError = "Couldn't confirm the update finished: it was still running after 3 hours. Reload the page to see where it got to.";
	}

	/** Show an update the daemon is running (started here, in another tab, or before a reload) and poll it. */
	async function followUpdate(status: UpdateStatus) {
		showUpdatePanel = true;
		updateCompleted = false;
		updateInProgress = true;
		updateStatus = status;
		selectedComponents = new Set(status.components);
		await pollUpdateStatus();
	}

	async function resumeRunningUpdate() {
		let status: UpdateStatus;
		try {
			status = await getUpdateStatus();
		} catch {
			// unknown is fine here: starting another update gets a 409, which follows the running one
			return;
		}
		if (status.state === 'in_progress') await followUpdate(status);
	}

	async function handleRollback(component: string) {
		actionError = '';
		try {
			// OLD CODE START — #96: a failed rollback ({ result: 'error' }) was ignored
			// await rollbackComponent(component);
			// OLD CODE END
			const res = await rollbackComponent(component);
			if (res.result === 'error') actionError = `Couldn't roll back ${component}: the request failed.`;
			await refresh.run();
		} catch {
			// OLD CODE START — #96: a network error was swallowed
			// // Keep existing state
			// OLD CODE END
			actionError = `Couldn't roll back ${component}: the request failed.`;
		}
	}

	// ---------------------------------------------------------------------------
	// Initialize
	// ---------------------------------------------------------------------------

	// OLD CODE START — loads go through the page refresh contract
	// $effect(() => {
	// 	fetchAll();
	// 	resumeRunningUpdate();
	// 	return () => {
	// 		pollRun++;
	// 	};
	// });
	// OLD CODE END
	onMount(() => {
		void refresh.run();
		resumeRunningUpdate();
		return () => {
			pollRun++;
		};
	});
</script>

<svelte:head>
	<title>Software updates | NetTap</title>
</svelte:head>

{#snippet componentCell(entry: VersionEntry)}
	<span class="two">
		<span class="component-name">{entry.name}</span>
		<span class="dim component-type">{entry.install_type}</span>
	</span>
{/snippet}

{#snippet currentCell(entry: VersionEntry)}
	<span class="mono">{entry.current_version}</span>
{/snippet}

{#snippet latestCell(entry: VersionEntry)}
	<span class="mono">{updatesMap.get(entry.key)?.latest_version ?? '—'}</span>
{/snippet}

{#snippet statusCell(entry: VersionEntry)}
	{@const status = rowStatus(entry)}
	{#if status === 'Error'}
		<span class="chip is-bad"><Icon name="warn" />Error</span>
	{:else if status === 'Update available'}
		<span class="chip"><Icon name="download" />Update available</span>
	{:else if status === 'Up to date'}
		<span class="chip is-ok"><Icon name="check" />Up to date</span>
	{:else}
		<span class="chip">{status}</span>
	{/if}
{/snippet}

{#snippet actionCell(entry: VersionEntry)}
	{@const update = updatesMap.get(entry.key)}
	<!-- OLD CODE START — offered Update for updates NetTap can't apply
	{#if update}
	OLD CODE END -->
	{#if update && !update.applies_with}
		<button class="btn" type="button" onclick={() => openSingleUpdate(entry.key)}>Update</button>
	{:else if update?.applies_with}
		<!-- was blank: say how this update arrives -->
		<span class="applies-with">{update.applies_with}</span>
	{/if}
{/snippet}

{#snippet historyResultCell(result: UpdateResult)}
	<span class={['chip', result.success ? 'is-ok' : 'is-bad']}>
		<Icon name={result.success ? 'check' : 'close'} />{result.success ? 'Success' : 'Failed'}
	</span>
{/snippet}

{#snippet historyVersionCell(result: UpdateResult)}
	<span class="mono">{result.old_version} → {result.new_version}</span>
{/snippet}

{#snippet historyDateCell(result: UpdateResult)}
	<span class="dim">{new Date(result.completed_at).toLocaleDateString()}</span>
{/snippet}

{#snippet historyDurationCell(result: UpdateResult)}
	<span class="num">{formatDuration(result.started_at, result.completed_at)}</span>
{/snippet}

{#snippet historyErrorCell(result: UpdateResult)}
	{#if result.error}<span class="error-text">{result.error}</span>{/if}
{/snippet}

{#snippet historyActionCell(result: UpdateResult)}
	{#if result.rollback_available}
		<button class="btn" type="button" onclick={() => handleRollback(result.component)}>Roll back</button>
	{/if}
{/snippet}

<div class="page-head">
	<div>
		<a href="/system" class="back"><Icon name="back" />System</a>
		<h1 class="page-title">Software updates</h1>
		<p class="page-sub">
			{#if updatesFailed}
				Couldn't load the available updates: the request failed.
			{:else if lastCheck}
				Last checked: {timeAgo(lastCheck)}
			{:else}
				Updates have not been checked yet
			{/if}
		</p>
	</div>
	<div class="head-actions">
		<button class="btn primary" type="button" onclick={handleCheckForUpdates} disabled={checking || loading}>
			<Icon name="refresh" />
			{checking ? 'Checking…' : 'Check for updates'}
		</button>
	</div>
</div>

{#if failedChecks.length > 0}
	<!-- OLD CODE START — showed "component-versions" as is, and blamed every failure on a source not answering
	<p class="text-warning">Couldn't check {failedChecks.join(', ')}: those sources didn't answer.</p>
	OLD CODE END -->
	<div class="notice is-warn" role="status"><Icon name="warn" />{failedChecksNote}</div>
{/if}

{#if actionError}
	<div class="notice is-error" role="alert"><Icon name="warn" />{actionError}</div>
{/if}

<div class="grid">
	<!-- Update banner -->
	{#if updatesAvailableCount > 0 && !showUpdatePanel}
		<Card
			hero
			class="c-12"
			title="{updatesAvailableCount} update{updatesAvailableCount !== 1 ? 's' : ''} available"
			sub={applicableCount > 0
				? 'Review and apply updates to keep your appliance secure and up to date.'
				: 'None of these can be applied from here: each one says how it arrives.'}
		>
			<!-- the sub was always "Review and apply…", also when none could be applied here -->
			{#snippet actions()}
				<div class="actions">
					<button class="btn" type="button" onclick={() => openUpdatePanel(true)}>Review</button>
					<!-- was always shown: with nothing applicable it opened a panel with nothing to pick -->
					{#if applicableCount > 0}
						<button class="btn primary" type="button" onclick={() => openUpdatePanel(true)}>Update all</button>
					{/if}
				</div>
			{/snippet}
		</Card>
	{/if}

	<!-- Update panel -->
	{#if showUpdatePanel}
		<Card
			class="c-12"
			title={updateCompleted ? finishedTitle : updateInProgress ? 'Updating…' : 'Apply updates'}
			sub={updateCompleted
				? 'What happened to each component'
				: updateInProgress
					? 'A Malcolm update takes 10 to 40 minutes · you can leave this page and come back'
					: 'Pick the components to update · NetTap backs up first and rolls back if an update fails'}
		>
			<!-- OLD CODE START — read "Update Complete" also when polling stopped first
			Update Complete
			OLD CODE END -->
			{#snippet actions()}
				<button class="icon-btn" type="button" onclick={closeUpdatePanel} aria-label="Close"><Icon name="close" /></button>
			{/snippet}

			{#if updateCompleted && updateStatus}
				<!-- Completion summary -->
				<div class="chips summary">
					{#if successCount > 0}
						<span class="chip is-ok"><Icon name="check" />{successCount} succeeded</span>
					{/if}
					{#if failCount > 0}
						<span class="chip is-bad"><Icon name="close" />{failCount} failed</span>
					{/if}
				</div>
				<ul class="rows">
					{#each updateStatus.results as result (result.component)}
						<li class="row">
							<span class={['row-ic', result.success ? 'is-ok' : 'is-bad']}>
								<Icon name={result.success ? 'check' : 'close'} label={result.success ? 'Succeeded' : 'Failed'} />
							</span>
							<span class="two">
								<b>{result.component}</b>
								<span class="mono">{result.old_version} → {result.new_version}</span>
							</span>
							<span class="row-end">
								{#if result.error}
									<span class="error-text">{result.error}</span>
								{/if}
								{#if result.rollback_available && !result.success}
									<button class="btn" type="button" onclick={() => handleRollback(result.component)}>Roll back</button>
								{/if}
							</span>
						</li>
					{/each}
				</ul>
			{:else if updateInProgress && updateStatus}
				<!-- Progress -->
				<div class="progress">
					<Meter value={updateStatus.progress_percent} label="Update progress" />
					<p class="num">{updateStatus.progress_percent}% complete</p>
					{#if updateStatus.current_step}
						<p class="dim">{updateStatus.current_step}</p>
					{/if}
				</div>
				<ul class="rows">
					{#each [...selectedComponents] as component (component)}
						{@const icon = componentStatusIcon(component, updateStatus)}
						<li class="row">
							<span class={['row-ic', icon === 'success' && 'is-ok', icon === 'failed' && 'is-bad']}>
								{#if icon === 'updating'}
									<Icon name="refresh" />
								{:else if icon === 'success'}
									<Icon name="check" />
								{:else if icon === 'failed'}
									<Icon name="close" />
								{/if}
							</span>
							<span class="component-status-name">{component}</span>
							<span class="row-end dim">
								{#if icon === 'updating'}
									Updating…
								{:else if icon === 'success'}
									Done
								{:else if icon === 'failed'}
									Failed
								{:else}
									Pending
								{/if}
							</span>
						</li>
					{/each}
				</ul>
				{#if updateStatus.current_component}
					<p class="mono dim current">Updating: {updateStatus.current_component}</p>
				{/if}
			{:else}
				<!-- Component selection -->
				<p class="help">Select the components you want to update:</p>
				<ul class="checklist">
					{#each availableUpdates as update (update.component)}
						<li>
							<label class="check-row pick">
								<!-- applies_with: NetTap can't apply it, so it can't be picked -->
								<input
									type="checkbox"
									checked={!update.applies_with && selectedComponents.has(update.component)}
									disabled={!!update.applies_with}
									onchange={() => toggleComponent(update.component)}
								/>
								<span class="pick-info">
									<span class="pick-head">
										<b>{update.component}</b>
										<span class="tag">{update.update_type}</span>
										{#if update.requires_restart && !update.applies_with}
											<span class="tag">Restart required</span>
										{/if}
									</span>
									<span class="mono">{update.current_version} → {update.latest_version}</span>
									<!-- OLD CODE START — an unmeasured (null) size showed nothing; now it says so
									{#if update.size_mb > 0}
										<span class="check-size text-muted">{formatSizeMB(update.size_mb)}</span>
									{/if}
									OLD CODE END -->
									{#if update.applies_with}
										<span class="dim">{update.applies_with}</span>
									{:else if update.size_mb == null}
										<span class="dim">size unknown</span>
									{:else if update.size_mb > 0}
										<span class="dim">{formatSizeMB(update.size_mb)}</span>
									{/if}
								</span>
							</label>
							{#if update.changelog}
								<Collapsible title="Changelog" subtitle={update.latest_version}>
									<pre class="changelog">{update.changelog}</pre>
								</Collapsible>
							{/if}
						</li>
					{/each}
				</ul>
				<div class="form-actions">
					<button class="btn" type="button" onclick={closeUpdatePanel}>Cancel</button>
					<button class="btn primary" type="button" onclick={handleApplyUpdates} disabled={selectedCount === 0 || applying}>
						{applying ? 'Starting…' : `Update ${selectedCount} component${selectedCount !== 1 ? 's' : ''}`}
					</button>
				</div>
			{/if}
		</Card>
	{/if}

	<!-- Installed versions -->
	<Card title="Installed versions" sub="Every component NetTap runs · by kind" class="c-12">
		{#if loading && Object.keys(versions).length === 0}
			<CardState state="loading" title="Loading version information" />
		{:else if versionsFailed && Object.keys(versions).length === 0}
			<CardState
				state="error"
				title="Couldn't load installed versions: the request failed."
				message="Check that NetTap is running on the System page, then try again."
				onaction={() => void refresh.run()}
			/>
		{:else if Object.keys(versions).length === 0}
			<CardState
				state="empty"
				icon="download"
				title="No version information available"
				message="Select Check for updates to scan this NetTap."
			/>
		{:else}
			{#if versionsFailed}
				<div class="notice is-warn" role="status"><Icon name="warn" />{loadFailed('installed versions', true)}</div>
			{/if}
			{#each Object.entries(groupedVersions) as [category, entries] (category)}
				{#if entries.length > 0}
					<section class="category">
						<h3 class="eyebrow">{categoryLabels[category] || category}</h3>
						<DataTable
							columns={versionColumns}
							rows={entries}
							ariaLabel={categoryLabels[category] || category}
							rowKey={(e) => e.key}
							initialSort={{ key: 'name', dir: 'asc' }}
						/>
					</section>
				{/if}
			{/each}
		{/if}
	</Card>

	<!-- What's new -->
	{#if updateHistory.length > 0 && updateHistory.some((r) => r.success)}
		<Card title="What's new" sub="Recent updates applied to your appliance · last five" class="c-12">
			<dl class="facts flush">
				{#each updateHistory.filter((r) => r.success).slice(0, 5) as result, i (i)}
					<dt>{result.component}</dt>
					<dd><span class="mono">{result.old_version} → {result.new_version}</span> <span class="dim">· {timeAgo(result.completed_at)}</span></dd>
				{/each}
			</dl>
		</Card>
	{/if}

	<!-- Update history -->
	{#if updateHistory.length > 0}
		<Card title="Update history" sub="{updateHistory.length} past update{updateHistory.length !== 1 ? 's' : ''}" class="c-12">
			{#if historyFailed}
				<div class="notice is-warn" role="status"><Icon name="warn" />{loadFailed('the update history', true)}</div>
			{/if}
			<DataTable
				columns={historyColumns}
				rows={updateHistory}
				ariaLabel="Update history"
				rowKey={(r) => `${r.component}-${r.started_at}-${r.completed_at}`}
				initialSort={{ key: 'completed_at', dir: 'desc' }}
			/>
		</Card>
	{:else if historyFailed}
		<Card title="Update history" sub="Past updates on this NetTap" class="c-12">
			<CardState
				state="error"
				title={loadFailed('the update history')}
				message="Check that NetTap is running on the System page, then try again."
				onaction={() => void refresh.run()}
			/>
		</Card>
	{/if}
</div>

<style>
	:global(.card) > .notice { margin-bottom: var(--sp-4); }
	.category + .category { margin-top: var(--sp-5); }
	.category .eyebrow { margin-bottom: var(--sp-2); }
	.category :global(.vtcol-action) { text-align: right; }
	.component-type { font-size: var(--text-xs); }
	.applies-with { display: inline-block; max-width: 280px; font-size: var(--text-xs); color: var(--text-3); text-align: right; white-space: normal; }
	.error-text { color: var(--sev-critical); font-size: var(--text-sm); }
	.summary { margin-bottom: var(--sp-4); }
	.rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
	.row { display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; gap: var(--sp-3); align-items: center; padding: var(--sp-2) 0; }
	.row + .row { border-top: 1px solid var(--line); }
	.row-ic { display: grid; place-items: center; color: var(--text-3); }
	.row-ic.is-ok { color: var(--ok); }
	.row-ic.is-bad { color: var(--sev-critical); }
	.row-end { display: flex; align-items: center; gap: var(--sp-3); justify-content: flex-end; font-size: var(--text-sm); }
	.progress { display: flex; flex-direction: column; gap: var(--sp-2); margin-bottom: var(--sp-4); font-size: var(--text-sm); }
	.current { margin-top: var(--sp-3); font-size: var(--text-sm); }
	.help { color: var(--text-2); font-size: var(--text-sm); margin-bottom: var(--sp-3); }
	.checklist { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--sp-2); }
	.checklist > li { padding: var(--sp-3); border: 1px solid var(--line); border-radius: var(--r-md); background: var(--surface-1); }
	.pick { align-items: flex-start; }
	.pick input { margin-top: 2px; }
	.pick-info { display: flex; flex-direction: column; gap: var(--sp-1); min-width: 0; }
	.pick-head { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; }
	.changelog { margin: 0; white-space: pre-wrap; font-family: var(--font-mono); font-size: var(--text-xs); color: var(--text-2); }
	.facts.flush { border-top: 0; padding-top: 0; }
</style>
