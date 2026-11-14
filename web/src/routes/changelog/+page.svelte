<script lang="ts">
	// OLD CODE START — NET-272: what each device did, with drill-down
	// /**
	//  * Changelog — Network event audit log timeline.
	//  *
	//  * Chronological feed of network events with type filtering,
	//  * date range selection, and CSV/JSON export.
	//  */
	// OLD CODE END
	/**
	 * Changelog: what changed on the network, and what each new device did (NET-272).
	 *
	 * The events over the loaded range (`?range`), each joined in the browser to the device list
	 * over the same window (changelog-rows.ts). A chart pick (`?pickFrom`/`?pickTo`) only narrows
	 * the loaded rows: it never refetches or changes a figure. A row opens its details below the table.
	 */

	// OLD CODE: import { onDestroy, onMount } from 'svelte'; (NET-272: focus moves after the panel renders)
	import { onDestroy, onMount, tick } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	// OLD CODE: import { getChangelogEvents, getEventTypes, type ChangelogEvent } from '$lib/api/changelog'; (NET-272: rows replace the raw events)
	import { getChangelogEvents, getEventTypes } from '$lib/api/changelog';
	import { getDevices } from '$lib/api/devices';
	import { formatBytes } from '$lib/api/logs';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import AreaChart from '$lib/components/ui/charts/AreaChart.svelte';
	// OLD CODE: import type { IconName } from '$lib/components/ui/icons'; (NET-272: the icons moved to changelog-rows.ts)
	// OLD CODE: import { formatTime } from '$lib/utils/time'; (NET-272: the table and the panel format their own times)
	import { chartTime, DRILL_RANGES, fmt, rangeWindow, startRange, windowWords, type DrillRange, type DrillRangeValue, type DrillWindow } from '$lib/utils/drilldown';
	import {
		changelogKpis, DEVICE_LIMIT, EVENT_LIMIT, eventBuckets, eventLabels, inPick, joinChangelog, keepPick, knownFrom, pickRange, readPick, toCsv, toJson,
		type ChangelogRow, type Coverage,
	} from './changelog-rows';
	import ChangelogTable from './ChangelogTable.svelte';
	import ChangelogDetail from './ChangelogDetail.svelte';

	// State
	// OLD CODE: let events = $state<ChangelogEvent[]>([]); (NET-272: `view` holds the joined rows with their window)
	let eventTypes = $state<string[]>([]);
	let loading = $state(true);
	let selectedType = $state('');
	// OLD CODE: let limitCount = $state(100); (NET-272: the loaded range takes the daemon's cap, and the page says when it is reached)

	// NET-272: eventIcons and eventLabels (with their OLD CODE history) moved to changelog-rows.ts

	const RANGE_OPTIONS = DRILL_RANGES.map(({ value, label }) => ({ value, label }));
	const rangeOf = (v: string | null): DrillRange | undefined => DRILL_RANGES.find((r) => r.value === v);
	const DEFAULT_SPAN = rangeOf('7d')!;

	/** One load's answer, whole: the chart's buckets and a pick come from the same window as the rows. */
	interface View {
		win: DrillWindow;
		span: DrillRange;
		rows: ChangelogRow[];
		coverage: Coverage;
		/** Where the events are complete from, ms (changelog-rows knownFrom). */
		known: number;
	}

	let range = $state<DrillRangeValue>(startRange('7d'));
	let view = $state.raw<View | null>(null);
	/** The chart's pick: narrows the loaded rows only. */
	let pick = $state<DrillWindow | null>(null);
	let pickRefused = $state(false);
	let selectedId = $state<string | null>(null);
	let detail = $state<ReturnType<typeof ChangelogDetail>>();
	let eventsBody = $state<HTMLElement>();

	const span = $derived(view?.span ?? rangeOf(range) ?? DEFAULT_SPAN);
	const rangeText = $derived(span.words.charAt(0).toUpperCase() + span.words.slice(1));
	const rows = $derived(view?.rows ?? []);
	const shown = $derived(inPick(rows, pick));
	const kpis = $derived(changelogKpis(rows));
	const buckets = $derived(view ? eventBuckets(view.rows, view.win, view.span.bucketMs, view.known) : []);
	const busiest = $derived(buckets.reduce((top, b, i) => (Number.isFinite(b.count) && b.count > 0 && (top < 0 || b.count > buckets[top].count) ? i : top), -1));
	const selectedRow = $derived(rows.find((r) => r.id === selectedId) ?? null);
	const truncated = $derived(!!view?.coverage.eventsTruncated);
	const devicesFailed = $derived(!!view?.coverage.devicesFailed);

	// OLD CODE START — the page refresh contract (PLAN §5.5) runs the first load
	// // Load data on mount
	// $effect(() => {
	// 	loadData();
	// });
	// OLD CODE END
	const refresh = registerPageRefresh(loadData);
	// OLD CODE START — NET-272: range, type and the pick come from the URL first
	// onMount(() => {
	// 	refresh.run();
	// });
	// OLD CODE END
	onMount(() => {
		const q = $page.url.searchParams;
		range = rangeOf(q.get('range'))?.value ?? range;
		selectedType = q.get('type') ?? '';
		pick = readPick(q.get('pickFrom'), q.get('pickTo'));
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
	// OLD CODE START — NET-272: the events alone, newest `limitCount`, over the daemon's default 7 days
	// /** Events for the current filter plus the type list; a failure clears the events (they'd belong to another filter). */
	// async function loadData(guard: LoadGuard): Promise<LoadResult> {
	// 	const g = guard.begin();
	// 	const type = selectedType || undefined;
	// 	const limit = limitCount;
	// 	loading = true;
	// 	const [eventsRes, typesRes] = await Promise.allSettled([getChangelogEvents({ type, limit }), getEventTypes()]);
	// 	if (!guard.current(g)) return 'skipped';
	// 	events = eventsRes.status === 'fulfilled' ? eventsRes.value.events : [];
	// 	eventsFailed = eventsRes.status === 'rejected';
	// 	// getEventTypes answers [] on failure, as before
	// 	if (typesRes.status === 'fulfilled') eventTypes = typesRes.value;
	// 	loading = false;
	// 	return eventsFailed ? 'failed' : 'ok';
	// }
	// OLD CODE END
	/**
	 * The events over the range's window joined to the device list over the same window, plus the type
	 * list. A failed event request clears the rows (they'd belong to another filter); a failed device
	 * list keeps them, without figures ('partial').
	 */
	async function loadData(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const s = rangeOf(range) ?? DEFAULT_SPAN;
		const win = rangeWindow(s.hours);
		const type = selectedType || undefined;
		loading = true;
		const [eventsRes, devicesRes, typesRes] = await Promise.allSettled([
			getChangelogEvents({ ...win, type, limit: EVENT_LIMIT }),
			getDevices({ ...win, limit: DEVICE_LIMIT }),
			getEventTypes(),
		]);
		if (!guard.current(g)) return 'skipped';
		// getEventTypes answers [] on failure, as before
		if (typesRes.status === 'fulfilled') eventTypes = typesRes.value;
		eventsFailed = eventsRes.status === 'rejected';
		loading = false;
		if (eventsRes.status === 'rejected') {
			view = null;
			return 'failed';
		}
		const joined = joinChangelog(eventsRes.value.events, devicesRes.status === 'fulfilled' ? devicesRes.value : null);
		const known = knownFrom(joined.rows, win, s.bucketMs, joined.coverage.eventsTruncated);
		view = { win, span: s, ...joined, known };
		// review M1: a refusal belonged to the old range's chart
		pickRefused = false;
		// review L3: a row that left the loaded set closes its panel, so it can't reopen by itself later
		if (selectedId && !joined.rows.some((r) => r.id === selectedId)) selectedId = null;
		// relative ranges move on reload: a pick no longer inside the window (or its known part) goes
		const kept = keepPick(pick, win, known);
		if (pick && !kept) {
			pick = null;
			void writeUrl();
		}
		return devicesRes.status === 'fulfilled' ? 'ok' : 'partial';
	}

	/** The range, type and pick in the URL, so a reload or a shared link opens the same view. */
	function writeUrl() {
		const q = new URLSearchParams({ range });
		if (selectedType) q.set('type', selectedType);
		if (pick) {
			q.set('pickFrom', pick.from);
			q.set('pickTo', pick.to);
		}
		return goto(`${$page.url.pathname}?${q.toString()}`, { replaceState: true, keepFocus: true, noScroll: true });
	}

	function handleFilter() {
		// OLD CODE: refresh.run(); (NET-272: the type lives in the URL)
		void writeUrl();
		refresh.run();
	}

	/** A chart pick narrows the table to those buckets; one touching uncounted buckets is refused. */
	function pickBuckets(i: number, j: number) {
		if (!view) return;
		const next = pickRange(buckets, i, j, view.span.bucketMs, view.win);
		pickRefused = next === null;
		if (!next) return;
		pick = next;
		void writeUrl();
	}

	function clearPick() {
		pick = null;
		pickRefused = false;
		void writeUrl();
	}

	async function openRow(row: ChangelogRow) {
		selectedId = row.id;
		await tick();
		detail?.focus();
	}

	/** Focus goes back to the row that opened the panel, or to the events heading when a pick hid it. */
	async function closeDetail() {
		const button = eventsBody?.querySelector<HTMLButtonElement>('button.row-btn[aria-current="true"]');
		selectedId = null;
		await tick();
		if (button?.isConnected) {
			button.focus();
			return;
		}
		const heading = eventsBody?.closest('.card')?.querySelector<HTMLElement>('.card-title');
		if (!heading) return;
		heading.tabIndex = -1;
		heading.focus();
	}

	// OLD CODE START — NET-272: the raw events only, under one name; the export carries the joined columns now
	// function exportAsJson() {
	// 	const blob = new Blob([JSON.stringify(events, null, 2)], { type: 'application/json' });
	// 	const url = URL.createObjectURL(blob);
	// 	const a = document.createElement('a');
	// 	a.href = url;
	// 	a.download = `nettap-changelog-${new Date().toISOString().slice(0, 10)}.json`;
	// 	a.click();
	// 	URL.revokeObjectURL(url);
	// }
	//
	// function exportAsCsv() {
	// 	const headers = ['Timestamp', 'Event Type', 'Title', 'Description'];
	// 	const rows = events.map(e => [
	// 		e['@timestamp'],
	// 		e.event_type,
	// 		e.title,
	// 		e.description,
	// 	].map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(','));
	//
	// 	const csv = [headers.join(','), ...rows].join('\n');
	// 	const blob = new Blob([csv], { type: 'text/csv' });
	// 	const url = URL.createObjectURL(blob);
	// 	const a = document.createElement('a');
	// 	a.href = url;
	// 	a.download = `nettap-changelog-${new Date().toISOString().slice(0, 10)}.csv`;
	// 	a.click();
	// 	URL.revokeObjectURL(url);
	// }
	// OLD CODE END
	/** Saves the rows on screen; a capped list says so in its name. */
	function download(ext: 'json' | 'csv', type: string, body: string) {
		const url = URL.createObjectURL(new Blob([body], { type }));
		const a = document.createElement('a');
		a.href = url;
		a.download = `nettap-changelog-${new Date().toISOString().slice(0, 10)}${truncated ? `-newest-${EVENT_LIMIT}` : ''}.${ext}`;
		a.click();
		URL.revokeObjectURL(url);
	}
	const exportAsJson = () => download('json', 'application/json', toJson(shown));
	const exportAsCsv = () => download('csv', 'text/csv', toCsv(shown));

	const countOf = (n: number, one: string, many: string) => `${fmt(n)} ${n === 1 ? one : many}`;
	const eventsNote = $derived(truncated ? `In the newest ${fmt(EVENT_LIMIT)}` : rangeText);
	const matchedNote = $derived(view && !devicesFailed ? `${fmt(kpis.matched)} of ${fmt(kpis.newDevices)} matched` : devicesFailed ? 'Device list failed' : undefined);
	const chartTip = (i: number) => {
		const b = buckets[i];
		if (!b) return '';
		return `${chartTime(b.timestamp, span.hours)} · ${Number.isFinite(b.count) ? countOf(b.count, 'event', 'events') : 'not counted'}`;
	};
	const chartLabel = $derived(
		busiest >= 0
			? `Most events at ${chartTime(buckets[busiest].timestamp, span.hours)}, with ${fmt(buckets[busiest].count)}`
			: `No events counted in the ${span.words}`,
	);
	const eventsSub = $derived(
		view
			? `${countOf(shown.length, 'event', 'events')} · ${pick ? windowWords(pick.from, pick.to) : span.words}${truncated ? ` · the newest ${fmt(EVENT_LIMIT)}` : ''}`
			: `Newest first · ${span.words}`,
	);

	// OLD CODE START — the browser's locale printed "11/6/2026, 10:37:23 PM" (NET-192 PR 4: formatTime in utils/time)
	// function formatTime(ts: string): string {
	// 	try {
	// 		return new Date(ts).toLocaleString();
	// 	} catch {
	// 		return ts;
	// 	}
	// }
	// OLD CODE END

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
		<!-- OLD CODE: <p class="page-sub">Network events and system changes, newest first</p> (NET-272) -->
		<p class="page-sub">What changed on your network, and what each new device did · {span.words}</p>
	</div>
	<div class="head-actions">
		<Pills options={RANGE_OPTIONS} bind:value={range} onchange={handleFilter} ariaLabel="Time range" />
		<!-- OLD CODE: disabled={events.length === 0} on both (NET-272: the rows on screen) -->
		<button class="btn" type="button" onclick={exportAsJson} disabled={loading || shown.length === 0}><Icon name="download" />Export JSON</button>
		<button class="btn" type="button" onclick={exportAsCsv} disabled={loading || shown.length === 0}><Icon name="download" />Export CSV</button>
	</div>
</div>

<div class="grid">
	{#if devicesFailed}
		<p class="notice is-warn c-12" role="status"><Icon name="warn" /><span>Traffic figures unavailable: the device list failed.</span></p>
	{/if}
	{#if truncated}
		<p class="notice is-warn c-12" role="status">
			<Icon name="warn" /><span>Showing the newest {fmt(EVENT_LIMIT)} events: the oldest part of this range isn't counted. Pick a shorter range.</span>
		</p>
	{/if}
	{#if view?.coverage.devicesTruncated}
		<p class="notice c-12" role="status"><Icon name="empty" /><span>Only the {fmt(DEVICE_LIMIT)} busiest addresses have figures.</span></p>
	{/if}
	{#each view?.coverage.ipv6Notes ?? [] as note (note)}
		<p class="notice c-12" role="status"><Icon name="warn" /><span>{note}</span></p>
	{/each}

	<KpiCard class="c-3" label="Events" icon="changelog" value={view ? fmt(kpis.events) : '—'} note={eventsNote} />
	<KpiCard class="c-3" label="New devices" icon="devices" value={view ? fmt(kpis.newDevices) : '—'} note={eventsNote} />
	<KpiCard class="c-3" label="Data moved by new devices" icon="bandwidth" value={kpis.moved !== null ? formatBytes(kpis.moved) : '—'} note={matchedNote} />
	<KpiCard
		class="c-3"
		label="Busiest new device"
		icon="up"
		value={kpis.busiest ? formatBytes(kpis.busiest.total ?? 0) : '—'}
		note={matchedNote}
		sub={kpis.busiest?.name ?? undefined}
	/>

	<Card title="Events over time" sub="Events per {span.bucketWords} · {span.words}" hero class="c-12">
		{#if loading}
			<CardState state="loading" title="Loading events over time" />
		{:else if eventsFailed}
			<CardState state="error" title="Couldn't load changelog events: the request failed." message="Check that NetTap is running on the System page, then try again." onaction={handleFilter} />
		{:else if rows.length === 0}
			<CardState state="empty" icon="changelog" title="No events in this range." message="Pick a longer range to see older events." />
		{:else}
			<AreaChart
				series={[{ key: 'events', label: 'Events', colour: 1, points: buckets.map((b) => ({ t: b.timestamp, v: b.count })) }]}
				gaps
				formatX={(t) => chartTime(t, span.hours)}
				formatY={(v) => (Number.isInteger(v) ? fmt(v) : '')}
				formatTip={chartTip}
				highlightIndex={busiest >= 0 ? busiest : undefined}
				ariaLabel={chartLabel}
				height={200}
				onpick={pickBuckets}
			/>
			<p class="card-sub pick-hint">Click a point or drag across the chart to list the events then.</p>
			{#if pickRefused}
				<p class="notice is-warn pick-note" role="status"><Icon name="warn" /><span>That part of the range isn't counted: pick a shorter range to see it.</span></p>
			{/if}
		{/if}
	</Card>

	<!-- OLD CODE: <Card title="Events" sub="Newest first · up to {limitCount} events" class="c-12"> (NET-272) -->
	<Card title="Events" sub={eventsSub} class="c-12">
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
			<!-- OLD CODE START — NET-272: the loaded range takes the daemon's cap of 1,000, and the page says when it is reached
			<div class="field">
				<label class="label" for="limit-filter">Show</label>
				<select class="select" id="limit-filter" bind:value={limitCount} onchange={handleFilter}>
					<option value={25}>25 events</option>
					<option value={50}>50 events</option>
					<option value={100}>100 events</option>
					<option value={500}>500 events</option>
				</select>
			</div>
			OLD CODE END -->
			{#if pick}
				<span class="chip">
					Showing {windowWords(pick.from, pick.to)}
					<button class="chip-x" type="button" onclick={clearPick} aria-label="Show the whole range"><Icon name="close" /></button>
				</span>
			{/if}
		</div>

		<div bind:this={eventsBody}>
			{#if loading}
				<CardState state="loading" title="Loading changelog events" />
			{:else if eventsFailed}
				<CardState
					state="error"
					title="Couldn't load changelog events: the request failed."
					message="Check that NetTap is running on the System page, then try again."
					onaction={handleFilter}
				/>
			{:else if rows.length === 0}
				<CardState
					state="empty"
					icon="changelog"
					title="No events found for the selected filters."
					message="Events appear here when a new device joins the network, a manual storage cleanup runs, or more LAN addresses send traffic than NetTap lists."
				/>
				<!-- OLD CODE: message="Events appear here when a new device joins the network or a manual storage cleanup runs." (NET-182: the device limit is recorded too) -->
				<!-- OLD CODE START — NET-158: promised event types nothing records (devices leaving, alerts, settings) -->
				<!-- message="Events appear here as devices join or leave, alerts fire and settings change." -->
				<!-- OLD CODE END -->
			{:else if shown.length === 0}
				<CardState state="empty" icon="changelog" title="No events then." message="Pick another part of the chart, or show the whole range." />
			{:else}
				<!-- OLD CODE START — NET-272: a list of event cards; the table adds what each device did
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
				OLD CODE END -->
				<ChangelogTable rows={shown} {selectedId} onactivate={openRow} />
			{/if}
		</div>
	</Card>

	{#if view && selectedRow}
		<ChangelogDetail bind:this={detail} row={selectedRow} win={view.win} range={view.span.value} onclose={closeDetail} />
	{/if}
</div>

<style>
	/* Layout glue the system lacks: the filter field's width, the pick chip's clear button, the chart's notes */
	.toolbar .field { width: 14rem; }
	.chip-x { all: unset; display: inline-grid; place-items: center; cursor: pointer; color: var(--text-2); border-radius: var(--r-pill); }
	.chip-x:hover { color: var(--text-1); }
	.chip-x:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
	.pick-hint, .pick-note { margin-top: var(--sp-2); }
	/* OLD CODE START — NET-272: the event cards' rules; the table replaced them
	.events { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
	.event { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: var(--sp-3); padding: var(--sp-3) 0; }
	.event + .event { border-top: 1px solid var(--line); }
	.event-main { display: flex; flex-direction: column; gap: var(--sp-1); min-width: 0; }
	.event-top { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); flex-wrap: wrap; font-size: var(--text-xs); }
	.event-title { font: 500 var(--text-base)/1.3 var(--font-display); overflow-wrap: anywhere; }
	.event-desc { color: var(--text-2); font-size: var(--text-sm); overflow-wrap: anywhere; }
	.event .chips { margin-top: var(--sp-1); }
	OLD CODE END */
</style>
