<!--
  InvestigationDrawerContent.svelte — Details, Notes, and Linked Items tabs.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import DrawerSection from '../DrawerSection.svelte';
	import KVRow from '../KVRow.svelte';
	import type { Investigation } from '$api/investigations';

	let {
		investigation,
		activeTab,
		onstatuschange = (_id: string, _status: string) => {},
		onnoteadded = (_id: string, _note: string) => {},
	}: {
		investigation: Investigation;
		activeTab: string;
		onstatuschange?: (id: string, status: string) => void;
		onnoteadded?: (id: string, note: string) => void;
	} = $props();

	// Note state
	let noteText = $state('');
	let noteSaving = $state(false);

	function formatTimestamp(ts: string): string {
		if (!ts) return '--';
		try {
			return new Date(ts).toLocaleString(undefined, {
				year: 'numeric', month: 'short', day: 'numeric',
				hour: '2-digit', minute: '2-digit',
			});
		} catch {
			return ts;
		}
	}

	function timeAgo(ts: string): string {
		const diff = Date.now() - new Date(ts).getTime();
		if (diff < 60_000) return 'just now';
		if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
		if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
		return `${Math.floor(diff / 86_400_000)}d ago`;
	}

	function getStatusColor(status: string): string {
		switch (status) {
			case 'open': return 'var(--amber)';
			case 'in_progress': return 'var(--accent)';
			case 'closed': return 'var(--green)';
			default: return 'var(--text-muted)';
		}
	}

	async function handleAddNote() {
		if (!noteText.trim()) return;
		noteSaving = true;
		try {
			onnoteadded(investigation.id, noteText.trim());
			noteText = '';
		} finally {
			noteSaving = false;
		}
	}

	function handleStatusChange(e: Event) {
		const target = e.target as HTMLSelectElement;
		onstatuschange(investigation.id, target.value);
	}
</script>

{#if activeTab === 'details'}
	<div class="details-content">
		<DrawerSection title="Investigation" defaultExpanded>
			<KVRow label="Title" value={investigation.title} />
			<KVRow label="Status" value={investigation.status} />
			{#if investigation.severity}
				<KVRow label="Severity" value={investigation.severity} />
			{/if}
			<KVRow label="Created" value={formatTimestamp(investigation.created_at)} />
			<KVRow label="Updated" value={formatTimestamp(investigation.updated_at)} />
		</DrawerSection>

		{#if investigation.description}
			<DrawerSection title="Description" defaultExpanded>
				<p class="description-text">{investigation.description}</p>
			</DrawerSection>
		{/if}

		{#if investigation.tags?.length > 0}
			<DrawerSection title="Tags" defaultExpanded={false}>
				<div class="tag-pills">
					{#each investigation.tags as tag}
						<span class="badge badge-muted">{tag}</span>
					{/each}
				</div>
			</DrawerSection>
		{/if}

		<!-- Status change -->
		<DrawerSection title="Change Status" defaultExpanded={false}>
			<select class="status-select" value={investigation.status} onchange={handleStatusChange}>
				<option value="open">Open</option>
				<option value="in_progress">In Progress</option>
				<option value="closed">Closed</option>
			</select>
		</DrawerSection>
	</div>

{:else if activeTab === 'notes'}
	<div class="notes-content">
		{#if investigation.notes?.length > 0}
			<div class="notes-list">
				{#each investigation.notes as note}
					<div class="note-item">
						<div class="note-meta">{timeAgo(note.created_at)}</div>
						<p class="note-text">{note.content}</p>
					</div>
				{/each}
			</div>
		{:else}
			<div class="empty-state">
				<p class="text-muted">No notes yet</p>
			</div>
		{/if}

		<!-- Add note -->
		<div class="add-note">
			<textarea
				class="note-input"
				placeholder="Add a note..."
				bind:value={noteText}
				rows="3"
			></textarea>
			<button
				class="btn btn-primary btn-sm"
				onclick={handleAddNote}
				disabled={!noteText.trim() || noteSaving}
			>
				{noteSaving ? 'Saving...' : 'Add Note'}
			</button>
		</div>
	</div>

{:else if activeTab === 'linked'}
	<div class="linked-content">
		{#if investigation.alert_ids?.length > 0}
			<DrawerSection title="Linked Alerts ({investigation.alert_ids.length})" defaultExpanded>
				<div class="linked-list">
					{#each investigation.alert_ids as alertId}
						<a href="/alerts?id={alertId}" class="linked-item mono">{alertId}</a>
					{/each}
				</div>
			</DrawerSection>
		{/if}

		{#if investigation.device_ips?.length > 0}
			<DrawerSection title="Linked Devices ({investigation.device_ips.length})" defaultExpanded>
				<div class="linked-list">
					{#each investigation.device_ips as ip}
						<a href="/devices/{ip}" class="linked-item mono">{ip}</a>
					{/each}
				</div>
			</DrawerSection>
		{/if}

		{#if !investigation.alert_ids?.length && !investigation.device_ips?.length}
			<div class="empty-state">
				<p class="text-muted">No linked items</p>
			</div>
		{/if}
	</div>
{/if}

<style>
	.details-content, .notes-content, .linked-content {
		display: flex;
		flex-direction: column;
	}

	.description-text {
		font-size: var(--text-sm);
		color: var(--text-primary);
		line-height: 1.6;
	}

	.tag-pills {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
	}

	.status-select {
		width: 100%;
		padding: var(--space-sm);
		font-size: var(--text-sm);
		font-family: var(--font-sans);
		color: var(--text-primary);
		background-color: var(--bg-input);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		cursor: pointer;
	}

	.notes-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		margin-bottom: var(--space-md);
	}

	.note-item {
		padding: var(--space-sm) var(--space-md);
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-md);
	}

	.note-meta {
		font-size: var(--text-xs);
		color: var(--text-muted);
		margin-bottom: var(--space-xs);
	}

	.note-text {
		font-size: var(--text-sm);
		color: var(--text-primary);
		line-height: 1.5;
	}

	.add-note {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		margin-top: var(--space-md);
		padding-top: var(--space-md);
		border-top: 1px solid var(--border-dim);
	}

	.note-input {
		width: 100%;
		padding: var(--space-sm);
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		color: var(--text-primary);
		background-color: var(--bg-input);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		resize: vertical;
	}

	.note-input::placeholder {
		color: var(--text-muted);
	}

	.linked-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.linked-item {
		display: block;
		padding: var(--space-xs) var(--space-sm);
		font-size: var(--text-sm);
		color: var(--accent);
		text-decoration: none;
		border-radius: var(--radius-sm);
		transition: background-color var(--transition-fast);
	}

	.linked-item:hover {
		background-color: var(--accent-muted);
		text-decoration: none;
	}

	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: var(--space-xl) 0;
	}

	.mono { font-family: var(--font-mono); }
	.text-muted { color: var(--text-muted); font-size: var(--text-sm); }
</style>
