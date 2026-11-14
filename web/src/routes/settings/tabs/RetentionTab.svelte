<!--
  Settings › Storage & retention (NET-273: moved from the Settings page): the retention health card,
  the retention policy form and manual cleanup. The top bar's Refresh re-reads the health card only,
  never the form, so an unsaved edit survives it.
-->
<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { previewCleanup, executeCleanup, type CleanupPreview } from '$lib/api/storage';
	import { loadFailed } from '$lib/utils/load-failed';
	import { formatBytes } from '$lib/api/logs';
	import { formatTime } from '$lib/utils/time';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import StatStrip from '$lib/components/ui/StatStrip.svelte';
	import Meter from '$lib/components/ui/Meter.svelte';
	import Feedback from '../Feedback.svelte';

	interface Props {
		/** The policy form differs from what was last loaded or saved. */
		dirty?: boolean;
		/** A save or a cleanup is running. */
		busy?: boolean;
	}

	let { dirty = $bindable(false), busy = $bindable(false) }: Props = $props();

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
	let storageStatusFailed = $state(false);
	let storageLoading = $state(true);
	// OLD CODE: let ilmStatus = $state<{ synced: boolean; last_applied: string | null; pending_retry: boolean; policies: Record<string, string> } | null>(null);
	// A15: last_attempt and last_error say why ILM isn't in sync
	let ilmStatus = $state<{ synced: boolean; last_applied: string | null; pending_retry: boolean; policies: Record<string, string>; last_attempt?: string | null; last_error?: string | null } | null>(null);
	let retentionSaving = $state(false);
	let retentionMessage = $state('');
	let retentionError = $state(false);
	// Save stays off until the real values load, so defaults can't overwrite them
	let retentionLoad = $state<'loading' | 'ok' | 'failed'>('loading');
	// NET-273: the form as last loaded or saved, so the page can guard an unsaved edit
	const retentionForm = () => JSON.stringify(retentionConfig);
	let retentionSavedForm = $state(retentionForm());
	const retentionUnsaved = $derived(retentionLoad === 'ok' && retentionForm() !== retentionSavedForm);

	// --- Manual Cleanup state ---
	let cleanupDays = $state(60);
	let cleanupPreview = $state<CleanupPreview | null>(null);
	// Days the shown preview was computed for — the delete must use these, not the live input
	let cleanupPreviewDays = $state<number | null>(null);
	let cleanupPreviewing = $state(false);
	let cleanupExecuting = $state(false);
	let showCleanupConfirm = $state(false);
	let cleanupMessage = $state('');
	let cleanupError = $state(false);

	$effect(() => {
		dirty = retentionUnsaved;
		busy = retentionSaving || cleanupExecuting;
	});

	async function loadRetention() {
		try {
			const res = await fetch('/api/setup/storage');
			// OLD CODE START — L11: the route answers 503 now instead of mock figures (A16), so a 200
			// is always the daemon's
			// if (res.ok) {
			// 	const data = await res.json();
			// 	// source 'mock' = the daemon didn't answer and these are built-in defaults
			// 	if (data.source !== 'mock') {
			// 		// GET /api/setup/storage returns a FLAT StorageStatus object
			// 		// (hot_days, warm_days, etc. are top-level, not nested under retention)
			// 		retentionConfig.hot_days = data.hot_days ?? 90;
			// 		retentionConfig.warm_days = data.warm_days ?? 180;
			// 		retentionConfig.cold_days = data.cold_days ?? 30;
			// 		retentionConfig.disk_threshold = data.disk_threshold_percent ?? 80;
			// 		retentionConfig.emergency_threshold = data.emergency_threshold_percent ?? 90;
			// 		retentionLoad = 'ok';
			// 		return;
			// 	}
			// }
			// OLD CODE END
			if (res.ok) {
				const data = await res.json();
				// GET /api/setup/storage returns a FLAT StorageStatus object
				// (hot_days, warm_days, etc. are top-level, not nested under retention)
				retentionConfig.hot_days = data.hot_days ?? 90;
				retentionConfig.warm_days = data.warm_days ?? 180;
				retentionConfig.cold_days = data.cold_days ?? 30;
				retentionConfig.disk_threshold = data.disk_threshold_percent ?? 80;
				retentionConfig.emergency_threshold = data.emergency_threshold_percent ?? 90;
				retentionSavedForm = retentionForm();
				retentionLoad = 'ok';
				return;
			}
		} catch {
			// Falls through to 'failed'
		}
		retentionLoad = 'failed';
	}

	async function loadDiskUsage() {
		try {
			const res = await fetch('/api/storage/status');
			if (res.ok) {
				const data = await res.json();
				diskUsage = data.disk_usage_percent ?? data.usage_percent ?? null;
				lastPruneAt = data.last_prune_at ?? null;
				ilmStatus = data.ilm_status ?? null;
				storageStatusFailed = false;
				storageLoading = false;
				return;
			}
		} catch {
			// OLD CODE START — a failure left "Loading...", "Never (daemon starting...)" and a Problem badge
			// // Will stay null
			// OLD CODE END
		}
		storageStatusFailed = true;
		storageLoading = false;
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

		// OLD CODE START — a failed status read scored as a Problem
		// let status: 'healthy' | 'attention' | 'problem' = 'healthy';
		// OLD CODE END
		let status: 'healthy' | 'attention' | 'problem' | 'unknown' = 'healthy';
		if (storageStatusFailed) status = 'unknown';
		else if ((!ilmOk && !ilmPending) || diskCritical) status = 'problem';
		else if (ilmPending || diskHigh || !pruneOk) status = 'attention';

		return { status, ilmOk, ilmPending, pruneOk, pruneStale, diskPct, diskHigh, diskCritical };
	});

	/**
	 * The top bar's Refresh: the Retention health card only (NET-273: the page's loader read it with
	 * About; each tab reads its own now), never the form, so an unsaved edit survives it.
	 */
	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		// shortcut: the read writes its section unguarded; it takes no range or filter, so an older
		// reply answers the same question. Copy the query into locals if it gains one.
		await loadDiskUsage();
		if (!guard.current(g)) return 'skipped';
		return storageStatusFailed ? 'failed' : 'ok';
	}

	const refresh = registerPageRefresh(load);
	onDestroy(refresh.unregister);
	// The form loads once here, and again when the tab opens again
	onMount(() => {
		loadRetention();
		void refresh.run();
	});

	async function saveRetention() {
		retentionSaving = true;
		retentionMessage = '';
		retentionError = false;
		// The form as sent: an edit typed while the save runs stays unsaved (review L1)
		const sent = retentionForm();
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
				// OLD CODE: retentionSavedForm = retentionForm(); (counted edits typed during the save as saved)
				retentionSavedForm = sent;
				if (result.ilm_applied) {
					retentionMessage = 'Retention settings saved and applied to OpenSearch.';
				} else {
					retentionMessage = 'Retention settings saved. OpenSearch policies will sync shortly.';
				}
			} else {
				// OLD CODE START — didn't separate "not saved" from "may have been saved"
				// const data = await res.json();
				// retentionMessage = data.error || 'Failed to save configuration.';
				// OLD CODE END
				const data = await res.json().catch(() => ({}));
				retentionMessage = data.outcome_unknown
					? `Outcome unknown — check again. ${data.error ?? ''} Reload this page to see whether the settings were saved.`
					: `Not saved: ${data.error || `HTTP ${res.status}`}`;
				retentionError = true;
			}
		} catch {
			// OLD CODE START
			// retentionMessage = 'Failed to connect to server.';
			// OLD CODE END
			retentionMessage = 'Not saved: could not reach the NetTap server.';
			retentionError = true;
		} finally {
			retentionSaving = false;
		}
	}

	// OLD CODE START — 2026-11-06 (NET-166): a copy of formatBytes in $lib/api/logs, 1024-based under decimal labels; the shared one is decimal
	// function formatCleanupBytes(bytes: number): string {
	// 	if (bytes === 0) return '0 B';
	// 	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	// 	const i = Math.floor(Math.log(bytes) / Math.log(1024));
	// 	return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
	// }
	// OLD CODE END

	async function handleCleanupPreview() {
		if (cleanupDays < 1) return;
		cleanupPreviewing = true;
		cleanupMessage = '';
		cleanupError = false;
		cleanupPreview = null;
		cleanupPreviewDays = null;
		showCleanupConfirm = false;

		const days = cleanupDays;
		try {
			// OLD CODE START — preview and execute both read the live input, so editing
			// the days after previewing deleted a different range than the one shown
			// cleanupPreview = await previewCleanup(cleanupDays);
			// OLD CODE END
			cleanupPreview = await previewCleanup(days);
			cleanupPreviewDays = days;
		} catch (err: unknown) {
			cleanupMessage = err instanceof Error ? err.message : 'Failed to preview cleanup';
			cleanupError = true;
		} finally {
			cleanupPreviewing = false;
		}
	}

	async function handleCleanupExecute() {
		if (cleanupPreviewDays === null) return;
		cleanupExecuting = true;
		cleanupMessage = '';
		cleanupError = false;

		try {
			// OLD CODE START — used the live input instead of the previewed days
			// const result = await executeCleanup(cleanupDays);
			// OLD CODE END
			const result = await executeCleanup(cleanupPreviewDays);
			const freedStr = formatBytes(result.freed_bytes_estimate);
			cleanupMessage = `Cleanup complete: deleted ${result.deleted_indices} indices and ${result.deleted_pcap_files} PCAP files, freed ${freedStr}.`;
			if (result.errors.length > 0) {
				cleanupMessage += ` (${result.errors.length} errors)`;
			}
			cleanupError = false;
			cleanupPreview = null;
			cleanupPreviewDays = null;
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
		cleanupPreviewDays = null;
		cleanupMessage = '';
	}
</script>

<div class="grid">
	<!-- OLD CODE: sub="Storage status · read when this page opened" (NET-192 PR 4: the top bar's Refresh reads it again) -->
	<Card title="Retention health" sub="Storage status · read when the page opened or was refreshed" class="c-4">
		{#snippet actions()}
			{#if !storageLoading}
				<!-- OLD CODE START — no unknown state
				{retentionHealth.status === 'healthy' ? 'Healthy' : retentionHealth.status === 'attention' ? 'Attention' : 'Problem'}
				OLD CODE END -->
				<span class={['chip', { healthy: 'is-ok', attention: 'is-warn', problem: 'is-bad', unknown: '' }[retentionHealth.status]]}>
					{{ healthy: 'Healthy', attention: 'Attention', problem: 'Problem', unknown: 'Unknown' }[retentionHealth.status]}
				</span>
			{/if}
		{/snippet}
		{#if storageLoading}
			<CardState state="loading" title="Loading the storage status" />
		{:else if storageStatusFailed && ilmStatus === null && lastPruneAt === null}
			<CardState state="error" title={loadFailed('the storage status')} message="Check that NetTap is running on the System page, then reload." />
		{:else}
			{#if storageStatusFailed}
				<!-- OLD CODE: {@render feedback(loadFailed('the storage status', true), true)} (a red role="alert" box; stale figures are an amber status, NET-192 PR 4) -->
				<p class="notice is-warn" role="status"><Icon name="warn" /><span>{loadFailed('the storage status', true)}</span></p>
			{/if}
			<dl class="facts flush">
				<dt>ILM policies</dt>
				<dd>
					{#if ilmStatus === null}
						<span class="dim">Not reported</span>
					{:else if retentionHealth.ilmPending}
						<span class="chip">Syncing…</span>
					{:else if retentionHealth.ilmOk}
						<!-- OLD CODE START — 2026-11-02: read "All 1 synced" with one policy
						<span style="color: var(--green);">&#x2713; All {Object.keys(ilmStatus.policies).length || 3} synced</span>
						OLD CODE END -->
						{@const policyCount = Object.keys(ilmStatus.policies).length}
						<span class="chip is-ok"><Icon name="check" />{policyCount === 1 ? 'Policy synced' : `${policyCount || 'All'} policies synced`}</span>
					{:else}
						<span class="chip is-bad"><Icon name="warn" />Out of sync</span>
					{/if}
					{#if ilmStatus && !retentionHealth.ilmOk && ilmStatus.last_error}
						<!-- A15: the real reason, not the last success -->
						<p class="dim ilm-error">
							{ilmStatus.last_attempt ? `Last try ${timeAgo(ilmStatus.last_attempt)}: ` : ''}{ilmStatus.last_error}{retentionHealth.ilmPending ? ' NetTap tries again automatically.' : ''}
						</p>
					{/if}
				</dd>
				<dt>Disk usage</dt>
				<dd>
					{#if diskUsage !== null}
						<span class="num">{diskUsage}%</span> <span class="dim">· warning at {retentionConfig.disk_threshold}%</span>
					{:else}
						<span class="dim">Unavailable</span>
					{/if}
				</dd>
				<dt>Last prune</dt>
				<dd>
					{#if lastPruneAt}
						<span class="num">{timeAgo(lastPruneAt)}</span>
					{:else}
						<span class="dim">Never (daemon starting…)</span>
					{/if}
				</dd>
			</dl>
			{#if diskUsage !== null}
				<div class="meter-row"><Meter value={diskUsage} label="Disk used" /></div>
			{/if}
		{/if}
	</Card>

	<Card title="Data retention policy" sub="Days kept per tier · disk thresholds in %" class="c-8">
		<div class="stack">
			{#if retentionLoad === 'failed'}
				<Feedback message="Could not load the current retention settings, so saving is off. Reload the page to try again." isError />
			{/if}
			<Feedback message={retentionMessage} isError={retentionError} />

			<div class="form-grid">
				<div class="field">
					<!-- OLD CODE START — 2026-11-02: Malcolm writes Zeek and Suricata to one daily
					     arkime_sessions3 index, so this setting governs alerts too
					<label class="label" for="hot-days">Hot Tier (Zeek metadata)</label>
					OLD CODE END -->
					<label class="label" for="hot-days">Hot tier (Zeek metadata and Suricata alerts)</label>
					<div class="unit-field">
						<input class="input" id="hot-days" type="number" bind:value={retentionConfig.hot_days} min={7} max={365} />
						<span class="dim">days</span>
					</div>
					<p class="field-help">Zeek logs and Suricata alerts share one daily index, so both are deleted after this many days.</p>
				</div>
				<div class="field">
					<!-- OLD CODE START — 2026-11-02: no Malcolm index is warm; alerts follow the Hot tier
					<label class="label" for="warm-days">Warm Tier (Suricata alerts)</label>
					OLD CODE END -->
					<label class="label" for="warm-days">Warm tier (separate Suricata indices)</label>
					<div class="unit-field">
						<input class="input" id="warm-days" type="number" bind:value={retentionConfig.warm_days} min={7} max={730} />
						<span class="dim">days</span>
					</div>
					<p class="field-help">Applies only to separate <span class="mono">suricata-*</span> indices, which this install doesn't create. Alerts follow the Hot tier.</p>
				</div>
				<div class="field">
					<label class="label" for="cold-days">Cold tier (PCAP files)</label>
					<div class="unit-field">
						<input class="input" id="cold-days" type="number" bind:value={retentionConfig.cold_days} min={1} max={365} />
						<span class="dim">days</span>
					</div>
					<p class="field-help">Raw packet captures of all traffic. The oldest files also go once PCAP passes its share of the disk.</p>
				</div>
			</div>

			<div class="form-grid">
				<div class="field">
					<label class="label" for="disk-threshold">Disk warning threshold</label>
					<div class="unit-field">
						<input class="input" id="disk-threshold" type="number" bind:value={retentionConfig.disk_threshold} min={50} max={95} />
						<span class="dim">%</span>
					</div>
					<p class="field-help">Start pruning old data when disk usage exceeds this.</p>
				</div>
				<div class="field">
					<label class="label" for="emergency-threshold">Emergency threshold</label>
					<div class="unit-field">
						<input class="input" id="emergency-threshold" type="number" bind:value={retentionConfig.emergency_threshold} min={60} max={99} />
						<span class="dim">%</span>
					</div>
					<p class="field-help">Aggressive pruning regardless of tier when disk exceeds this.</p>
				</div>
			</div>

			<div class="form-actions">
				{#if retentionUnsaved}<span class="unsaved">Unsaved changes</span>{/if}
				<button class="btn primary" type="button" onclick={saveRetention} disabled={retentionSaving || retentionLoad !== 'ok'}>
					{retentionSaving ? 'Saving…' : 'Save retention settings'}
				</button>
			</div>
		</div>
	</Card>

	<Card title="Manual data cleanup" sub="Deletes OpenSearch indices and PCAP files · cannot be undone" class="c-12">
		<div class="stack">
			<p class="field-help">Permanently delete OpenSearch indices and PCAP files older than a specified number of days to free up disk space.</p>
			<Feedback message={cleanupMessage} isError={cleanupError} />

			<div class="inline-row">
				<span>Delete data older than</span>
				<div class="unit-field">
					<!-- OLD CODE START — editing the days left the old preview (and its Delete button) on screen
					<input class="input" type="number" bind:value={cleanupDays} min={1} max={3650} disabled={cleanupExecuting} />
					OLD CODE END -->
					<input
						class="input"
						type="number"
						aria-label="Delete data older than (days)"
						bind:value={cleanupDays}
						oninput={cancelCleanup}
						min={1}
						max={3650}
						disabled={cleanupExecuting || cleanupPreviewing}
					/>
					<span class="dim">days</span>
				</div>
				<button class="btn" type="button" onclick={handleCleanupPreview} disabled={cleanupPreviewing || cleanupExecuting || cleanupDays < 1}>
					{cleanupPreviewing ? 'Scanning…' : 'Preview cleanup'}
				</button>
			</div>

			{#if cleanupPreview}
				<section class="preview" aria-labelledby="cleanup-preview-title">
					<div class="preview-head">
						<h3 class="eyebrow" id="cleanup-preview-title">Cleanup preview</h3>
						<span class="dim">Data before {formatTime(cleanupPreview.cutoff_date, 'date')}</span>
					</div>
					<StatStrip
						stats={[
							{ key: 'indices', label: 'Indices', value: String(cleanupPreview.total_indices) },
							{ key: 'pcap', label: 'PCAP files', value: String(cleanupPreview.total_pcap_files) },
							{ key: 'freed', label: 'Space freed', value: formatBytes(cleanupPreview.estimated_freed_bytes) },
						]}
					/>

					{#if cleanupPreview.total_indices === 0 && cleanupPreview.total_pcap_files === 0}
						<p class="dim">No data found older than {cleanupPreviewDays} days.</p>
					{:else if !showCleanupConfirm}
						<Feedback message="This action is irreversible. Deleted data cannot be recovered." isError />
						<div class="form-actions">
							<button class="btn" type="button" onclick={cancelCleanup}>Cancel</button>
							<button class="btn danger" type="button" onclick={() => (showCleanupConfirm = true)}>Delete data</button>
						</div>
					{:else}
						<Feedback
							message={`Are you sure? This will permanently delete ${cleanupPreview.total_indices} indices and ${cleanupPreview.total_pcap_files} PCAP files (${formatBytes(cleanupPreview.estimated_freed_bytes)}).`}
							isError
						/>
						<div class="form-actions">
							<button class="btn" type="button" onclick={cancelCleanup} disabled={cleanupExecuting}>Cancel</button>
							<button class="btn danger" type="button" onclick={handleCleanupExecute} disabled={cleanupExecuting}>
								{cleanupExecuting ? 'Deleting…' : 'Confirm delete'}
							</button>
						</div>
					{/if}
				</section>
			{/if}
		</div>
	</Card>
</div>

<style>
	.ilm-error { margin-top: var(--sp-1); font-size: var(--text-sm); overflow-wrap: anywhere; }
	.meter-row {
		margin-top: var(--sp-4);
	}

	.preview {
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
		padding: var(--sp-4);
		border-radius: var(--r-md);
		background: var(--surface-2);
		border: 1px solid var(--line);
	}

	.preview-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--sp-3);
		flex-wrap: wrap;
		font-size: var(--text-xs);
	}

	/* The system has no destructive button: the word carries it, the colour backs it up */
	.btn.danger {
		color: var(--sev-critical);
	}
</style>
