<script lang="ts">
	/**
	 * Changelog — Network event audit log timeline.
	 *
	 * Chronological feed of network events with type filtering,
	 * date range selection, and CSV/JSON export.
	 */

	import { getChangelogEvents, getEventTypes, type ChangelogEvent } from '$lib/api/changelog';

	// State
	let events = $state<ChangelogEvent[]>([]);
	let eventTypes = $state<string[]>([]);
	let loading = $state(true);
	let selectedType = $state('');
	let limitCount = $state(100);

	// Event type display config
	const eventIcons: Record<string, string> = {
		device_joined: 'device-join',
		device_left: 'device-leave',
		alert_triggered: 'alert',
		config_changed: 'config',
		rule_updated: 'rule',
		capture_started: 'capture-start',
		capture_stopped: 'capture-stop',
		storage_pruned: 'storage',
	};

	const eventLabels: Record<string, string> = {
		device_joined: 'Device Joined',
		device_left: 'Device Left',
		alert_triggered: 'Alert Triggered',
		config_changed: 'Config Changed',
		rule_updated: 'Rule Updated',
		capture_started: 'Capture Started',
		capture_stopped: 'Capture Stopped',
		storage_pruned: 'Storage Pruned',
	};

	// Load data on mount
	$effect(() => {
		loadData();
	});

	async function loadData() {
		loading = true;
		const [eventsRes, typesRes] = await Promise.all([
			getChangelogEvents({
				type: selectedType || undefined,
				limit: limitCount,
			}),
			getEventTypes(),
		]);
		events = eventsRes.events;
		eventTypes = typesRes;
		loading = false;
	}

	async function handleFilter() {
		loading = true;
		const result = await getChangelogEvents({
			type: selectedType || undefined,
			limit: limitCount,
		});
		events = result.events;
		loading = false;
	}

	function exportAsJson() {
		const blob = new Blob([JSON.stringify(events, null, 2)], { type: 'application/json' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `nettap-changelog-${new Date().toISOString().slice(0, 10)}.json`;
		a.click();
		URL.revokeObjectURL(url);
	}

	function exportAsCsv() {
		const headers = ['Timestamp', 'Event Type', 'Title', 'Description'];
		const rows = events.map(e => [
			e['@timestamp'],
			e.event_type,
			e.title,
			e.description,
		].map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(','));

		const csv = [headers.join(','), ...rows].join('\n');
		const blob = new Blob([csv], { type: 'text/csv' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `nettap-changelog-${new Date().toISOString().slice(0, 10)}.csv`;
		a.click();
		URL.revokeObjectURL(url);
	}

	function formatTime(ts: string): string {
		try {
			return new Date(ts).toLocaleString();
		} catch {
			return ts;
		}
	}

	function eventColor(type: string): string {
		const colors: Record<string, string> = {
			device_joined: 'var(--status-success)',
			device_left: 'var(--status-warning)',
			alert_triggered: 'var(--status-critical)',
			config_changed: 'var(--accent)',
			rule_updated: 'var(--accent)',
			capture_started: 'var(--status-success)',
			capture_stopped: 'var(--status-warning)',
			storage_pruned: 'var(--text-muted)',
		};
		return colors[type] ?? 'var(--text-muted)';
	}
</script>

<svelte:head>
	<title>Changelog | NetTap</title>
</svelte:head>

<div class="changelog-page">
	<div class="page-header">
		<h2>Network Changelog</h2>
		<p class="text-muted">Chronological timeline of network events and system changes.</p>
	</div>

	<!-- Filters -->
	<div class="filters-row">
		<div class="filter-group">
			<label class="label" for="type-filter">Event Type</label>
			<select class="input" id="type-filter" bind:value={selectedType} onchange={handleFilter}>
				<option value="">All Events</option>
				{#each eventTypes as et}
					<option value={et}>{eventLabels[et] ?? et}</option>
				{/each}
			</select>
		</div>
		<div class="filter-group">
			<label class="label" for="limit-filter">Show</label>
			<select class="input" id="limit-filter" bind:value={limitCount} onchange={handleFilter}>
				<option value={25}>25 events</option>
				<option value={50}>50 events</option>
				<option value={100}>100 events</option>
				<option value={500}>500 events</option>
			</select>
		</div>
		<div class="export-buttons">
			<button class="btn btn-sm btn-secondary" onclick={exportAsJson} disabled={events.length === 0}>Export JSON</button>
			<button class="btn btn-sm btn-secondary" onclick={exportAsCsv} disabled={events.length === 0}>Export CSV</button>
		</div>
	</div>

	<!-- Timeline -->
	{#if loading}
		<div class="card">
			<p class="text-muted" style="padding: var(--space-lg);">Loading changelog events...</p>
		</div>
	{:else if events.length === 0}
		<div class="card">
			<p class="text-muted" style="padding: var(--space-lg);">No events found for the selected filters.</p>
		</div>
	{:else}
		<div class="timeline">
			{#each events as event}
				<div class="timeline-entry">
					<div class="timeline-dot" style="background-color: {eventColor(event.event_type)};"></div>
					<div class="timeline-content">
						<div class="timeline-header">
							<span class="event-badge" style="color: {eventColor(event.event_type)};">
								{eventLabels[event.event_type] ?? event.event_type}
							</span>
							<span class="event-time">{formatTime(event['@timestamp'])}</span>
						</div>
						<h4 class="event-title">{event.title}</h4>
						{#if event.description}
							<p class="event-description">{event.description}</p>
						{/if}
						{#if event.metadata && Object.keys(event.metadata).length > 0}
							<div class="event-metadata">
								{#each Object.entries(event.metadata) as [key, value]}
									<span class="meta-tag"><strong>{key}:</strong> {String(value)}</span>
								{/each}
							</div>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.changelog-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
		max-width: 900px;
	}

	.page-header h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		margin-bottom: var(--space-xs);
	}

	.filters-row {
		display: flex;
		align-items: flex-end;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	.filter-group {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.export-buttons {
		display: flex;
		gap: var(--space-xs);
		margin-left: auto;
	}

	/* Timeline */
	.timeline {
		display: flex;
		flex-direction: column;
		gap: 0;
		position: relative;
		padding-left: 24px;
	}

	.timeline::before {
		content: '';
		position: absolute;
		left: 7px;
		top: 0;
		bottom: 0;
		width: 2px;
		background: var(--border-default);
	}

	.timeline-entry {
		position: relative;
		padding: var(--space-sm) 0 var(--space-md) var(--space-md);
	}

	.timeline-dot {
		position: absolute;
		left: -21px;
		top: 14px;
		width: 12px;
		height: 12px;
		border-radius: 50%;
		border: 2px solid var(--bg-primary);
		z-index: 1;
	}

	.timeline-content {
		padding: var(--space-sm) var(--space-md);
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
	}

	.timeline-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: var(--space-xs);
	}

	.event-badge {
		font-size: var(--text-xs);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.event-time {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.event-title {
		font-size: var(--text-base);
		font-weight: 600;
		margin-bottom: var(--space-xs);
	}

	.event-description {
		font-size: var(--text-sm);
		color: var(--text-secondary);
		margin-bottom: var(--space-xs);
	}

	.event-metadata {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
	}

	.meta-tag {
		font-size: var(--text-xs);
		padding: 2px 6px;
		background: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		color: var(--text-secondary);
	}

	@media (max-width: 640px) {
		.filters-row {
			flex-direction: column;
			align-items: stretch;
		}

		.export-buttons {
			margin-left: 0;
		}
	}
</style>
