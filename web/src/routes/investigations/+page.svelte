<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
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
	import DetailDrawer from '$components/DetailDrawer.svelte';
	import InvestigationDrawerContent from '$components/drawer/content/InvestigationDrawerContent.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import type { SeverityLevel } from '$lib/utils/severity';
	import { registerPageRefresh, type LoadGuard, type LoadResult, outcome } from '$lib/stores/pageRefresh';

	// ---------------------------------------------------------------------------
	// Types
	// ---------------------------------------------------------------------------

	type StatusFilter = 'all' | 'open' | 'in_progress' | 'resolved' | 'closed';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	const NO_STATS: InvestigationStats = { total: 0, by_status: {}, by_severity: {} };

	let investigations = $state<Investigation[]>([]);
	let stats = $state<InvestigationStats>(NO_STATS);
	// OLD CODE START — 2026-11-03 redesign: loading started false, and the counts showed their 0
	// defaults until the first stats reply; now nothing shows a number before it has loaded
	// let loading = $state(false);
	// OLD CODE END
	let loading = $state(true);
	// #96: a failed request must not read as "No Investigations" or zero counts
	let listFailed = $state(false);
	let statsFailed = $state(false);
	let statsLoaded = $state(false);
	// #96: a failed save, delete or note looked like it worked; say so and keep what was typed
	let actionError = $state<string | null>(null);
	function failed(what: string): void {
		actionError = `Couldn't ${what}: the request failed.`;
	}
	let activeFilter = $state<StatusFilter>('all');

	// The investigation whose details are open beside the table
	let expandedId = $state<string | null>(null);
	let expanded = $derived(investigations.find((inv) => inv.id === expandedId) ?? null);

	// Detail drawer state
	let drawerInvestigation = $state<Investigation | null>(null);
	let drawerTab = $state('details');
	const INV_DRAWER_TABS = [
		{ id: 'details', label: 'Details' },
		{ id: 'notes', label: 'Notes' },
		{ id: 'linked', label: 'Linked Items' },
	];

	function openDrawer(inv: Investigation) {
		drawerInvestigation = inv;
		drawerTab = 'details';
	}

	function closeDrawer() {
		drawerInvestigation = null;
		drawerTab = 'details';
	}

	async function handleDrawerStatusChange(id: string, status: string) {
		if (!(await updateInvestigation(id, { status }))) failed('change the status');
		refresh.run();
	}

	async function handleDrawerNoteAdded(id: string, noteText: string) {
		if (!(await addNote(id, noteText))) failed('save the note');
		refresh.run();
	}

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
	// Status filter
	// ---------------------------------------------------------------------------

	const statusFilters: { value: StatusFilter; label: string }[] = [
		{ value: 'all', label: 'All' },
		{ value: 'open', label: 'Open' },
		{ value: 'in_progress', label: 'In progress' },
		{ value: 'resolved', label: 'Resolved' },
		{ value: 'closed', label: 'Closed' },
	];

	// ---------------------------------------------------------------------------
	// Display helpers
	// ---------------------------------------------------------------------------

	// OLD CODE START — 2026-11-03 redesign: legacy badge classes; severity is a SeverityPill and
	// status a system chip now (severityLevel, statusChip)
	// function severityBadgeClass(severity: string): string {
	// 	switch (severity) {
	// 		case 'critical': return 'badge severity-critical';
	// 		case 'high': return 'badge severity-high';
	// 		case 'medium': return 'badge severity-medium';
	// 		case 'low': return 'badge severity-low';
	// 		default: return 'badge severity-info';
	// 	}
	// }
	// function statusBadgeClass(status: string): string {
	// 	switch (status) {
	// 		case 'open': return 'badge badge-accent';
	// 		case 'in_progress': return 'badge badge-warning';
	// 		case 'resolved': return 'badge badge-success';
	// 		case 'closed': return 'badge';
	// 		default: return 'badge';
	// 	}
	// }
	// OLD CODE END

	const SEVERITY_RANK: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 };
	const STATUS_ORDER: Record<string, number> = { open: 0, in_progress: 1, resolved: 2, closed: 3 };

	/** Unknown severities show as Info, as the old badge did. */
	function severityLevel(severity: string): SeverityLevel {
		return severity in SEVERITY_RANK ? (severity as SeverityLevel) : 'info';
	}

	function statusChip(status: string): string {
		if (status === 'in_progress') return 'is-warn';
		if (status === 'resolved') return 'is-ok';
		return '';
	}

	function severityLabel(severity: string): string {
		switch (severity) {
			case 'critical':
				return 'Critical';
			case 'high':
				return 'High';
			case 'medium':
				return 'Medium';
			case 'low':
				return 'Low';
			default:
				return severity.charAt(0).toUpperCase() + severity.slice(1);
		}
	}

	function statusLabel(status: string): string {
		switch (status) {
			case 'in_progress':
				return 'In progress';
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

	/** A count, or "—" while the stats are loading or after they failed (#96: never a stand-in 0). */
	function countText(filter: StatusFilter): string {
		return statsLoaded && !statsFailed ? filterCount(filter).toLocaleString() : '—';
	}

	let filterOptions = $derived(
		statusFilters.map((f) => ({ value: f.value, label: `${f.label} · ${countText(f.value)}` })),
	);

	const columns: Column<Investigation>[] = [
		{ key: 'title', label: 'Investigation', sortValue: (r) => r.title.toLowerCase(), cell: titleCell },
		{ key: 'severity', label: 'Severity', sortValue: (r) => SEVERITY_RANK[r.severity] ?? 0, cell: severityCell },
		{ key: 'status', label: 'Status', sortValue: (r) => STATUS_ORDER[r.status] ?? 9, cell: statusCell },
		{ key: 'alerts', label: 'Alerts', numeric: true, sortValue: (r) => r.alert_ids.length, cell: alertsCell },
		{ key: 'devices', label: 'Devices', numeric: true, sortValue: (r) => r.device_ips.length, cell: devicesCell },
		{ key: 'notes', label: 'Notes', numeric: true, sortValue: (r) => r.notes.length, cell: notesCell },
		{ key: 'tags', label: 'Tags', sortValue: (r) => r.tags.join(', ').toLowerCase(), cell: tagsCell },
		{ key: 'created_at', label: 'Created', sortValue: (r) => Date.parse(r.created_at) || 0, cell: createdCell },
	];

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	// OLD CODE START — 2026-11-03 redesign: two loaders that wrote state whenever they finished,
	// so a slow reply for an old filter could overwrite a newer one. One guarded loader now
	// feeds the page refresh contract (PLAN.md §5.5); a filter change runs it too.
	// async function fetchInvestigations() {
	// 	loading = true;
	// 	try {
	// 		const statusParam = activeFilter === 'all' ? undefined : activeFilter;
	// 		const response = await getInvestigations({ status: statusParam });
	// 		investigations = response.investigations;
	// 		listFailed = false;
	// 	} catch {
	// 		investigations = [];
	// 		listFailed = true;
	// 	} finally {
	// 		loading = false;
	// 	}
	// }
	// async function fetchStats() {
	// 	try {
	// 		stats = await getInvestigationStats();
	// 		statsFailed = false;
	// 	} catch {
	// 		stats = { total: 0, by_status: {}, by_severity: {} };
	// 		statsFailed = true;
	// 	}
	// }
	// async function fetchAll() {
	// 	await Promise.all([fetchInvestigations(), fetchStats()]);
	// }
	// let prevFilter: StatusFilter | null = null;
	// $effect(() => {
	// 	if (prevFilter !== null && prevFilter !== activeFilter) {
	// 		fetchInvestigations();
	// 	}
	// 	prevFilter = activeFilter;
	// });
	// $effect(() => {
	// 	fetchAll();
	// });
	// OLD CODE END

	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const status = activeFilter === 'all' ? undefined : activeFilter;
		loading = true;
		const [list, counts] = await Promise.allSettled([getInvestigations({ status }), getInvestigationStats()]);
		if (!guard.current(g)) return 'skipped';
		if (list.status === 'fulfilled') {
			investigations = list.value.investigations;
			listFailed = false;
		} else {
			investigations = [];
			listFailed = true;
		}
		if (counts.status === 'fulfilled') {
			stats = counts.value;
			statsFailed = false;
			statsLoaded = true;
		} else {
			stats = NO_STATS;
			statsFailed = true;
		}
		loading = false;
		// OLD CODE START — counted by hand; outcome() in pageRefresh is the shared rule
		// const ok = [list, counts].filter((r) => r.status === 'fulfilled').length;
		// return ok === 2 ? 'ok' : ok === 0 ? 'failed' : 'partial';
		// OLD CODE END
		return outcome([list, counts]);
	}

	const refresh = registerPageRefresh(load);
	onMount(() => {
		refresh.run();
	});
	onDestroy(() => refresh.unregister());

	function changeFilter(next: StatusFilter) {
		activeFilter = next;
		refresh.run();
	}

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
			try {
				await createInvestigation({
					title: newTitle.trim(),
					description: newDescription.trim(),
					severity: newSeverity,
					tags,
				});
			} catch {
				failed('create the investigation');
				return;
			}
			newTitle = '';
			newDescription = '';
			newSeverity = 'medium';
			newTags = '';
			showNewForm = false;
			await refresh.run();
		} finally {
			creating = false;
		}
	}

	async function handleStatusChange(inv: Investigation, newStatus: string) {
		if (!(await updateInvestigation(inv.id, { status: newStatus }))) failed('change the status');
		await refresh.run();
	}

	async function handleDelete(id: string) {
		if (!(await deleteInvestigation(id))) {
			failed('delete the investigation');
			return;
		}
		deleteConfirmId = null;
		if (expandedId === id) expandedId = null;
		await refresh.run();
	}

	async function handleAddNote(invId: string) {
		const content = noteInputs[invId]?.trim();
		if (!content) return;
		if (!(await addNote(invId, content))) {
			failed('save the note');
			return;
		}
		noteInputs[invId] = '';
		await refresh.run();
	}

	async function handleDeleteNote(invId: string, noteId: string) {
		if (!(await deleteNote(invId, noteId))) failed('delete the note');
		await refresh.run();
	}

	// ---------------------------------------------------------------------------
	// Expand / collapse
	// ---------------------------------------------------------------------------

	function toggleExpand(id: string) {
		expandedId = expandedId === id ? null : id;
	}
