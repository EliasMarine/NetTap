<script lang="ts">
	import {
		getInvestigations,
		createInvestigation,
		updateInvestigation,
		deleteInvestigation,
		addNote,
		deleteNote,
		getInvestigationStats,
	} from '$api/investigations';
	import type { Investigation, InvestigationStats } from '$api/investigations';

	// ---------------------------------------------------------------------------
	// Types
	// ---------------------------------------------------------------------------

	type StatusFilter = 'all' | 'open' | 'in_progress' | 'resolved' | 'closed';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let investigations = $state<Investigation[]>([]);
	let stats = $state<InvestigationStats>({ total: 0, by_status: {}, by_severity: {} });
	let loading = $state(false);
	let activeFilter = $state<StatusFilter>('all');

	// Expanded investigation
	let expandedId = $state<string | null>(null);

	// New investigation form
	let showNewForm = $state(false);
	let newTitle = $state('');
	let newDescription = $state('');
	let newSeverity = $state('medium');
	let newTags = $state('');
	let creating = $state(false);

	// New note input per investigation
	let noteInputs = $state<Record<string, string>>({});

	// Delete confirmation
	let deleteConfirmId = $state<string | null>(null);

	// ---------------------------------------------------------------------------
	// Status filter tabs
	// ---------------------------------------------------------------------------

	const statusFilters: { value: StatusFilter; label: string }[] = [
		{ value: 'all', label: 'All' },
		{ value: 'open', label: 'Open' },
		{ value: 'in_progress', label: 'In Progress' },
		{ value: 'resolved', label: 'Resolved' },
		{ value: 'closed', label: 'Closed' },
	];

	// ---------------------------------------------------------------------------
	// Display helpers
	// ---------------------------------------------------------------------------

	function severityBadgeClass(severity: string): string {
		switch (severity) {
			case 'critical':
				return 'badge badge-danger';
			case 'high':
				return 'badge badge-warning';
			case 'medium':
				return 'badge badge-accent';
			case 'low':
				return 'badge badge-success';
			default:
				return 'badge';
		}
	}

	function statusBadgeClass(status: string): string {
		switch (status) {
			case 'open':
				return 'badge badge-accent';
			case 'in_progress':
				return 'badge badge-warning';
			case 'resolved':
				return 'badge badge-success';
			case 'closed':
				return 'badge';
			default:
				return 'badge';
		}
	}

	function statusLabel(status: string): string {
		switch (status) {
			case 'in_progress':
				return 'In Progress';
			default:
				return status.charAt(0).toUpperCase() + status.slice(1);
		}
	}

	function formatTimestamp(ts: string): string {
		try {
			const d = new Date(ts);
			return d.toLocaleString();
		} catch {
			return ts;
		}
	}

	function filterCount(filter: StatusFilter): number {
		if (filter === 'all') return stats.total;
		return stats.by_status[filter] ?? 0;
	}

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchInvestigations() {
		loading = true;
		try {
			const statusParam = activeFilter === 'all' ? undefined : activeFilter;
			const response = await getInvestigations({ status: statusParam });
			investigations = response.investigations;
		} catch {
			investigations = [];
		} finally {
			loading = false;
		}
	}

	async function fetchStats() {
		try {
			stats = await getInvestigationStats();
		} catch {
			stats = { total: 0, by_status: {}, by_severity: {} };
		}
	}

	async function fetchAll() {
		await Promise.all([fetchInvestigations(), fetchStats()]);
	}

	// ---------------------------------------------------------------------------
	// Filter change triggers refetch
	// ---------------------------------------------------------------------------

	let prevFilter: StatusFilter | null = null;

	$effect(() => {
		if (prevFilter !== null && prevFilter !== activeFilter) {
			fetchInvestigations();
		}
		prevFilter = activeFilter;
	});

	// ---------------------------------------------------------------------------
	// CRUD actions
	// ---------------------------------------------------------------------------

	async function handleCreate() {
		if (!newTitle.trim()) return;
		creating = true;
		try {
			const tags = newTags
				.split(',')
				.map((t) => t.trim())
				.filter(Boolean);
			await createInvestigation({
				title: newTitle.trim(),
				description: newDescription.trim(),
				severity: newSeverity,
				tags,
			});
			newTitle = '';
			newDescription = '';
			newSeverity = 'medium';
			newTags = '';
			showNewForm = false;
			await fetchAll();
		} finally {
			creating = false;
		}
	}

	async function handleStatusChange(inv: Investigation, newStatus: string) {
		await updateInvestigation(inv.id, { status: newStatus });
		await fetchAll();
	}

	async function handleDelete(id: string) {
		await deleteInvestigation(id);
		deleteConfirmId = null;
		if (expandedId === id) expandedId = null;
		await fetchAll();
	}

	async function handleAddNote(invId: string) {
		const content = noteInputs[invId]?.trim();
		if (!content) return;
		await addNote(invId, content);
		noteInputs[invId] = '';
		await fetchAll();
	}

	async function handleDeleteNote(invId: string, noteId: string) {
		await deleteNote(invId, noteId);
		await fetchAll();
	}

	// ---------------------------------------------------------------------------
	// Expand / collapse
	// ---------------------------------------------------------------------------

	function toggleExpand(id: string) {
		expandedId = expandedId === id ? null : id;
	}

	// ---------------------------------------------------------------------------
	// Initial fetch
	// ---------------------------------------------------------------------------

	$effect(() => {
		fetchAll();
	});
