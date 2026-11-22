<!--
  Settings › Notifications › Weekly report (NET-340): the one schedule the card manages (`card: true`,
  never just the first listed). Save always confirms (`confirm: true`) with the token and rev it was
  shown, so it confirms exactly these settings; the daemon creates the schedule on the first save.
  Its refusals (a send in progress, settings changed in another window) show as they are.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { getReportSchedules, upsertReportCard, type ReportSchedule } from '$lib/api/reports';
	import { loadFailed } from '$lib/utils/load-failed';
	import Feedback from './Feedback.svelte';

	interface Props {
		/** The form differs from what was last loaded or saved. */
		dirty?: boolean;
		/** A save is running, so Settings holds a tab switch until it lands. */
		writing?: boolean;
	}

	let { dirty = $bindable(false), writing = $bindable(false) }: Props = $props();

	const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
	const HOURS = Array.from({ length: 24 }, (_, h) => h);
	const WHAT_IS_SENT = 'Internet use, alerts, new devices, offline incidents and the data cap, as plain-text email to these addresses';

	interface Form {
		enabled: boolean;
		weekday: number;
		hour: number;
		recipients: string;
	}

	/** A new schedule's starting point: on, Monday at 08:00, no addresses yet. */
	const NEW_FORM: Form = { enabled: true, weekday: 0, hour: 8, recipients: '' };

	let phase = $state<'loading' | 'ready' | 'failed'>('loading');
	let schedule = $state.raw<ReportSchedule | null>(null);
	let zone = $state<string | null>(null);
	let form = $state<Form>({ ...NEW_FORM });
	let saved = $state<Form>({ ...NEW_FORM });
	let saving = $state(false);
	let message = $state('');
	let isError = $state(false);

	const formOf = (s: ReportSchedule): Form => ({ enabled: s.enabled, weekday: s.weekday, hour: s.hour, recipients: s.recipients.join('\n') });
	/** One address per line; blank lines and surrounding spaces don't count. */
	const addresses = (text: string) => text.split('\n').map((line) => line.trim()).filter(Boolean);
	const same = (a: Form, b: Form) =>
		a.enabled === b.enabled && a.weekday === b.weekday && a.hour === b.hour && addresses(a.recipients).join('\n') === addresses(b.recipients).join('\n');

	const unsaved = $derived(phase === 'ready' && !same(form, saved));
	$effect(() => {
		dirty = unsaved;
		writing = saving;
	});

	function adopt(s: ReportSchedule | null) {
		schedule = s;
		if (s) zone = s.tz;
		saved = s ? formOf(s) : { ...NEW_FORM };
		form = { ...saved };
	}

	async function load() {
		phase = 'loading';
		try {
			const list = await getReportSchedules();
			const card = list.schedules.find((s) => s.card) ?? null;
			zone = card?.tz ?? list.tz ?? null;
			adopt(card);
			phase = 'ready';
		} catch {
			phase = 'failed';
		}
	}

	async function save() {
		message = '';
		saving = true;
		try {
			const s = await upsertReportCard({
				enabled: form.enabled,
				weekday: form.weekday,
				hour: form.hour,
				recipients: addresses(form.recipients),
				confirm: true,
				...(schedule ? { confirm_token: schedule.confirm_token, rev: schedule.rev } : {}),
			});
			adopt(s);
			message = !s.enabled ? 'Saved. The weekly report is off.' : s.recipients.length ? 'Saved. The weekly report is on.' : 'Saved. Reports are kept on the Reports page and not emailed: add an address to email them.';
			isError = false;
		} catch (err) {
			// the form stays as typed, so the owner can try again
			message = err instanceof Error && err.message ? err.message : "Couldn't save the weekly report.";
			isError = true;
		} finally {
			saving = false;
		}
	}

	const hourLabel = (h: number) => `${String(h).padStart(2, '0')}:00`;

	onMount(load);
</script>

<Card title="Weekly report" sub="What your network did over the last week, emailed once a week · past reports are on the Reports page" class="c-12">
	{#if phase === 'loading'}
		<CardState state="loading" title="Loading the weekly report" />
	{:else if phase === 'failed'}
		<CardState state="error" title={loadFailed('the weekly report')} message="Check that NetTap is running on the System page, then try again." onaction={load} />
	{:else}
		<div class="stack">
			{#if schedule?.needs_review}
				<p class="notice is-warn" role="status"><Icon name="warn" /><span>Paused until you check the recipients and save.</span></p>
			{/if}
			<Feedback {message} {isError} />
			<div class="switch-row">
				<input type="checkbox" role="switch" class="switch" id="report-enabled" bind:checked={form.enabled} disabled={saving} />
				<label class="label" for="report-enabled">Email a weekly report</label>
			</div>
			<div class="form-grid">
				<div class="field">
					<label class="label" for="report-weekday">Day</label>
					<select class="select" id="report-weekday" bind:value={form.weekday} disabled={saving}>
						{#each WEEKDAYS as day, i (day)}<option value={i}>{day}</option>{/each}
					</select>
				</div>
				<div class="field">
					<label class="label" for="report-hour">Time</label>
					<select class="select" id="report-hour" bind:value={form.hour} disabled={saving} aria-describedby="report-zone">
						{#each HOURS as h (h)}<option value={h}>{hourLabel(h)}</option>{/each}
					</select>
					<p class="field-help" id="report-zone">Times are in {zone ?? "NetTap's time zone"}.</p>
				</div>
			</div>
			<div class="field">
				<label class="label" for="report-recipients">Email addresses, one per line</label>
				<textarea
					class="textarea mono"
					id="report-recipients"
					rows="3"
					bind:value={form.recipients}
					disabled={saving}
					placeholder="you@example.com"
					aria-describedby="report-what"
				></textarea>
				<p class="field-help" id="report-what">{WHAT_IS_SENT}. With no addresses, reports are kept on the Reports page only.</p>
			</div>
			<div class="form-actions">
				{#if unsaved}<span class="unsaved">Unsaved changes</span>{/if}
				<button class="btn primary" type="button" onclick={save} disabled={saving}>
					{saving ? 'Saving…' : 'Save weekly report'}
				</button>
			</div>
		</div>
	{/if}
</Card>
