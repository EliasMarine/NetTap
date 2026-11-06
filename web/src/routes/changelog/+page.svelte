<script lang="ts">
	/**
	 * Changelog — Network event audit log timeline.
	 *
	 * Chronological feed of network events with type filtering,
	 * date range selection, and CSV/JSON export.
	 */

	import { onDestroy, onMount } from 'svelte';
	import { getChangelogEvents, getEventTypes, type ChangelogEvent } from '$lib/api/changelog';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import type { IconName } from '$lib/components/ui/icons';

	// State
	let events = $state<ChangelogEvent[]>([]);
	let eventTypes = $state<string[]>([]);
	let loading = $state(true);
	let selectedType = $state('');
	let limitCount = $state(100);

	// Event type display config
	// OLD CODE START — never rendered; each type now has a system icon
	// const eventIcons: Record<string, string> = {
	// 	device_joined: 'device-join',
	// 	device_left: 'device-leave',
	// 	alert_triggered: 'alert',
	// 	config_changed: 'config',
	// 	rule_updated: 'rule',
	// 	capture_started: 'capture-start',
	// 	capture_stopped: 'capture-stop',
	// 	storage_pruned: 'storage',
	// };
	// OLD CODE END
	const eventIcons: Record<string, IconName> = {
		device_joined: 'devices',
		device_left: 'devices',
		alert_triggered: 'alerts',
		config_changed: 'settings',
		rule_updated: 'filter',
		capture_started: 'play',
		capture_stopped: 'pause',
		storage_pruned: 'system',
	};

	// OLD CODE START — sentence case (design system voice)
	// const eventLabels: Record<string, string> = {
	// 	device_joined: 'Device Joined',
	// 	device_left: 'Device Left',
	// 	alert_triggered: 'Alert Triggered',
	// 	config_changed: 'Config Changed',
	// 	rule_updated: 'Rule Updated',
	// 	capture_started: 'Capture Started',
	// 	capture_stopped: 'Capture Stopped',
	// 	storage_pruned: 'Storage Pruned',
	// };
	// OLD CODE END
	const eventLabels: Record<string, string> = {
		device_joined: 'Device joined',
		device_left: 'Device left',
		alert_triggered: 'Alert triggered',
		config_changed: 'Config changed',
		rule_updated: 'Rule updated',
		capture_started: 'Capture started',
		capture_stopped: 'Capture stopped',
		storage_pruned: 'Storage pruned',
	};

	// OLD CODE START — the page refresh contract (PLAN §5.5) runs the first load
	// // Load data on mount
	// $effect(() => {
	// 	loadData();
	// });
	// OLD CODE END
	const refresh = registerPageRefresh(loadData);
	onMount(() => {
		refresh.run();
	});
	onDestroy(refresh.unregister);

	// #96: the event request failed, so an empty list is not "no events"
	let eventsFailed = $state(false);

	// OLD CODE START — folded into loadData, which now guards against an older, slower load
	// // Events for the current filter; a failure clears them (they'd belong to another filter)
	// async function fetchEvents() {
	// 	try {
	// 		events = (await getChangelogEvents({ type: selectedType || undefined, limit: limitCount })).events;
	// 		eventsFailed = false;
	// 	} catch {
	// 		events = [];
	// 		eventsFailed = true;
	// 	}
	// }
	// OLD CODE END

	// OLD CODE START — #96: getChangelogEvents now throws on failure
	// async function loadData() {
	// 	loading = true;
	// 	const [eventsRes, typesRes] = await Promise.all([
	// 		getChangelogEvents({
	// 			type: selectedType || undefined,
	// 			limit: limitCount,
	// 		}),
	// 		getEventTypes(),
	// 	]);
	// 	events = eventsRes.events;
	// 	eventTypes = typesRes;
	// 	loading = false;
	// }
	//
	// async function handleFilter() {
	// 	loading = true;
	// 	const result = await getChangelogEvents({
	// 		type: selectedType || undefined,
	// 		limit: limitCount,
	// 	});
	// 	events = result.events;
	// 	loading = false;
	// }
	// OLD CODE END
	// OLD CODE START — PLAN §5.5: a filter change during a load let the older response win
	// async function loadData() {
	// 	loading = true;
	// 	const [, typesRes] = await Promise.all([fetchEvents(), getEventTypes()]);
	// 	eventTypes = typesRes;
	// 	loading = false;
	// }
	//
	// async function handleFilter() {
	// 	loading = true;
	// 	await fetchEvents();
	// 	loading = false;
	// }
	// OLD CODE END
	/** Events for the current filter plus the type list; a failure clears the events (they'd belong to another filter). */
	async function loadData(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const type = selectedType || undefined;
		const limit = limitCount;
		loading = true;
		const [eventsRes, typesRes] = await Promise.allSettled([getChangelogEvents({ type, limit }), getEventTypes()]);
		if (!guard.current(g)) return 'skipped';
		events = eventsRes.status === 'fulfilled' ? eventsRes.value.events : [];
		eventsFailed = eventsRes.status === 'rejected';
		// getEventTypes answers [] on failure, as before
		if (typesRes.status === 'fulfilled') eventTypes = typesRes.value;
		loading = false;
		return eventsFailed ? 'failed' : 'ok';
	}

	function handleFilter() {
		refresh.run();
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

	// OLD CODE START — legacy status colours; the type now reads from its icon and label
	// function eventColor(type: string): string {
	// 	const colors: Record<string, string> = {
	// 		device_joined: 'var(--status-success)',
	// 		device_left: 'var(--status-warning)',
	// 		alert_triggered: 'var(--status-critical)',
	// 		config_changed: 'var(--accent)',
	// 		rule_updated: 'var(--accent)',
	// 		capture_started: 'var(--status-success)',
	// 		capture_stopped: 'var(--status-warning)',
	// 		storage_pruned: 'var(--text-muted)',
	// 	};
	// 	return colors[type] ?? 'var(--text-muted)';
	// }
	// OLD CODE END
</script>

<svelte:head>
	<title>Changelog | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">Changelog</h1>
		<p class="page-sub">Network events and system changes, newest first</p>
	</div>
	<div class="head-actions">
		<button class="btn" type="button" onclick={exportAsJson} disabled={events.length === 0}><Icon name="download" />Export JSON</button>
		<button class="btn" type="button" onclick={exportAsCsv} disabled={events.length === 0}><Icon name="download" />Export CSV</button>
	</div>
</div>

<div class="grid">
	<Card title="Events" sub="Newest first · up to {limitCount} events" class="c-12">
		<div class="toolbar">
			<div class="field">
				<label class="label" for="type-filter">Event type</label>
				<select class="select" id="type-filter" bind:value={selectedType} onchange={handleFilter}>
					<option value="">All events</option>
					{#each eventTypes as et (et)}
						<option value={et}>{eventLabels[et] ?? et}</option>
					{/each}
				</select>
			</div>
			<div class="field">
				<label class="label" for="limit-filter">Show</label>
				<select class="select" id="limit-filter" bind:value={limitCount} onchange={handleFilter}>
					<option value={25}>25 events</option>
					<option value={50}>50 events</option>
					<option value={100}>100 events</option>
					<option value={500}>500 events</option>
				</select>
			</div>
		</div>

		{#if loading}
			<CardState state="loading" title="Loading changelog events" />
		{:else if eventsFailed}
			<CardState
				state="error"
				title="Couldn't load changelog events: the request failed."
				message="Check that NetTap is running on the System page, then try again."
				onaction={handleFilter}
			/>
		{:else if events.length === 0}
			<CardState
				state="empty"
				icon="changelog"
				title="No events found for the selected filters."
				message="Events appear here when a new device joins the network or a manual storage cleanup runs."
			/>
			<!-- OLD CODE START — NET-158: promised event types nothing records (devices leaving, alerts, settings) -->
			<!-- message="Events appear here as devices join or leave, alerts fire and settings change." -->
			<!-- OLD CODE END -->
		{:else}
			<ol class="events">
				{#each events as event}
					<li class="event">
						<span class="tile"><Icon name={eventIcons[event.event_type] ?? 'changelog'} /></span>
						<div class="event-main">
							<div class="event-top">
								<span class="tag">{eventLabels[event.event_type] ?? event.event_type}</span>
								<time class="dim num" datetime={event['@timestamp']}>{formatTime(event['@timestamp'])}</time>
							</div>
							<h3 class="event-title">{event.title}</h3>
							{#if event.description}
								<p class="event-desc">{event.description}</p>
							{/if}
							{#if event.metadata && Object.keys(event.metadata).length > 0}
								<div class="chips">
									{#each Object.entries(event.metadata) as [key, value] (key)}
										<span class="chip">{key}: <span class="mono">{String(value)}</span></span>
									{/each}
								</div>
							{/if}
						</div>
					</li>
				{/each}
			</ol>
		{/if}
	</Card>
</div>

<style>
	/* Layout glue the system lacks: the filter fields' width and the event rows */
	.toolbar .field { width: 14rem; }
	.events { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
	.event { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: var(--sp-3); padding: var(--sp-3) 0; }
	.event + .event { border-top: 1px solid var(--line); }
	.event-main { display: flex; flex-direction: column; gap: var(--sp-1); min-width: 0; }
	.event-top { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); flex-wrap: wrap; font-size: var(--text-xs); }
	.event-title { font: 500 var(--text-base)/1.3 var(--font-display); overflow-wrap: anywhere; }
	.event-desc { color: var(--text-2); font-size: var(--text-sm); overflow-wrap: anywhere; }
	.event .chips { margin-top: var(--sp-1); }
</style>