</script>

<svelte:head>
	<title>Investigations | NetTap</title>
</svelte:head>

<div class="investigations-page">
	<!-- Header -->
	<div class="page-header">
		<div class="header-left">
			<h2>Investigations</h2>
			<p class="text-muted">Track and manage security investigations</p>
		</div>
		<div class="header-actions">
			<button class="btn btn-primary btn-sm" onclick={() => (showNewForm = !showNewForm)}>
				<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
				</svg>
				New Investigation
			</button>
		</div>
	</div>

	<!-- New investigation form -->
	{#if showNewForm}
		<div class="card new-investigation-form">
			<h3>Create Investigation</h3>
			<div class="form-grid">
				<div class="form-group">
					<label for="inv-title">Title</label>
					<input
						id="inv-title"
						class="input"
						type="text"
						placeholder="Investigation title..."
						bind:value={newTitle}
					/>
				</div>
				<div class="form-group">
					<label for="inv-severity">Severity</label>
					<select id="inv-severity" class="input" bind:value={newSeverity}>
						<option value="low">Low</option>
						<option value="medium">Medium</option>
						<option value="high">High</option>
						<option value="critical">Critical</option>
					</select>
				</div>
				<div class="form-group form-group-full">
					<label for="inv-description">Description</label>
					<textarea
						id="inv-description"
						class="input"
						rows="3"
						placeholder="Describe the investigation..."
						bind:value={newDescription}
					></textarea>
				</div>
				<div class="form-group form-group-full">
					<label for="inv-tags">Tags (comma-separated)</label>
					<input
						id="inv-tags"
						class="input"
						type="text"
						placeholder="malware, c2, phishing..."
						bind:value={newTags}
					/>
				</div>
			</div>
			<div class="form-actions">
				<button class="btn btn-secondary btn-sm" onclick={() => (showNewForm = false)}>
					Cancel
				</button>
				<button
					class="btn btn-primary btn-sm"
					onclick={handleCreate}
					disabled={creating || !newTitle.trim()}
				>
					{creating ? 'Creating...' : 'Create Investigation'}
				</button>
			</div>
		</div>
	{/if}

	<!-- Filter tabs -->
	<div class="filter-tabs">
		{#each statusFilters as filter}
			<button
				class="filter-tab"
				class:active={activeFilter === filter.value}
				onclick={() => (activeFilter = filter.value)}
			>
				{filter.label}
				<span class="filter-count">
					{filterCount(filter.value)}
				</span>
			</button>
		{/each}
	</div>

	<!-- Investigation list -->
	{#if loading && investigations.length === 0}
		<div class="loading-state">
			<div class="spinner"></div>
			<p class="text-muted">Loading investigations...</p>
		</div>
	{:else if investigations.length === 0}
		<div class="empty-state">
			<div class="empty-icon">
				<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
					<path d="M16 4h2a2 2 0 012 2v14a2 2 0 01-2 2H6a2 2 0 01-2-2V6a2 2 0 012-2h2" />
					<rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
				</svg>
			</div>
			<h3>No Investigations</h3>
			<p class="text-muted">
				Create an investigation to track and manage security incidents.
				Click "New Investigation" above to get started.
			</p>
		</div>
	{:else}
		<div class="investigation-list">
			{#each investigations as inv (inv.id)}
				<div class="card investigation-card" class:expanded={expandedId === inv.id}>
					<!-- Card header (always visible) -->
					<button
						class="investigation-card-header"
						onclick={() => toggleExpand(inv.id)}
					>
						<div class="inv-header-left">
							<span class={severityBadgeClass(inv.severity)}>
								{inv.severity.toUpperCase()}
							</span>
							<span class={statusBadgeClass(inv.status)}>
								{statusLabel(inv.status)}
							</span>
							<h4 class="inv-title">{inv.title}</h4>
						</div>
						<div class="inv-header-right">
							<div class="inv-meta-badges">
								{#if inv.alert_ids.length > 0}
									<span class="meta-badge" title="Linked alerts">
										<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" /></svg>
										{inv.alert_ids.length}
									</span>
								{/if}
								{#if inv.device_ips.length > 0}
									<span class="meta-badge" title="Linked devices">
										<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" /></svg>
										{inv.device_ips.length}
									</span>
								{/if}
								{#if inv.notes.length > 0}
									<span class="meta-badge" title="Notes">
										<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" /></svg>
										{inv.notes.length}
									</span>
								{/if}
							</div>
							{#if inv.tags.length > 0}
								<div class="inv-tags">
									{#each inv.tags.slice(0, 3) as tag}
										<span class="tag">{tag}</span>
									{/each}
									{#if inv.tags.length > 3}
										<span class="tag tag-more">+{inv.tags.length - 3}</span>
									{/if}
								</div>
							{/if}
							<span class="inv-timestamp mono">{formatTimestamp(inv.created_at)}</span>
							<svg
								class="expand-icon"
								class:rotate={expandedId === inv.id}
								viewBox="0 0 24 24"
								width="16"
								height="16"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<polyline points="6 9 12 15 18 9" />
							</svg>
						</div>
					</button>

					<!-- Expanded details -->
					{#if expandedId === inv.id}
						<div class="investigation-details">
							<!-- Description -->
							{#if inv.description}
								<div class="detail-section">
									<h5>Description</h5>
									<p class="inv-description">{inv.description}</p>
								</div>
							{/if}

							<!-- Status change -->
							<div class="detail-section">
								<h5>Change Status</h5>
								<div class="status-actions">
									<select
										class="input input-sm"
										value={inv.status}
										onchange={(e) => handleStatusChange(inv, (e.target as HTMLSelectElement).value)}
									>
										<option value="open">Open</option>
										<option value="in_progress">In Progress</option>
										<option value="resolved">Resolved</option>
										<option value="closed">Closed</option>
									</select>
								</div>
							</div>

							<!-- Linked alerts -->
							{#if inv.alert_ids.length > 0}
								<div class="detail-section">
									<h5>Linked Alerts ({inv.alert_ids.length})</h5>
									<div class="linked-items">
										{#each inv.alert_ids as alertId}
											<span class="linked-item">
												<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" /></svg>
												{alertId}
											</span>
										{/each}
									</div>
								</div>
							{/if}

							<!-- Linked devices -->
							{#if inv.device_ips.length > 0}
								<div class="detail-section">
									<h5>Linked Devices ({inv.device_ips.length})</h5>
									<div class="linked-items">
										{#each inv.device_ips as ip}
											<a href="/devices/{ip}" class="linked-item linked-device">
												<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" /></svg>
												{ip}
											</a>
										{/each}
									</div>
								</div>
							{/if}

							<!-- Notes -->
							<div class="detail-section">
								<h5>Notes ({inv.notes.length})</h5>
								{#if inv.notes.length > 0}
									<div class="notes-list">
										{#each inv.notes as note (note.id)}
											<div class="note-card">
												<p class="note-content">{note.content}</p>
												<div class="note-meta">
													<span class="mono text-muted">{formatTimestamp(note.created_at)}</span>
													<button
														class="btn-icon btn-danger-icon"
														title="Delete note"
														onclick={() => handleDeleteNote(inv.id, note.id)}
													>
														<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
															<polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
														</svg>
													</button>
												</div>
											</div>
										{/each}
									</div>
								{/if}

								<!-- Add note form -->
								<div class="add-note-form">
									<textarea
										class="input"
										rows="2"
										placeholder="Add a note..."
										value={noteInputs[inv.id] ?? ''}
										oninput={(e) => (noteInputs[inv.id] = (e.target as HTMLTextAreaElement).value)}
									></textarea>
									<button
										class="btn btn-secondary btn-sm"
										onclick={() => handleAddNote(inv.id)}
										disabled={!noteInputs[inv.id]?.trim()}
									>
										Save Note
									</button>
								</div>
							</div>

							<!-- Tags -->
							{#if inv.tags.length > 0}
								<div class="detail-section">
									<h5>Tags</h5>
									<div class="tags-list">
										{#each inv.tags as tag}
											<span class="tag">{tag}</span>
										{/each}
									</div>
								</div>
							{/if}

							<!-- Delete -->
							<div class="detail-section detail-section-danger">
								{#if deleteConfirmId === inv.id}
									<p class="text-danger">Are you sure you want to delete this investigation? This cannot be undone.</p>
									<div class="delete-actions">
										<button class="btn btn-secondary btn-sm" onclick={() => (deleteConfirmId = null)}>
											Cancel
										</button>
										<button class="btn btn-danger btn-sm" onclick={() => handleDelete(inv.id)}>
											Delete Investigation
										</button>
									</div>
								{:else}
									<button class="btn btn-danger btn-sm" onclick={() => (deleteConfirmId = inv.id)}>
										<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
											<polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
										</svg>
										Delete Investigation
									</button>
								{/if}
							</div>
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.investigations-page {
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

	/* Filter tabs */
	.filter-tabs {
		display: flex;
		gap: 2px;
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-xs);
		overflow-x: auto;
	}

	.filter-tab {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		padding: var(--space-sm) var(--space-md);
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-secondary);
		background: none;
		border: none;
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition: all var(--transition-fast);
		white-space: nowrap;
	}

	.filter-tab:hover {
		color: var(--text-primary);
		background-color: var(--bg-tertiary);
	}

	.filter-tab.active {
		color: var(--accent);
		background-color: var(--accent-muted);
	}

	.filter-count {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 20px;
		height: 20px;
		padding: 0 6px;
		font-size: var(--text-xs);
		font-weight: 600;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-full);
	}

	.filter-tab.active .filter-count {
		background-color: var(--accent);
		color: #fff;
	}

	/* Loading state */
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

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	/* Empty state */
	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--space-3xl);
		text-align: center;
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
	}

	.empty-icon {
		color: var(--text-muted);
		margin-bottom: var(--space-md);
	}

	.empty-state h3 {
		font-size: var(--text-xl);
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: var(--space-sm);
	}

	.empty-state p {
		max-width: 480px;
		line-height: var(--leading-relaxed);
	}

	/* New investigation form */
	.new-investigation-form {
		padding: var(--space-lg);
	}

	.new-investigation-form h3 {
		font-size: var(--text-lg);
		font-weight: 600;
		margin-bottom: var(--space-md);
	}

	.form-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-md);
	}

	.form-group {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.form-group-full {
		grid-column: 1 / -1;
	}

	.form-group label {
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-secondary);
	}

	.form-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-sm);
		margin-top: var(--space-md);
		padding-top: var(--space-md);
		border-top: 1px solid var(--border-default);
	}

	/* Investigation list */
	.investigation-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.investigation-card {
		padding: 0;
		overflow: hidden;
		transition: border-color var(--transition-fast);
	}

	.investigation-card:hover {
		border-color: var(--accent);
	}

	.investigation-card.expanded {
		border-color: var(--accent);
	}

	/* Card header */
	.investigation-card-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-md);
		padding: var(--space-md);
		width: 100%;
		background: none;
		border: none;
		cursor: pointer;
		font-family: var(--font-sans);
		text-align: left;
	}

	.investigation-card-header:hover {
		background-color: var(--bg-tertiary);
	}

	.inv-header-left {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		min-width: 0;
		flex: 1;
	}

	.inv-title {
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.inv-header-right {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		flex-shrink: 0;
	}

	.inv-meta-badges {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
	}

	.meta-badge {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		padding: 2px 6px;
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--text-secondary);
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-sm);
	}

	.inv-tags {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
	}

	.tag {
		display: inline-block;
		padding: 1px 8px;
		font-size: 11px;
		font-weight: 500;
		color: var(--text-secondary);
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-full);
	}

	.tag-more {
		color: var(--text-muted);
	}

	.inv-timestamp {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.expand-icon {
		transition: transform var(--transition-fast);
		color: var(--text-muted);
		flex-shrink: 0;
	}

	.expand-icon.rotate {
		transform: rotate(180deg);
	}

	/* Expanded details */
	.investigation-details {
		border-top: 1px solid var(--border-default);
		padding: var(--space-md);
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.detail-section h5 {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-secondary);
		margin-bottom: var(--space-sm);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.inv-description {
		font-size: var(--text-sm);
		line-height: var(--leading-relaxed);
		color: var(--text-primary);
	}

	/* Status actions */
	.status-actions {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.input-sm {
		padding: var(--space-xs) var(--space-sm);
		font-size: var(--text-sm);
	}

	/* Linked items */
	.linked-items {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
	}

	.linked-item {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 3px 10px;
		font-size: var(--text-xs);
		font-family: var(--font-mono);
		color: var(--text-secondary);
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		border: 1px solid var(--border-default);
	}

	.linked-device {
		text-decoration: none;
		transition: border-color var(--transition-fast), color var(--transition-fast);
	}

	.linked-device:hover {
		border-color: var(--accent);
		color: var(--accent);
		text-decoration: none;
	}

	/* Notes */
	.notes-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		margin-bottom: var(--space-md);
	}

	.note-card {
		padding: var(--space-sm) var(--space-md);
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-md);
		border: 1px solid var(--border-default);
	}

	.note-content {
		font-size: var(--text-sm);
		line-height: var(--leading-normal);
		color: var(--text-primary);
		margin-bottom: var(--space-xs);
	}

	.note-meta {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.btn-icon {
		background: none;
		border: none;
		cursor: pointer;
		padding: 2px;
		border-radius: var(--radius-sm);
		color: var(--text-muted);
		transition: color var(--transition-fast);
	}

	.btn-danger-icon:hover {
		color: var(--danger);
	}

	.add-note-form {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		align-items: flex-end;
	}

	.add-note-form textarea {
		width: 100%;
	}

	/* Tags list */
	.tags-list {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
	}

	/* Danger section */
	.detail-section-danger {
		padding-top: var(--space-md);
		border-top: 1px solid var(--border-default);
	}

	.text-danger {
		color: var(--danger);
		font-size: var(--text-sm);
		margin-bottom: var(--space-sm);
	}

	.delete-actions {
		display: flex;
		gap: var(--space-sm);
	}

	/* Responsive */
	@media (max-width: 768px) {
		.page-header {
			flex-direction: column;
		}

		.header-actions {
			width: 100%;
			justify-content: flex-end;
		}

		.investigation-card-header {
			flex-direction: column;
			align-items: flex-start;
		}

		.inv-header-right {
			flex-wrap: wrap;
		}

		.form-grid {
			grid-template-columns: 1fr;
		}
	}

	@media (max-width: 640px) {
		.inv-tags {
			display: none;
		}
	}
</style>
