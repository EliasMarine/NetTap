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
	import Collapsible from '$lib/components/Collapsible.svelte';

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

	// Update modal/panel state
	let showUpdatePanel = $state(false);
	let selectedComponents = $state<Set<string>>(new Set());
	let updateInProgress = $state(false);
	let updateCompleted = $state(false);

	// Sort state
	let sortBy = $state<'name' | 'status'>('name');

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	const versionEntries = $derived.by(() => {
		const entries = Object.entries(versions).map(([key, v]) => ({ key, ...v }));

		if (sortBy === 'status') {
			const statusOrder: Record<string, number> = { error: 0, unknown: 1, ok: 2 };
			entries.sort((a, b) => (statusOrder[a.status] ?? 1) - (statusOrder[b.status] ?? 1));
		} else {
			entries.sort((a, b) => a.name.localeCompare(b.name));
		}

		return entries;
	});

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

	const updatesMap = $derived.by(() => {
		const map = new Map<string, AvailableUpdate>();
		for (const u of availableUpdates) {
			map.set(u.component, u);
		}
		return map;
	});

	const selectedCount = $derived(selectedComponents.size);

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

	function updateTypeBadgeClass(type: string): string {
		switch (type) {
			case 'major':
				return 'badge badge-danger';
			case 'minor':
				return 'badge badge-warning';
			case 'patch':
				return 'badge badge-success';
			default:
				return 'badge badge-muted';
		}
	}

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

	async function fetchAll() {
		loading = true;
		try {
			const [versionsRes, updatesRes, historyRes] = await Promise.all([
				getVersions(),
				getAvailableUpdates(),
				getUpdateHistory(),
			]);
			versions = versionsRes.versions;
			lastScan = versionsRes.last_scan;
			availableUpdates = updatesRes.updates;
			lastCheck = updatesRes.last_check;
			updateHistory = historyRes;
		} catch {
			// Keep existing state on error
		} finally {
			loading = false;
		}
	}

	async function handleCheckForUpdates() {
		checking = true;
		try {
			const res = await checkForUpdates();
			availableUpdates = res.updates;
			lastCheck = new Date().toISOString();
		} catch {
			// Keep existing state
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
			selectedComponents = new Set(availableUpdates.map((u) => u.component));
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

		try {
			const status = await applyUpdates([...selectedComponents]);
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
			updateCompleted = true;
		} finally {
			applying = false;
		}
	}

	async function pollUpdateStatus() {
		let attempts = 0;
		const maxAttempts = 120; // max 2 minutes of polling

		while (attempts < maxAttempts) {
			await new Promise((resolve) => setTimeout(resolve, 1000));
			attempts++;

			try {
				const status = await getUpdateStatus();
				updateStatus = status;

				if (status.state !== 'in_progress') {
					updateInProgress = false;
					updateCompleted = true;
					// Refresh versions after update completes
					await fetchAll();
					return;
				}
			} catch {
				// Continue polling on error
			}
		}

		updateInProgress = false;
		updateCompleted = true;
	}

	async function handleRollback(component: string) {
		try {
			await rollbackComponent(component);
			await fetchAll();
		} catch {
			// Keep existing state
		}
	}

	// ---------------------------------------------------------------------------
	// Initialize
	// ---------------------------------------------------------------------------

	$effect(() => {
		fetchAll();
	});
</script>

<svelte:head>
	<title>Software Updates | NetTap</title>
</svelte:head>

<div class="updates-page">
	<!-- Header -->
	<div class="page-header">
		<div class="header-left">
			<div class="header-breadcrumb">
				<a href="/system" class="breadcrumb-link">System</a>
				<span class="breadcrumb-sep">/</span>
				<span>Software Updates</span>
			</div>
			<h2>Software Updates</h2>
			<p class="text-muted">
				{#if lastCheck}
					Last checked: {timeAgo(lastCheck)}
				{:else}
					Updates have not been checked yet
				{/if}
			</p>
		</div>
		<div class="header-actions">
			<button
				class="btn btn-primary btn-sm"
				onclick={handleCheckForUpdates}
				disabled={checking || loading}
			>
				<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<polyline points="23 4 23 10 17 10" />
					<polyline points="1 20 1 14 7 14" />
					<path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
				</svg>
				{checking ? 'Checking...' : 'Check for Updates'}
			</button>
		</div>
	</div>

	{#if loading && Object.keys(versions).length === 0}
		<div class="loading-state">
			<div class="spinner"></div>
			<p class="text-muted">Loading version information...</p>
		</div>
	{:else}
		<!-- Update Banner -->
		{#if updatesAvailableCount > 0 && !showUpdatePanel}
			<div class="update-banner">
				<div class="update-banner-content">
					<div class="update-banner-icon">
						<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
							<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
							<polyline points="7 10 12 15 17 10" />
							<line x1="12" y1="15" x2="12" y2="3" />
						</svg>
					</div>
					<div class="update-banner-text">
						<span class="update-banner-title">
							{updatesAvailableCount} update{updatesAvailableCount !== 1 ? 's' : ''} available
						</span>
						<span class="update-banner-subtitle">
							Review and apply updates to keep your appliance secure and up to date.
						</span>
					</div>
				</div>
				<div class="update-banner-actions">
					<button class="btn btn-secondary btn-sm" onclick={() => openUpdatePanel(true)}>
						Review
					</button>
					<button class="btn btn-primary btn-sm" onclick={() => openUpdatePanel(true)}>
						Update All
					</button>
				</div>
			</div>
		{/if}

		<!-- Update Panel (modal-like overlay) -->
		{#if showUpdatePanel}
			<div class="update-panel">
				<div class="card">
					<div class="card-header">
						<span class="card-title">
							{#if updateCompleted}
								Update Complete
							{:else if updateInProgress}
								Updating...
							{:else}
								Apply Updates
							{/if}
						</span>
						<button class="btn-close" onclick={closeUpdatePanel} aria-label="Close">
							<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<line x1="18" y1="6" x2="6" y2="18" />
								<line x1="6" y1="6" x2="18" y2="18" />
							</svg>
						</button>
					</div>

					{#if updateCompleted && updateStatus}
						<!-- Completion summary -->
						<div class="update-summary">
							<div class="summary-stats">
								{#if successCount > 0}
									<div class="summary-stat summary-success">
										<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
											<path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
											<polyline points="22 4 12 14.01 9 11.01" />
										</svg>
										<span>{successCount} succeeded</span>
									</div>
								{/if}
								{#if failCount > 0}
									<div class="summary-stat summary-fail">
										<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
											<circle cx="12" cy="12" r="10" />
											<line x1="15" y1="9" x2="9" y2="15" />
											<line x1="9" y1="9" x2="15" y2="15" />
										</svg>
										<span>{failCount} failed</span>
									</div>
								{/if}
							</div>

							<!-- Per-component results -->
							<div class="result-list">
								{#each updateStatus.results as result}
									<div class="result-item">
										<div class="result-info">
											{#if result.success}
												<span class="result-icon result-icon-success">
													<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12" /></svg>
												</span>
											{:else}
												<span class="result-icon result-icon-fail">
													<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
												</span>
											{/if}
											<div>
												<span class="result-name">{result.component}</span>
												<span class="result-version mono">
													{result.old_version} &rarr; {result.new_version}
												</span>
											</div>
										</div>
										<div class="result-actions">
											{#if result.error}
												<span class="text-danger text-sm">{result.error}</span>
											{/if}
											{#if result.rollback_available && !result.success}
												<button class="btn btn-secondary btn-xs" onclick={() => handleRollback(result.component)}>
													Rollback
												</button>
											{/if}
										</div>
									</div>
								{/each}
							</div>
						</div>
					{:else if updateInProgress && updateStatus}
						<!-- Progress display -->
						<div class="update-progress">
							<div class="progress-bar-container">
								<div
									class="progress-bar"
									style="width: {updateStatus.progress_percent}%"
								></div>
							</div>
							<p class="progress-label mono">{updateStatus.progress_percent}% complete</p>

							<div class="component-status-list">
								{#each [...selectedComponents] as component}
									{@const icon = componentStatusIcon(component, updateStatus)}
									<div class="component-status-item">
										<span class="component-status-icon">
											{#if icon === 'updating'}
												<div class="spinner-sm"></div>
											{:else if icon === 'success'}
												<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="var(--success)" stroke-width="2"><polyline points="20 6 9 17 4 12" /></svg>
											{:else if icon === 'failed'}
												<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="var(--danger)" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
											{:else}
												<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="var(--text-muted)" stroke-width="2"><circle cx="12" cy="12" r="10" /></svg>
											{/if}
										</span>
										<span class="component-status-name">{component}</span>
										<span class="component-status-label">
											{#if icon === 'updating'}
												Updating...
											{:else if icon === 'success'}
												Done
											{:else if icon === 'failed'}
												Failed
											{:else}
												Pending
											{/if}
										</span>
									</div>
								{/each}
							</div>

							{#if updateStatus.current_component}
								<div class="log-area">
									<p class="log-title mono">Updating: {updateStatus.current_component}</p>
								</div>
							{/if}
						</div>
					{:else}
						<!-- Component selection -->
						<div class="update-selection">
							<p class="text-muted selection-help">
								Select the components you want to update:
							</p>

							<div class="component-checklist">
								{#each availableUpdates as update}
									<div class="component-check-item">
										<label class="check-label">
											<input
												type="checkbox"
												checked={selectedComponents.has(update.component)}
												onchange={() => toggleComponent(update.component)}
											/>
											<div class="check-info">
												<div class="check-header">
													<span class="check-name">{update.component}</span>
													<span class={updateTypeBadgeClass(update.update_type)}>
														{update.update_type}
													</span>
													{#if update.requires_restart}
														<span class="badge badge-warning">Restart required</span>
													{/if}
												</div>
												<span class="check-version mono">
													{update.current_version} &rarr; {update.latest_version}
												</span>
												{#if update.size_mb > 0}
													<span class="check-size text-muted">{formatSizeMB(update.size_mb)}</span>
												{/if}
											</div>
										</label>

										<!-- Expandable changelog -->
										{#if update.changelog}
											<Collapsible title="Changelog" subtitle={update.latest_version}>
												<pre class="changelog-content">{update.changelog}</pre>
											</Collapsible>
										{/if}
									</div>
								{/each}
							</div>

							<div class="update-actions">
								<button class="btn btn-secondary" onclick={closeUpdatePanel}>
									Cancel
								</button>
								<button
									class="btn btn-primary"
									onclick={handleApplyUpdates}
									disabled={selectedCount === 0 || applying}
								>
									{applying ? 'Starting...' : `Update ${selectedCount} Component${selectedCount !== 1 ? 's' : ''}`}
								</button>
							</div>
						</div>
					{/if}
				</div>
			</div>
		{/if}

		<!-- Release Notes / What's New -->
		{#if updateHistory.length > 0 && updateHistory.some((r) => r.success)}
			<Collapsible title="What's New" subtitle="Recent updates applied to your appliance">
				<div class="release-notes">
					{#each updateHistory.filter((r) => r.success).slice(0, 5) as result}
						<div class="release-note-item">
							<div class="release-note-header">
								<span class="release-note-name">{result.component}</span>
								<span class="mono release-note-version">{result.old_version} &rarr; {result.new_version}</span>
								<span class="text-muted text-sm">{timeAgo(result.completed_at)}</span>
							</div>
						</div>
					{/each}
				</div>
			</Collapsible>
		{/if}

		<!-- Versions Table -->
		<div class="card">
			<div class="card-header">
				<span class="card-title">Installed Versions</span>
				<div class="sort-controls">
					<span class="text-muted text-sm">Sort by:</span>
					<button
						class="sort-btn"
						class:sort-active={sortBy === 'name'}
						onclick={() => (sortBy = 'name')}
					>
						Name
					</button>
					<button
						class="sort-btn"
						class:sort-active={sortBy === 'status'}
						onclick={() => (sortBy = 'status')}
					>
						Status
					</button>
				</div>
			</div>

			{#each Object.entries(groupedVersions) as [category, entries]}
				{#if entries.length > 0}
					<div class="version-category">
						<h4 class="category-title">{categoryLabels[category] || category}</h4>
						<div class="version-table">
							<div class="version-table-header">
								<span class="vtcol-name">Component</span>
								<span class="vtcol-current">Current Version</span>
								<span class="vtcol-latest">Latest Available</span>
								<span class="vtcol-status">Status</span>
								<span class="vtcol-action"></span>
							</div>
							{#each entries as entry}
								{@const update = updatesMap.get(entry.key)}
								<div class="version-row">
									<span class="vtcol-name">
										<span class="component-name">{entry.name}</span>
										<span class="component-type text-muted text-xs">{entry.install_type}</span>
									</span>
									<span class="vtcol-current mono">{entry.current_version}</span>
									<span class="vtcol-latest mono">
										{#if update}
											{update.latest_version}
										{:else}
											--
										{/if}
									</span>
									<span class="vtcol-status">
										{#if entry.status === 'error'}
											<span class="badge badge-danger">Error</span>
										{:else if entry.status === 'unknown'}
											<span class="badge badge-muted">Unknown</span>
										{:else if update}
											<span class="badge badge-warning">Update Available</span>
										{:else}
											<span class="badge badge-success">Up to Date</span>
										{/if}
									</span>
									<span class="vtcol-action">
										{#if update}
											<button
												class="btn btn-secondary btn-xs"
												onclick={() => openSingleUpdate(entry.key)}
											>
												Update
											</button>
										{/if}
									</span>
								</div>
							{/each}
						</div>
					</div>
				{/if}
			{/each}

			{#if Object.keys(versions).length === 0}
				<p class="text-muted empty-state">No version information available. Click "Check for Updates" to scan.</p>
			{/if}
		</div>

		<!-- Update History -->
		{#if updateHistory.length > 0}
			<Collapsible title="Update History" subtitle="{updateHistory.length} past update{updateHistory.length !== 1 ? 's' : ''}" badge={String(updateHistory.length)}>
				<div class="history-list">
					{#each updateHistory as result}
						<div class="history-item">
							<div class="history-info">
								<span class={result.success ? 'badge badge-success' : 'badge badge-danger'}>
									{result.success ? 'Success' : 'Failed'}
								</span>
								<span class="history-component">{result.component}</span>
								<span class="history-version mono">
									{result.old_version} &rarr; {result.new_version}
								</span>
							</div>
							<div class="history-meta">
								<span class="text-muted text-sm">
									{new Date(result.completed_at).toLocaleDateString()}
								</span>
								<span class="text-muted text-sm">
									{formatDuration(result.started_at, result.completed_at)}
								</span>
								{#if result.error}
									<span class="text-danger text-sm">{result.error}</span>
								{/if}
								{#if result.rollback_available}
									<button class="btn btn-secondary btn-xs" onclick={() => handleRollback(result.component)}>
										Rollback
									</button>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			</Collapsible>
		{/if}
	{/if}
</div>

<style>
	.updates-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	/* Header */
	.page-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	.header-left h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		margin-bottom: var(--space-xs);
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.header-breadcrumb {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		font-size: var(--text-xs);
		color: var(--text-muted);
		margin-bottom: var(--space-xs);
	}

	.breadcrumb-link {
		color: var(--accent);
		text-decoration: none;
	}

	.breadcrumb-link:hover {
		text-decoration: underline;
	}

	.breadcrumb-sep {
		color: var(--text-muted);
	}

	/* Loading */
	.loading-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--space-3xl);
		gap: var(--space-md);
	}

	.spinner {
		width: 32px;
		height: 32px;
		border: 3px solid var(--border-default);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	.spinner-sm {
		width: 16px;
		height: 16px;
		border: 2px solid var(--border-default);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	/* Update Banner */
	.update-banner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-md);
		padding: var(--space-md) var(--space-lg);
		background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 12%, transparent), color-mix(in srgb, var(--accent) 6%, transparent));
		border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
		border-radius: var(--radius-lg);
		flex-wrap: wrap;
	}

	.update-banner-content {
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	.update-banner-icon {
		color: var(--accent);
		flex-shrink: 0;
	}

	.update-banner-text {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.update-banner-title {
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--text-primary);
	}

	.update-banner-subtitle {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	.update-banner-actions {
		display: flex;
		gap: var(--space-sm);
		flex-shrink: 0;
	}

	/* Update Panel */
	.update-panel {
		position: relative;
	}

	.btn-close {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		padding: 0;
		background: none;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		color: var(--text-muted);
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.btn-close:hover {
		color: var(--text-primary);
		background: var(--bg-tertiary);
	}

	/* Update Selection */
	.selection-help {
		margin-bottom: var(--space-md);
	}

	.component-checklist {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
		margin-bottom: var(--space-lg);
	}

	.component-check-item {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		padding: var(--space-sm) 0;
		border-bottom: 1px solid var(--border-muted);
	}

	.component-check-item:last-child {
		border-bottom: none;
	}

	.check-label {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		cursor: pointer;
	}

	.check-label input[type='checkbox'] {
		margin-top: 3px;
		accent-color: var(--accent);
	}

	.check-info {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.check-header {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		flex-wrap: wrap;
	}

	.check-name {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
	}

	.check-version {
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	.check-size {
		font-size: var(--text-xs);
	}

	.changelog-content {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-secondary);
		white-space: pre-wrap;
		word-break: break-word;
		background: var(--bg-tertiary);
		padding: var(--space-sm);
		border-radius: var(--radius-sm);
		max-height: 200px;
		overflow-y: auto;
		margin-top: var(--space-sm);
	}

	.update-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-sm);
		padding-top: var(--space-md);
		border-top: 1px solid var(--border-muted);
	}

	/* Progress */
	.update-progress {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.progress-bar-container {
		width: 100%;
		height: 8px;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-full);
		overflow: hidden;
	}

	.progress-bar {
		height: 100%;
		background-color: var(--accent);
		border-radius: var(--radius-full);
		transition: width 0.3s ease;
	}

	.progress-label {
		font-size: var(--text-sm);
		color: var(--text-secondary);
		text-align: center;
	}

	.component-status-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.component-status-item {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xs) 0;
	}

	.component-status-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		height: 20px;
		flex-shrink: 0;
	}

	.component-status-name {
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-primary);
		flex: 1;
	}

	.component-status-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.log-area {
		background: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		padding: var(--space-sm) var(--space-md);
		margin-top: var(--space-sm);
	}

	.log-title {
		font-size: var(--text-xs);
		color: var(--accent);
	}

	/* Summary */
	.update-summary {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.summary-stats {
		display: flex;
		gap: var(--space-lg);
		flex-wrap: wrap;
	}

	.summary-stat {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		font-size: var(--text-sm);
		font-weight: 600;
	}

	.summary-success {
		color: var(--success);
	}

	.summary-fail {
		color: var(--danger);
	}

	.result-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.result-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-md);
		padding: var(--space-sm) 0;
		border-bottom: 1px solid var(--border-muted);
	}

	.result-item:last-child {
		border-bottom: none;
	}

	.result-info {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.result-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.result-icon-success {
		color: var(--success);
	}

	.result-icon-fail {
		color: var(--danger);
	}

	.result-info div {
		display: flex;
		flex-direction: column;
	}

	.result-name {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
	}

	.result-version {
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	.result-actions {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	/* Versions Table */
	.version-category {
		margin-bottom: var(--space-lg);
	}

	.version-category:last-child {
		margin-bottom: 0;
	}

	.category-title {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-bottom: var(--space-sm);
		padding-bottom: var(--space-xs);
		border-bottom: 1px solid var(--border-muted);
	}

	.version-table {
		width: 100%;
	}

	.version-table-header {
		display: grid;
		grid-template-columns: 2fr 1.5fr 1.5fr 1fr auto;
		gap: var(--space-md);
		padding: var(--space-xs) 0;
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		border-bottom: 1px solid var(--border-default);
	}

	.version-row {
		display: grid;
		grid-template-columns: 2fr 1.5fr 1.5fr 1fr auto;
		gap: var(--space-md);
		padding: var(--space-sm) 0;
		align-items: center;
		border-bottom: 1px solid var(--border-muted);
	}

	.version-row:last-child {
		border-bottom: none;
	}

	.vtcol-name {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.component-name {
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-primary);
	}

	.component-type {
		font-size: var(--text-xs);
	}

	.vtcol-current,
	.vtcol-latest {
		font-size: var(--text-sm);
	}

	.vtcol-status {
		display: flex;
	}

	.vtcol-action {
		display: flex;
		justify-content: flex-end;
	}

	.sort-controls {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.sort-btn {
		padding: 2px var(--space-sm);
		font-family: var(--font-sans);
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--text-muted);
		background: none;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.sort-btn:hover {
		color: var(--text-primary);
		background: var(--bg-tertiary);
	}

	.sort-active {
		color: var(--accent);
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 10%, transparent);
	}

	.empty-state {
		padding: var(--space-xl);
		text-align: center;
	}

	/* Release Notes */
	.release-notes {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.release-note-item {
		padding: var(--space-sm) 0;
		border-bottom: 1px solid var(--border-muted);
	}

	.release-note-item:last-child {
		border-bottom: none;
	}

	.release-note-header {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	.release-note-name {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
	}

	.release-note-version {
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	/* History */
	.history-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.history-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-md);
		padding: var(--space-sm) 0;
		border-bottom: 1px solid var(--border-muted);
		flex-wrap: wrap;
	}

	.history-item:last-child {
		border-bottom: none;
	}

	.history-info {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.history-component {
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-primary);
	}

	.history-version {
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	.history-meta {
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	/* Utility classes */
	.text-sm {
		font-size: var(--text-sm);
	}

	.text-xs {
		font-size: var(--text-xs);
	}

	.text-danger {
		color: var(--danger);
	}

	.text-success {
		color: var(--success);
	}

	.badge-muted {
		font-size: var(--text-xs);
		padding: 2px 8px;
		border-radius: var(--radius-sm);
		background: var(--bg-tertiary);
		color: var(--text-muted);
		font-weight: 500;
	}

	.btn-xs {
		padding: 2px var(--space-sm);
		font-size: var(--text-xs);
	}

	@media (max-width: 768px) {
		.page-header {
			flex-direction: column;
		}

		.update-banner {
			flex-direction: column;
		}

		.version-table-header,
		.version-row {
			grid-template-columns: 1.5fr 1fr 1fr auto;
		}

		.vtcol-latest {
			display: none;
		}

		.history-item {
			flex-direction: column;
			align-items: flex-start;
		}
	}

	@media (max-width: 480px) {
		.version-table-header,
		.version-row {
			grid-template-columns: 1fr auto;
		}

		.vtcol-current,
		.vtcol-latest {
			display: none;
		}
	}
</style>
