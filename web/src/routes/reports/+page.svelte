<script lang="ts">
	/**
	 * Reports (NET-340): the weekly report the Settings card schedules. The KPIs are the card
	 * schedule's (next send, last delivery) and the shown report's coverage; the hero is one report's
	 * five sections, each with its own coverage line; the history lists that schedule's reports, and
	 * a row shows its report. Generate now makes a report for the latest full period without emailing it.
	 */
	import { onDestroy, onMount, tick } from 'svelte';
	import { daemonReason, generateReport, getReport, getReportHistory, getReportSchedules, ReportsError, type Report, type ReportSchedule, type ReportSummary } from '$lib/api/reports';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import { loadFailed } from '$lib/utils/load-failed';
	import ReportSections from './ReportSections.svelte';
	import { TRIGGER_WORDS, daysCoveredKpi, deliveryKpis, deliveryWords, nextReportKpi, periodWords, zonedTime } from './report-words';

	const SETTINGS_HREF = '/settings?tab=notifications';
	const RUNNING_HINT = 'Check that NetTap is running on the System page, then try again.';

	/** One load's answer: the card's schedule (null when there is none) and its reports, newest first. */
	interface View {
		schedule: ReportSchedule | null;
		reports: ReportSummary[];
	}

	let view = $state.raw<View | null>(null);
	let loading = $state(true);
	/** The last load failed; with a view on screen, it is kept and the notice says how old it is. */
	let failed = $state(false);
	/** The daemon's sentence for that failure; null when NetTap couldn't be reached. */
	let failReason = $state<string | null>(null);
	let loadedAt = $state<number | null>(null);

	let selectedId = $state<string | null>(null);
	/** The last report loaded, whichever was picked; it is on screen only while it is the selected one. */
	let shown = $state.raw<Report | null>(null);
	// OLD CODE: let reportState = $state<'idle' | 'loading' | 'ready' | 'failed'>('idle'); (TypeScript review: a pick back to the shown report kept 'loading' for ever)
	/** The newest pick's failure, when its report isn't the one already loaded: the daemon's sentence, or '' for no reason. */
	let reportError = $state<string | null>(null);
	/** A refresh of the report on screen failed: it stays, under the stale notice. */
	let reportStale = $state(false);
	/** On screen: the loaded report when it is the selected one; loading or failed are derived from it, never stored. */
	const current = $derived(shown && shown.id === selectedId ? shown : null);

	let generating = $state(false);
	let generated = $state<{ text: string; tone: 'is-ok' | 'is-warn' | 'is-error' } | null>(null);

	const schedule = $derived(view?.schedule ?? null);
	const tz = $derived(schedule?.tz);
	const next = $derived(view ? nextReportKpi(schedule) : { value: '—' });
	const delivery = $derived(view ? deliveryKpis(schedule) : { last: { value: '—' }, delivery: { value: '—' } });
	// OLD CODE: const covered = $derived(daysCoveredKpi(shown)); (TypeScript review: only the report on screen)
	const covered = $derived(daysCoveredKpi(current));

	const refresh = registerPageRefresh(loadData);
	onMount(() => void refresh.run());
	onDestroy(refresh.unregister);

	/** Shows one report; the newest pick wins, and a failed refresh of the report on screen keeps it. */
	let reportSeq = 0;
	// OLD CODE START — TypeScript review: reportState was stored, so picking back the shown report (seq bumped,
	// state left 'loading') then failing its refetch left the spinner for ever; a report's failure set the page's `failed`
	// async function showReport(id: string): Promise<boolean> {
	// 	const summary = view?.reports.find((r) => r.id === id);
	// 	if (!summary) return false;
	// 	const seq = ++reportSeq;
	// 	if (shown?.id !== id) reportState = 'loading';
	// 	try {
	// 		const report = await getReport(summary.schedule_id, id);
	// 		if (seq === reportSeq) {
	// 			shown = report;
	// 			reportState = 'ready';
	// 		}
	// 		return true;
	// 	} catch {
	// 		if (seq === reportSeq) {
	// 			if (shown?.id === id) failed = true;
	// 			else reportState = 'failed';
	// 		}
	// 		return false;
	// 	}
	// }
	// OLD CODE END
	async function showReport(id: string): Promise<boolean> {
		const summary = view?.reports.find((r) => r.id === id);
		if (!summary) return false;
		const seq = ++reportSeq;
		// a new pick supersedes the last one's failure
		reportError = null;
		try {
			const report = await getReport(summary.schedule_id, id);
			if (seq === reportSeq) {
				shown = report;
				reportStale = false;
			}
			return true;
		} catch (err) {
			if (seq === reportSeq) {
				if (shown?.id === id) reportStale = true;
				else reportError = daemonReason(err) ?? '';
			}
			return false;
		}
	}

	/** The card's schedule, its reports, then the report on screen (the one picked while still listed, else the newest). */
	async function loadData(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		let next: View;
		try {
			const { schedules } = await getReportSchedules();
			// Other schedules are API-only (plan §3.2): the page shows the card's
			const card = schedules.find((s) => s.card) ?? null;
			next = { schedule: card, reports: card ? (await getReportHistory(card.id)).reports : [] };
		} catch (err) {
			if (!guard.current(g)) return 'skipped';
			failed = true;
			// OLD CODE: (none: the catch dropped the daemon's sentence) (TypeScript review: an unreadable store read "check NetTap is running")
			failReason = daemonReason(err);
			loading = false;
			return 'failed';
		}
		if (!guard.current(g)) return 'skipped';
		view = next;
		failed = false;
		failReason = null;
		loading = false;
		loadedAt = Date.now();
		const id = next.reports.some((r) => r.id === selectedId) ? selectedId : (next.reports[0]?.id ?? null);
		selectedId = id;
		if (!id) {
			shown = null;
			// OLD CODE: reportState = 'idle'; (TypeScript review: derived from `current` now)
			reportError = null;
			reportStale = false;
			return 'ok';
		}
		return (await showReport(id)) ? 'ok' : 'partial';
	}

	async function pick(row: Row) {
		selectedId = row.id;
		void showReport(row.id);
		// the report is above the table: focus its heading so it scrolls into view and is read out
		await tick();
		const heading = document.querySelector<HTMLElement>('.report-hero .card-title');
		if (!heading) return;
		heading.tabIndex = -1;
		heading.focus();
	}

	async function generate() {
		if (!schedule) return;
		generating = true;
		generated = null;
		try {
			const report = await generateReport(schedule.id);
			generated = { text: `Report made for ${periodWords(report.period)}. Generate now keeps it here and doesn't email it.`, tone: 'is-ok' };
			// OLD CODE: selectedId = report.id; shown = report; reportState = 'ready'; (TypeScript review: a pick still in flight could overwrite it)
			reportSeq++;
			selectedId = report.id;
			shown = report;
			reportError = null;
			reportStale = false;
			await refresh.run();
		} catch (err) {
			// a 409 ("A report is being generated…") is a wait, not a failure
			const conflict = err instanceof ReportsError && err.status === 409;
			generated = { text: err instanceof Error ? err.message : "Couldn't make the report.", tone: conflict ? 'is-warn' : 'is-error' };
		} finally {
			generating = false;
		}
	}

	interface Row {
		id: string;
		period: string;
		first: string;
		generated: string;
		generated_at: string;
		trigger: string;
		delivery: string;
	}

	const rows = $derived<Row[]>(
		(view?.reports ?? []).map((r) => ({
			id: r.id,
			period: periodWords(r.period),
			first: r.period.first,
			generated: zonedTime(r.generated_at, tz),
			generated_at: r.generated_at,
			trigger: TRIGGER_WORDS[r.trigger] ?? r.trigger,
			delivery: deliveryWords(r.delivery.result),
		})),
	);
	const columns: Column<Row>[] = [
		{ key: 'period', label: 'Period', sortValue: (r) => r.first },
		{ key: 'generated', label: 'Generated', sortValue: (r) => r.generated_at },
		{ key: 'trigger', label: 'Trigger' },
		{ key: 'delivery', label: 'Delivery' },
	];

	// OLD CODE START — TypeScript review: the head named the last report loaded, even while another was loading or had failed
	// const heroTitle = $derived(shown ? `Report for ${periodWords(shown.period)}` : 'Latest report');
	// const heroSub = $derived(
	// 	shown
	// 		? `Generated ${zonedTime(shown.generated_at, shown.period.tz)} · ${TRIGGER_WORDS[shown.trigger] ?? shown.trigger} · ${deliveryWords(shown.delivery.result)}`
	// 		: 'Five sections, each with what it covers',
	// );
	// OLD CODE END
	/** The selected report's head: from its history row, or the report itself until the history lists it (Generate now). */
	const picked = $derived(view?.reports.find((r) => r.id === selectedId) ?? current);
	const heroTitle = $derived(picked ? `Report for ${periodWords(picked.period)}` : 'Latest report');
	const heroSub = $derived(
		picked
			? `Generated ${zonedTime(picked.generated_at, tz)} · ${TRIGGER_WORDS[picked.trigger] ?? picked.trigger} · ${deliveryWords(picked.delivery.result)}`
			: 'Five sections, each with what it covers',
	);
