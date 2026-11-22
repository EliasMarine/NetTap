<!--
  ReportSections.svelte (NET-340): one report's five sections, each with its status, its own
  coverage line and, when partial or unavailable, the daemon's reason. An unavailable section
  shows no figures, so a missing week never reads as a quiet one.
-->
<script lang="ts">
	import type { Report } from '$lib/api/reports';
	import { formatBytes } from '$lib/api/logs';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import StatStrip from '$lib/components/ui/StatStrip.svelte';
	import { fmt } from '$lib/utils/drilldown';
	import { suricataLevel } from '$lib/utils/severity';
	import { monthName } from '../bandwidth/usage-words';
	import { STATUS_CHIP, UNRECORDED_END, countOf, crossingWords, dayNote, dayWords, durationWords, gb, periodNoun, zonedTime } from './report-words';

	let { report }: { report: Report } = $props();

	const s = $derived(report.sections);
	const tz = $derived(report.period.tz);
	const noun = $derived(periodNoun(report.frequency));
	const bytes = (n: number | null | undefined) => (n == null ? '—' : formatBytes(n));
	const count = (n: number | null | undefined) => (n == null ? '—' : fmt(n));

	type Day = NonNullable<Report['sections']['alerts']['days']>[number];
	type Rule = NonNullable<Report['sections']['alerts']['worst']>[number];
	type Device = NonNullable<Report['sections']['new_devices']['listed']>[number];
	type Incident = NonNullable<Report['sections']['offline']['incidents']>[number];

	const dayColumns: Column<Day>[] = [
		{ key: 'date', label: 'Day', cell: dayCell },
		{ key: 'count', label: 'Alerts', numeric: true, cell: dayCountCell },
		{ key: 'note', label: 'Stored', sortValue: dayNote, cell: dayNoteCell },
	];
	const ruleColumns: Column<Rule>[] = [
		{ key: 'rule', label: 'Rule', cell: ruleCell },
		// lower is worse; unknown sorts after severity 3
		{ key: 'severity', label: 'Severity', sortValue: (r) => -(r.severity ?? 4), cell: severityCell },
		{ key: 'count', label: 'Alerts', numeric: true, cell: ruleCountCell },
		{ key: 'what', label: 'What it means', cell: whatCell },
	];
	const deviceColumns: Column<Device>[] = [
		{ key: 'name', label: 'Device', sortValue: (d) => d.name ?? d.mac, cell: deviceCell },
		{ key: 'vendor', label: 'Maker', sortValue: (d) => d.vendor ?? '', cell: vendorCell },
		{ key: 'ip', label: 'Address', sortValue: (d) => d.ip ?? '', cell: ipCell },
		{ key: 'first_seen', label: 'First seen', cell: firstSeenCell },
	];
	const incidentColumns: Column<Incident>[] = [
		{ key: 'name', label: 'Device', sortValue: (i) => i.name ?? i.mac, cell: incidentDeviceCell },
		{ key: 'from', label: 'Offline from', cell: fromCell },
		{ key: 'to', label: 'Back', sortValue: (i) => i.to ?? '', cell: toCell },
		{ key: 'minutes', label: 'For', numeric: true, sortValue: (i) => i.minutes ?? -1, cell: minutesCell },
	];
</script>