</script>

{#snippet titleCell(inv: Investigation)}<span class="inv-title">{inv.title}</span>{/snippet}
{#snippet severityCell(inv: Investigation)}<SeverityPill level={severityLevel(inv.severity)} />{/snippet}
{#snippet statusCell(inv: Investigation)}<span class="chip {statusChip(inv.status)}">{statusLabel(inv.status)}</span>{/snippet}
{#snippet alertsCell(inv: Investigation)}{inv.alert_ids.length}{/snippet}
{#snippet devicesCell(inv: Investigation)}{inv.device_ips.length}{/snippet}
{#snippet notesCell(inv: Investigation)}{inv.notes.length}{/snippet}
{#snippet tagsCell(inv: Investigation)}
	{#if inv.tags.length > 0}
		<span class="tags">
			{#each inv.tags.slice(0, 3) as tag}<span class="tag">{tag}</span>{/each}
			{#if inv.tags.length > 3}<span class="tag">+{inv.tags.length - 3}</span>{/if}
		</span>
	{:else}<span class="dim">None</span>{/if}
{/snippet}
{#snippet createdCell(inv: Investigation)}<span class="dim num">{formatTimestamp(inv.created_at)}</span>{/snippet}

<svelte:head>
	<title>Investigations | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">Investigations</h1>
		<p class="page-sub">Track and manage security investigations</p>
	</div>
	<div class="head-actions">
		<button class="btn primary" onclick={() => (showNewForm = !showNewForm)}>New investigation</button>
	</div>
</div>

{#if actionError}
	<div class="notice is-error" role="alert">
		<Icon name="warn" />
		<span class="grow">{actionError}</span>
		<button class="btn" onclick={() => (actionError = null)}>Dismiss</button>
	</div>
{/if}

<div class="grid inv-layout">
	<KpiCard class="c-3" label="Investigations" icon="logs" value={countText('all')} note={statsFailed ? "Couldn't load the counts" : 'All time'} />
	<KpiCard class="c-3" label="Open" icon="alerts" value={countText('open')} note={statsFailed ? "Couldn't load the counts" : 'Not started yet'} />
	<KpiCard class="c-3" label="In progress" icon="refresh" value={countText('in_progress')} note={statsFailed ? "Couldn't load the counts" : 'Being worked on'} />
	<KpiCard class="c-3" label="Resolved" icon="check" value={countText('resolved')} note={statsFailed ? "Couldn't load the counts" : 'Fixed, not yet closed'} />

	<!-- New investigation form -->
	{#if showNewForm}
		<Card title="New investigation" sub="Saved to NetTap's investigation log" class="c-12">
			<div class="form-grid">
				<div class="field">
					<label class="label" for="inv-title">Title</label>
					<input id="inv-title" class="input" type="text" placeholder="Investigation title…" bind:value={newTitle} />
				</div>
				<div class="field">
					<label class="label" for="inv-severity">Severity</label>
					<select id="inv-severity" class="select" bind:value={newSeverity}>
						<option value="low">Low</option>
						<option value="medium">Medium</option>
						<option value="high">High</option>
						<option value="critical">Critical</option>
					</select>
				</div>
				<div class="field full">
					<label class="label" for="inv-description">Description</label>
					<textarea
						id="inv-description"
						class="textarea"
						rows="3"
						placeholder="Describe the investigation…"
						bind:value={newDescription}
					></textarea>
				</div>
				<div class="field full">
					<label class="label" for="inv-tags">Tags (comma-separated)</label>
					<input id="inv-tags" class="input" type="text" placeholder="malware, c2, phishing…" bind:value={newTags} />
				</div>
			</div>
			<div class="form-actions">
				<button class="btn" onclick={() => (showNewForm = false)}>Cancel</button>
				<button class="btn primary" onclick={handleCreate} disabled={creating || !newTitle.trim()}>
					{creating ? 'Creating…' : 'Create investigation'}
				</button>
			</div>
		</Card>
	{/if}

	<Card
		title="All investigations"
		sub={listFailed ? 'The list failed to load' : `${investigations.length.toLocaleString()} shown · all time`}
		class={expanded ? 'c-8' : 'c-12'}
	>
		{#snippet actions()}
			<Pills options={filterOptions} value={activeFilter} onchange={changeFilter} ariaLabel="Status" />
		{/snippet}

		{#if loading && investigations.length === 0}
			<CardState state="loading" title="Loading investigations" />
		{:else if listFailed}
			<CardState
				state="error"
				title="Couldn't load investigations: the request failed."
				message="Check that NetTap is running on the System page, then try again."
				onaction={() => refresh.run()}
			/>
		{:else if investigations.length === 0}
			<CardState
				state="empty"
				icon="logs"
				title={activeFilter === 'all' ? 'No investigations yet' : 'No investigations with this status'}
				message="Investigations appear here once you create one. Use New investigation to start tracking a security incident."
			/>
		{:else}
			<DataTable
				{columns}
				rows={investigations}
				ariaLabel="Investigations"
				rowKey={(inv) => inv.id}
				onrowactivate={(inv) => toggleExpand(inv.id)}
				rowLabel={(inv) => `Open investigation ${inv.title}`}
				selectedKey={expandedId ?? undefined}
			/>
		{/if}
	</Card>

	<!-- The open investigation, beside the table (below it under 1100 px) -->
	{#if expanded}
		{@const inv = expanded}
		<Card title={inv.title} sub="{severityLabel(inv.severity)} · {statusLabel(inv.status)} · opened {formatTimestamp(inv.created_at)}" class="c-4 inv-detail">
			{#snippet actions()}
				<button class="icon-btn ghost" aria-label="Close details" onclick={() => (expandedId = null)}><Icon name="close" /></button>
			{/snippet}

			<div class="stack">
				{#if inv.description}
					<p class="body-text">{inv.description}</p>
				{/if}

				<div class="field">
					<label class="label" for="inv-status-{inv.id}">Status</label>
					<select
						id="inv-status-{inv.id}"
						class="select"
						value={inv.status}
						onchange={(e) => handleStatusChange(inv, (e.target as HTMLSelectElement).value)}
					>
						<option value="open">Open</option>
						<option value="in_progress">In progress</option>
						<option value="resolved">Resolved</option>
						<option value="closed">Closed</option>
					</select>
				</div>

				{#if inv.alert_ids.length > 0}
					<section>
						<h3 class="eyebrow">Linked alerts ({inv.alert_ids.length})</h3>
						<ul class="linked">
							{#each inv.alert_ids as alertId}
								<li><Icon name="alerts" /><span class="mono">{alertId}</span></li>
							{/each}
						</ul>
					</section>
				{/if}

				{#if inv.device_ips.length > 0}
					<section>
						<h3 class="eyebrow">Linked devices ({inv.device_ips.length})</h3>
						<ul class="linked">
							{#each inv.device_ips as ip}
								<li><Icon name="devices" /><a class="link mono" href="/devices/{ip}">{ip}</a></li>
							{/each}
						</ul>
					</section>
				{/if}

				<section>
					<h3 class="eyebrow">Notes ({inv.notes.length})</h3>
					{#if inv.notes.length > 0}
						<ul class="notes">
							{#each inv.notes as note (note.id)}
								<li class="note">
									<p class="body-text">{note.content}</p>
									<div class="note-meta">
										<span class="dim num">{formatTimestamp(note.created_at)}</span>
										<button
											class="icon-btn ghost"
											aria-label="Delete note"
											title="Delete note"
											onclick={() => handleDeleteNote(inv.id, note.id)}><Icon name="close" /></button
										>
									</div>
								</li>
							{/each}
						</ul>
					{/if}
					<div class="add-note">
						<label class="sr-only" for="inv-note-{inv.id}">Add a note</label>
						<textarea
							id="inv-note-{inv.id}"
							class="textarea"
							rows="2"
							placeholder="Add a note…"
							value={noteInputs[inv.id] ?? ''}
							oninput={(e) => (noteInputs[inv.id] = (e.target as HTMLTextAreaElement).value)}
						></textarea>
						<button class="btn" onclick={() => handleAddNote(inv.id)} disabled={!noteInputs[inv.id]?.trim()}>
							Save note
						</button>
					</div>
				</section>

				{#if inv.tags.length > 0}
					<section>
						<h3 class="eyebrow">Tags</h3>
						<div class="tags">
							{#each inv.tags as tag}<span class="tag">{tag}</span>{/each}
						</div>
					</section>
				{/if}

				<div class="actions">
					<button class="btn" onclick={() => openDrawer(inv)}>View full details</button>
				</div>

				<div class="danger-zone">
					{#if deleteConfirmId === inv.id}
						<p class="body-text">Delete this investigation? This can't be undone.</p>
						<div class="actions">
							<button class="btn" onclick={() => (deleteConfirmId = null)}>Cancel</button>
							<button class="btn danger" onclick={() => handleDelete(inv.id)}>Delete investigation</button>
						</div>
					{:else}
						<button class="btn danger" onclick={() => (deleteConfirmId = inv.id)}>Delete investigation</button>
					{/if}
				</div>
			</div>
		</Card>
	{/if}
</div>

<!-- Detail Drawer -->
<DetailDrawer
	open={!!drawerInvestigation}
	title={drawerInvestigation?.title ?? ''}
	subtitle={drawerInvestigation ? `${severityLabel(drawerInvestigation.severity)} — ${statusLabel(drawerInvestigation.status)}` : ''}
	tabs={INV_DRAWER_TABS}
	activeTab={drawerTab}
	onclose={closeDrawer}
	ontabchange={(tab) => (drawerTab = tab)}
>
	{#snippet children()}
		{#if drawerInvestigation}
			<InvestigationDrawerContent
				investigation={drawerInvestigation}
				activeTab={drawerTab}
				onstatuschange={(_id, status) => handleDrawerStatusChange(_id, status)}
				onnoteadded={(_id, note) => handleDrawerNoteAdded(_id, note)}
			/>
		{/if}
	{/snippet}
	{#snippet actions()}
		<button class="btn" onclick={closeDrawer}>Close</button>
	{/snippet}
</DetailDrawer>

<style>
	.grow {
		flex: 1;
		align-self: center;
	}

	.field.full {
		grid-column: 1 / -1;
	}

	.inv-title {
		font-weight: 700;
		white-space: normal;
	}

	.tags {
		display: inline-flex;
		flex-wrap: wrap;
		gap: var(--sp-1);
	}

	/* The detail card sits beside the table like the alert drawer, and below it under 1100 px */
	.inv-layout > :global(.inv-detail) {
		position: sticky;
		top: var(--sp-4);
		align-self: start;
	}

	.body-text {
		font-size: var(--text-sm);
		color: var(--text-2);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}

	section {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}

	.linked {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
		font-size: var(--text-sm);
	}

	.linked li {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		min-width: 0;
	}

	.linked li :global(.ic) {
		width: 14px;
		height: 14px;
		color: var(--text-3);
	}

	.notes {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}

	.note {
		padding: var(--sp-3);
		border-radius: var(--r-md);
		background: var(--surface-2);
		border: 1px solid var(--line);
	}

	.note-meta {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--sp-2);
		margin-top: var(--sp-1);
		font-size: var(--text-xs);
	}

	.add-note {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: var(--sp-2);
	}

	.danger-zone {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
		padding-top: var(--sp-4);
		border-top: 1px solid var(--line);
	}

	.btn.danger {
		color: var(--sev-critical);
	}

	/* Keep the close button beside a long title */
	.inv-layout > :global(.inv-detail > .card-head) {
		flex-wrap: nowrap;
	}

	@container app (max-width: 1100px) {
		.inv-layout > :global(.inv-detail) {
			grid-column: span 12;
			position: static;
		}
	}
</style>