</script>

<svelte:head>
	<title>Reports | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">Reports</h1>
		<p class="page-sub">What your network did each week, in plain English · times in {tz ?? "NetTap's time zone"}</p>
	</div>
	<div class="head-actions">
		<button class="btn primary" type="button" onclick={generate} disabled={!schedule || generating}>
			<Icon name="play" />{generating ? 'Generating…' : 'Generate now'}
		</button>
	</div>
</div>

<div class="grid">
	{#if generated}
		<p class={['notice', 'c-12', generated.tone]} role={generated.tone === 'is-error' ? 'alert' : 'status'}>
			<Icon name={generated.tone === 'is-ok' ? 'check' : 'warn'} /><span>{generated.text}</span>
		</p>
	{/if}
	<!-- OLD CODE: {#if failed && view} (TypeScript review: a report's failed refresh has its own flag, which a later pick clears) -->
	{#if (failed && view) || reportStale}
		<p class="notice is-warn c-12" role="status"><Icon name="warn" /><span>{loadFailed('the reports', true, loadedAt)}{failed && failReason ? ` ${failReason}` : ''}</span></p>
	{/if}

	<KpiCard class="c-3" label="Next report" icon="changelog" value={next.value} note={next.note} />
	<KpiCard class="c-3" label="Last sent" icon="up" value={delivery.last.value} note={delivery.last.note} />
	<KpiCard class="c-3" label="Delivery" icon="check" value={delivery.delivery.value} note={delivery.delivery.note} />
	<KpiCard class="c-3" label="Days covered" icon="bandwidth" value={covered.value} note={covered.note} sub={covered.sub} />

	<Card title={heroTitle} sub={heroSub} hero class="c-12 report-hero">
		{#if loading}
			<CardState state="loading" title="Loading the latest report" />
		{:else if !view}
			<CardState state="error" title={loadFailed('the reports')} message={failReason ?? RUNNING_HINT} onaction={() => refresh.run()} />
		{:else if !schedule}
			<!-- OLD CODE: message="Turn it on in Settings › Notifications: NetTap emails what your network did each week, and keeps each report here." (NET-357: name the step, save, and what email needs) -->
			<CardState
				state="empty"
				icon="logs"
				title="No weekly report set up."
				message="Turn on Make a weekly report in Settings › Notifications and save. NetTap keeps each report here. To have it emailed too, add addresses there and set up the email server in Settings › API keys."
				href={SETTINGS_HREF}
				actionLabel="Open Settings › Notifications"
			/>
		{:else if !selectedId}
			<CardState
				state="empty"
				icon="logs"
				title="No reports yet."
				message={schedule.next_send ? `The first one is made on ${zonedTime(schedule.next_send, tz)}. Generate now makes one for the last full week.` : 'Generate now makes one for the last full week.'}
			/>
		{:else if current}
			<ReportSections report={current} />
		{:else if reportError !== null}
			<CardState state="error" title={loadFailed('this report')} message={reportError || 'Try again, or pick another report below.'} onaction={() => selectedId && showReport(selectedId)} />
		{:else}
			<CardState state="loading" title="Loading the report" />
		{/if}
	</Card>

	<Card title="History" sub="This schedule's reports, newest first · the newest 12 are kept" class="c-12">
		{#if loading}
			<CardState state="loading" title="Loading the report history" />
		{:else if !view}
			<CardState state="error" title={loadFailed('the report history')} message={failReason ?? RUNNING_HINT} onaction={() => refresh.run()} />
		{:else if rows.length === 0}
			<!-- OLD CODE: … : 'Set up the weekly report in Settings › Notifications.' (NET-357: name the step) -->
			<CardState
				state="empty"
				icon="logs"
				title="No reports yet."
				message={schedule ? 'Each report is listed here once it is made.' : 'Turn on Make a weekly report in Settings › Notifications and save.'}
				href={schedule ? undefined : SETTINGS_HREF}
				actionLabel={schedule ? undefined : 'Open Settings › Notifications'}
			/>
		{:else}
			<DataTable
				ariaLabel="Report history"
				{rows}
				{columns}
				rowKey={(r) => r.id}
				initialSort={{ key: 'generated', dir: 'desc' }}
				onrowactivate={pick}
				rowLabel={(r) => `Show the report for ${r.period}, generated ${r.generated}`}
				selectedKey={selectedId ?? undefined}
			/>
		{/if}
	</Card>
</div>