{#snippet head(title: string, section: { status: keyof typeof STATUS_CHIP; coverage: string; note: string | null })}
	<div class="rs-head">
		<h3 class="rs-title">{title}</h3>
		<span class={['chip', STATUS_CHIP[section.status]?.cls]}>{STATUS_CHIP[section.status]?.text ?? section.status}</span>
	</div>
	{#if section.status !== 'unavailable'}<p class="card-sub">{section.coverage}</p>{/if}
	{#if section.note}
		<p class={['notice', section.status === 'unavailable' ? 'is-error' : 'is-warn']} role="status"><Icon name="warn" /><span>{section.note}</span></p>
	{/if}
{/snippet}

{#snippet dayCell(d: Day)}<span class="num">{dayWords(d.date)}</span>{/snippet}
{#snippet dayCountCell(d: Day)}{fmt(d.count)}{/snippet}
{#snippet dayNoteCell(d: Day)}<span class="wrap dim">{dayNote(d) || 'Stored'}</span>{/snippet}
{#snippet ruleCell(r: Rule)}<span class="wrap mono">{r.rule}</span>{/snippet}
{#snippet severityCell(r: Rule)}{#if r.severity == null}<span class="dim">Severity unknown</span>{:else}<SeverityPill level={suricataLevel(r.severity)} />{/if}{/snippet}
{#snippet ruleCountCell(r: Rule)}{fmt(r.count)}{/snippet}
{#snippet whatCell(r: Rule)}<span class="wrap">{r.what}</span>{/snippet}
{#snippet deviceCell(d: Device)}<span class="two">{d.name ?? d.mac}{#if d.name}<span class="mono">{d.mac}</span>{/if}</span>{/snippet}
{#snippet vendorCell(d: Device)}{d.vendor ?? '—'}{/snippet}
{#snippet ipCell(d: Device)}<span class="mono">{d.ip ?? '—'}</span>{/snippet}
{#snippet firstSeenCell(d: Device)}<span class="num">{zonedTime(d.first_seen, tz)}</span>{/snippet}
{#snippet incidentDeviceCell(i: Incident)}<span class="two">{i.name ?? i.mac}{#if i.name}<span class="mono">{i.mac}</span>{/if}</span>{/snippet}
{#snippet fromCell(i: Incident)}<span class="num">{zonedTime(i.from, tz)}</span>{/snippet}
{#snippet toCell(i: Incident)}
	<!-- with no time, the daemon's detail is the end ("Returned before 14 Nov 09:12, time not recorded") -->
	<span class="two wrap">
		{i.to ? zonedTime(i.to, tz) : (i.detail ?? UNRECORDED_END[i.state] ?? '—')}
		{#if i.to && i.detail}<span class="dim">{i.detail}</span>{/if}
	</span>
{/snippet}
{#snippet minutesCell(i: Incident)}{durationWords(i.minutes)}{/snippet}

<div class="sections">
	<section class="rs" aria-label="Internet use">
		{@render head('Internet use', s.traffic)}
		{#if s.traffic.status !== 'unavailable'}
			{@const t = s.traffic}
			<StatStrip
				stats={[
					{ key: 'total', label: t.provisional ? 'Total (provisional)' : 'Total', value: bytes(t.total) },
					{ key: 'down', label: 'Downloaded', value: bytes(t.download) },
					{ key: 'up', label: 'Uploaded', value: bytes(t.upload) },
					{ key: 'local', label: 'Local', value: bytes(t.local) },
				]}
			/>
			{#if t.counted_total != null && (t.provisional || (t.total != null && t.counted_total < t.total))}
				<!-- OLD CODE: At least {formatBytes(t.counted_total)} … (ponytail review: formatBytes rounds a minimum up, 82.46 GB read "82.5 GB") -->
				<p class="line">At least {gb(t.counted_total, true)} counted under your current exclusions.</p>
			{/if}
			<p class="line">
				{#if t.busiest}Busiest day: {dayWords(t.busiest.date)}, with {formatBytes(t.busiest.total)}.{:else}No usage was counted {noun}.{/if}
			</p>
		{/if}
	</section>

	<section class="rs" aria-label="Alerts">
		{@render head('Alerts', s.alerts)}
		{#if s.alerts.status !== 'unavailable'}
			{@const a = s.alerts}
			<StatStrip
				stats={[
					{ key: 'total', label: 'Alerts', value: count(a.total) },
					{ key: 'high', label: 'High', value: count(a.by_severity?.['1']) },
					{ key: 'medium', label: 'Medium', value: count(a.by_severity?.['2']) },
					{ key: 'low', label: 'Low', value: count(a.by_severity?.['3']) },
				]}
			/>
			{#if a.by_severity?.other}
				<p class="line">{countOf(a.by_severity.other, 'alert has', 'alerts have')} no severity recorded.</p>
			{/if}
			{#if a.days?.length}
				<DataTable ariaLabel="Alerts per day" rows={a.days} columns={dayColumns} rowKey={(d) => d.date} />
			{/if}
			<h4 class="rs-sub">Worst rules</h4>
			{#if a.worst == null}
				<!-- OLD CODE: <span>Not included this time.{a.worst_note ? ` ${a.worst_note}` : ''}</span> (ponytail review: the daemon's note starts with those words, so they showed twice) -->
				<p class="notice" role="status"><Icon name="empty" /><span>{a.worst_note ?? 'Not included this time.'}</span></p>
			{:else if a.worst.length === 0}
				<p class="line">No alerts {noun}.</p>
			{:else}
				<DataTable ariaLabel="Worst rules" rows={a.worst} columns={ruleColumns} rowKey={(r) => r.rule} />
			{/if}
		{/if}
	</section>

	<section class="rs" aria-label="New devices">
		{@render head('New devices', s.new_devices)}
		{#if s.new_devices.status !== 'unavailable'}
			{@const n = s.new_devices}
			<StatStrip stats={[{ key: 'count', label: 'Seen for the first time', value: count(n.count) }]} />
			{#if n.listed?.length}
				{#if n.count != null && n.count > n.listed.length}
					<p class="line">Showing the first {fmt(n.listed.length)} of {fmt(n.count)}.</p>
				{/if}
				<DataTable ariaLabel="New devices" rows={n.listed} columns={deviceColumns} rowKey={(d) => d.mac} />
			{/if}
		{/if}
	</section>

	<section class="rs" aria-label="Offline incidents">
		{@render head('Offline incidents', s.offline)}
		{#if s.offline.status !== 'unavailable'}
			{@const o = s.offline}
			<StatStrip
				stats={[
					{ key: 'incidents', label: 'Times a watched device went offline', value: count(o.incidents?.length) },
					{ key: 'watched', label: 'Watched now', value: count(o.watched_now) },
				]}
			/>
			{#if o.incidents?.length}
				<DataTable ariaLabel="Offline incidents" rows={o.incidents} columns={incidentColumns} rowKey={(i) => `${i.mac}|${i.from}`} />
			{:else if o.incidents}
				<p class="line">No watched device went offline.</p>
			{/if}
		{/if}
	</section>

	<section class="rs" aria-label="Data cap">
		{@render head('Data cap', s.data_cap)}
		{#if s.data_cap.status !== 'unavailable'}
			{@const c = s.data_cap}
			{@const month = c.month && /^\d{4}-\d{2}$/.test(c.month) ? monthName(Number(c.month.slice(0, 4)), Number(c.month.slice(5))) : c.month}
			{#if c.cap_bytes == null}
				<p class="line">No data cap set.</p>
			{/if}
			<StatStrip
				stats={[
					{ key: 'used', label: `Counted in ${month ?? 'the month'}`, value: gb(c.used_counted, true) },
					...(c.used_provisional != null && c.used_provisional !== c.used_counted ? [{ key: 'prov', label: 'Provisional total', value: gb(c.used_provisional) }] : []),
					...(c.cap_bytes != null ? [{ key: 'cap', label: 'Your current cap', value: gb(c.cap_bytes) }] : []),
					...(c.percent != null ? [{ key: 'pct', label: 'Of your current cap', value: `${c.percent.toFixed(1)}%` }] : []),
				]}
			/>
			{#if c.crossings === null}
				<p class="line">Couldn't read the cap warnings this time.</p>
			{/if}
			{#each c.crossings ?? [] as x (`${x.month}|${x.threshold}|${x.at}`)}
				<p class="line">{crossingWords(x, tz)}</p>
			{/each}
		{/if}
	</section>

	<p class="posture">Security posture isn't part of this report. <a class="link" href="/compliance">Open Security posture</a> for the full picture.</p>
</div>

<style>
	/* Layout glue: the sections stack with a hairline between them, each head a title beside its status */
	.sections { display: flex; flex-direction: column; }
	.rs { display: flex; flex-direction: column; gap: var(--sp-3); padding-block: var(--sp-5); min-width: 0; }
	.rs:first-child { padding-top: 0; }
	.rs + .rs, .posture { border-top: 1px solid var(--line); }
	.posture { margin: 0; padding-top: var(--sp-5); font-size: var(--text-sm); color: var(--text-2); }
	.rs-head { display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap; }
	.rs-title { margin: 0; font-size: var(--text-md); font-weight: 600; color: var(--text-1); }
	.rs-sub { margin: 0; font-size: var(--text-sm); font-weight: 600; color: var(--text-2); }
	.line { margin: 0; font-size: var(--text-sm); color: var(--text-2); }
	/* Table cells don't wrap (system.css); a long rule name or note does, down to 10rem, instead of widening the table (as on Changelog) */
	.wrap { display: inline-block; white-space: normal; overflow-wrap: anywhere; min-width: 10rem; }
</style>
