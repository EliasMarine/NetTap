<!--
  Settings › Notifications › Weekly report (NET-340): the one schedule the card manages (`card: true`,
  never just the first listed). Save always confirms (`confirm: true`) with the token and rev it was
  shown, so it confirms exactly these settings; the daemon creates the schedule on the first save.
  Its refusals (a send in progress, settings changed in another window) show as they are; after a 409
  the card reloads the schedule, so the next Save carries the current token and rev.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { daemonReason, getReportSchedules, ReportsError, upsertReportCard, type ReportSchedule } from '$lib/api/reports';
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

	// OLD CODE: /** A new schedule's starting point: on, Monday at 08:00, no addresses yet. */
	// OLD CODE: const NEW_FORM: Form = { enabled: true, weekday: 0, hour: 8, recipients: '' }; (NET-357: the switch showed on while nothing was saved, and Reports said none was set up)
	/** Before the first save there is no schedule, so the switch is off: Monday at 08:00, no addresses yet. */
	const NEW_FORM: Form = { enabled: false, weekday: 0, hour: 8, recipients: '' };

	let phase = $state<'loading' | 'ready' | 'failed'>('loading');
	/** The daemon's sentence for a failed load; null when NetTap couldn't be reached. */
	let loadReason = $state<string | null>(null);
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
		// OLD CODE: } catch { (TypeScript review: the daemon's sentence was dropped)
		} catch (err) {
			loadReason = daemonReason(err);
			phase = 'failed';
		}
	}

	/**
	 * After a 409: the schedule as it is now, so the next Save carries its token and rev. The owner's
	 * unsaved edits stay; untouched fields take the new values. Nothing changed means the 409 was a
	 * send in progress, and the daemon's sentence stays.
	 */
	async function reloadAfterConflict(sentToken: string | undefined) {
		let list;
		try {
			list = await getReportSchedules();
		} catch {
			// the daemon's 409 sentence stays on screen; the next Save meets the same 409 and tries again
			return;
		}
		const fresh = list.schedules.find((s) => s.card) ?? null;
		if (fresh?.confirm_token === sentToken) return;
		// OLD CODE START — NET-357: any edit kept the whole local form, so a retry after changing only the day
		// sent this window's switch and addresses over the other window's
		// const edited = !same(form, saved);
		// schedule = fresh;
		// zone = fresh?.tz ?? list.tz ?? zone;
		// saved = fresh ? formOf(fresh) : { ...NEW_FORM };
		// if (!edited) form = { ...saved };
		// message = edited
		// 	? 'These settings changed in another window. NetTap loaded them and kept your edits: check them and save again.'
		// 	: 'These settings changed in another window. NetTap loaded them: check them and save again.';
		// OLD CODE END
		const started = saved;
		const next = fresh ? formOf(fresh) : { ...NEW_FORM };
		const mine = addresses(form.recipients);
		const addressesEdited = mine.join('\n') !== addresses(started.recipients).join('\n');
		// both windows changed the addresses: the saved list stays, so nothing removed there comes back unasked
		// OLD CODE: const addressClash = addressesEdited && addresses(next.recipients).join('\n') !== addresses(started.recipients).join('\n'); (review: both windows typing the same list is no clash)
		const theirs = addresses(next.recipients).join('\n');
		const addressClash = addressesEdited && theirs !== addresses(started.recipients).join('\n') && theirs !== mine.join('\n');
		const merged: Form = {
			enabled: form.enabled !== started.enabled ? form.enabled : next.enabled,
			weekday: form.weekday !== started.weekday ? form.weekday : next.weekday,
			hour: form.hour !== started.hour ? form.hour : next.hour,
			recipients: addressesEdited && !addressClash ? form.recipients : next.recipients,
		};
		const edited = !same(form, started);
		schedule = fresh;
		zone = fresh?.tz ?? list.tz ?? zone;
		saved = next;
		form = merged;
		message = !edited
			? 'These settings changed in another window. NetTap loaded them: check them and save again.'
			: addressClash
				? `These settings changed in another window. NetTap loaded them and kept your other edits. The addresses changed there too, so the saved ones are shown; yours were: ${mine.join(', ') || 'none'}. Check them and save again.`
				: 'These settings changed in another window. NetTap loaded them and kept your edits: check them and save again.';
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
			// TypeScript review: every retry resent the stale token, so the card never recovered
			if (err instanceof ReportsError && err.status === 409) await reloadAfterConflict(schedule?.confirm_token);
		} finally {
			saving = false;
		}
	}

	const hourLabel = (h: number) => `${String(h).padStart(2, '0')}:00`;

	onMount(load);
</script>

<!-- OLD CODE: sub="What your network did over the last week, emailed once a week · past reports are on the Reports page" (NET-357: email is optional) -->
<Card title="Weekly report" sub="What your network did over the last week, made once a week · kept on the Reports page, and emailed to the addresses below" class="c-12">
	{#if phase === 'loading'}
		<CardState state="loading" title="Loading the weekly report" />
	{:else if phase === 'failed'}
		<!-- OLD CODE: message="Check that NetTap is running on the System page, then try again." (TypeScript review: the daemon's sentence first) -->
		<CardState state="error" title={loadFailed('the weekly report')} message={loadReason ?? 'Check that NetTap is running on the System page, then try again.'} onaction={load} />
	{:else}
		<div class="stack">
			{#if schedule?.needs_review}
				<p class="notice is-warn" role="status"><Icon name="warn" /><span>Paused until you check the recipients and save.</span></p>
			{/if}
			<Feedback {message} {isError} />
			<div class="switch-row">
				<input type="checkbox" role="switch" class="switch" id="report-enabled" bind:checked={form.enabled} disabled={saving} />
				<!-- OLD CODE: <label class="label" for="report-enabled">Email a weekly report</label> (NET-357: with no addresses the report is only kept, not emailed) -->
				<label class="label" for="report-enabled">Make a weekly report</label>
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
				<!-- OLD CODE: {WHAT_IS_SENT}. With no addresses, reports are kept on the Reports page only. (NET-357: email also needs the email server) -->
				<p class="field-help" id="report-what">{WHAT_IS_SENT}. With no addresses, reports are kept on the Reports page only. Email also needs the email server, set in Settings › API keys.</p>
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
