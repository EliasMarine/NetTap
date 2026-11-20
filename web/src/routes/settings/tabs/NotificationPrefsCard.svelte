<!--
  NotificationPrefsCard.svelte: Settings › Notifications › Notification preferences (NET-273: moved from
  the Settings page's Notifications tab). The threshold, webhook and email it edits are the daemon's
  "settings-*" channel and rule, which the channel and rule lists beside it also show and change, so the
  Notifications tab runs every write here through its one-at-a-time lock (`run`) and, after a channel or
  rule change, calls `channelsChanged()`: a clean form reloads, an edited one is kept but can't be saved
  until the owner reloads it.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import Feedback from '../Feedback.svelte';

	interface Props {
		/** The tab's lock is held: a save, a channel or rule change, or the reload after it. */
		locked: boolean;
		/** Runs `task` under the tab's lock; does nothing while the lock is held. `write: false` for a read. */
		run: (task: () => Promise<void>, write?: boolean) => Promise<void>;
		/** After a save that worked: the tab reloads its lists (a settings channel may have come or gone). */
		onsaved: () => Promise<unknown>;
		/** The form differs from the settings last loaded or saved. */
		dirty?: boolean;
	}

	let { locked, run, onsaved, dirty = $bindable(false) }: Props = $props();

	// --- Notifications state ---
	let severityThreshold = $state<string>('medium');
	let emailEnabled = $state(false);
	let emailAddress = $state('');
	let webhookUrl = $state('');
	// NET-224: the daemon keeps these; it never sends the saved URL back, only a hint of it
	let webhookEnabled = $state(false);
	let webhookHasUrl = $state(false);
	let webhookHint = $state('');
	let smtpConfigured = $state(false);
	// NET-319: new devices go to the same channels; a config that never set it reads as on
	let newDevice = $state(true);
	// F6 (NET-339): data cap warnings too, on unless turned off
	let dataCap = $state(true);
	// F8 (NET-330): quiet hours. The daemon's default is off, 22:00 to 07:00, critical alerts through.
	const QUIET_DEFAULT = { enabled: false, start: '22:00', end: '07:00', critical_through: true };
	let quietEnabled = $state(QUIET_DEFAULT.enabled);
	let quietStart = $state(QUIET_DEFAULT.start);
	let quietEnd = $state(QUIET_DEFAULT.end);
	let quietCritical = $state(QUIET_DEFAULT.critical_through);
	// The last saved times: the daemon refuses an equal pair, so these are always a pair it accepts
	let savedQuietStart = QUIET_DEFAULT.start;
	let savedQuietEnd = QUIET_DEFAULT.end;
	// The owner's zone (Settings › Display); the daemon reads the times in it. Shown, never edited here.
	let tz = $state('UTC');
	let notifSaving = $state(false);
	let notifMessage = $state('');
	let notifError = $state(false);
	// a failed load leaves blank fields; saving them would wipe the real config
	let notifLoadFailed = $state(false);
	let testingSending = $state(false);
	let testMessage = $state('');
	let testError = $state(false);
	// review L3: the test sends through the saved settings, so it waits while the form differs
	// OLD CODE: JSON.stringify([severityThreshold, emailEnabled, emailAddress, webhookEnabled, webhookUrl]); (NET-319: and new devices)
	// OLD CODE: JSON.stringify([severityThreshold, emailEnabled, emailAddress, webhookEnabled, webhookUrl, newDevice]); (F6: and data cap warnings)
	// OLD CODE: JSON.stringify([severityThreshold, emailEnabled, emailAddress, webhookEnabled, webhookUrl, newDevice, dataCap]); (F8: and quiet hours)
	const notifForm = () =>
		JSON.stringify([
			severityThreshold, emailEnabled, emailAddress, webhookEnabled, webhookUrl, newDevice, dataCap,
			quietEnabled, quietStart, quietEnd, quietCritical,
		]);
	// the blank form until the load lands, so nothing reads as unsaved while it loads
	let notifSavedForm = $state(notifForm());
	// a failed load leaves nothing to compare with; the test then reports the daemon's own answer
	const notifUnsaved = $derived(!notifLoadFailed && notifForm() !== notifSavedForm);
	// NET-273: a channel or rule changed while this form had edits; a save could undo that change
	let conflict = $state(false);

	// F8: with the switch on, the window needs two different times; the daemon refuses anything else.
	// A cleared time field reads as '' in the browser.
	const quietProblem = $derived(
		!quietEnabled
			? ''
			: !quietStart || !quietEnd
				? 'Choose both times.'
				: quietStart === quietEnd
					? 'From and To must be different times.'
					: '',
	);

	/** Turning quiet hours off puts back the last saved times, so a half-typed pair can't stop "off" from saving. */
	function setQuietEnabled(on: boolean) {
		quietEnabled = on;
		if (!on) {
			quietStart = savedQuietStart;
			quietEnd = savedQuietEnd;
		}
	}

	$effect(() => {
		dirty = notifUnsaved;
	});

	// OLD CODE START — NET-224: the web route read env vars compose never set; the daemon keeps the settings now
	// async function loadNotificationConfig() {
	// 	try {
	// 		const res = await fetch('/api/notifications/config');
	// 		if (res.ok) {
	// 			const data = await res.json();
	// 			severityThreshold = data.severityThreshold ?? 'medium';
	// 			emailEnabled = data.email?.enabled ?? false;
	// 			emailAddress = data.email?.recipients?.[0] ?? '';
	// 			webhookUrl = data.webhook?.url ?? '';
	// 			notifLoadFailed = false;
	// 			return;
	// 		}
	// 	} catch {
	// 		// Falls through to failed
	// 	}
	// 	notifLoadFailed = true;
	// }
	// OLD CODE END
	// The daemon's 1 (critical) … 4 (low) as the select's values
	const SEVERITY_VALUES = ['critical', 'high', 'medium', 'low'];

	/** The Settings tab's notification setup as the daemon returns it (GET and a saved PUT). */
	function applyNotificationConfig(data: {
		min_severity?: number;
		email?: { enabled?: boolean; recipients?: string[]; smtp_configured?: boolean };
		webhook?: { enabled?: boolean; has_url?: boolean; url_hint?: string };
		new_device?: boolean;
		data_cap?: boolean;
		quiet?: { enabled?: boolean; start?: string; end?: string; critical_through?: boolean };
		tz?: string;
	}) {
		severityThreshold = SEVERITY_VALUES[(data.min_severity ?? 2) - 1] ?? 'high';
		newDevice = data.new_device ?? true;
		dataCap = data.data_cap ?? true;
		// F8: a daemon from before quiet hours sends neither field, which reads as off with the defaults
		quietEnabled = data.quiet?.enabled ?? QUIET_DEFAULT.enabled;
		quietStart = data.quiet?.start || QUIET_DEFAULT.start;
		quietEnd = data.quiet?.end || QUIET_DEFAULT.end;
		quietCritical = data.quiet?.critical_through ?? QUIET_DEFAULT.critical_through;
		savedQuietStart = quietStart;
		savedQuietEnd = quietEnd;
		tz = data.tz || 'UTC';
		emailEnabled = data.email?.enabled ?? false;
		emailAddress = (data.email?.recipients ?? []).join(', ');
		smtpConfigured = data.email?.smtp_configured ?? false;
		webhookEnabled = data.webhook?.enabled ?? false;
		webhookHasUrl = data.webhook?.has_url ?? false;
		webhookHint = data.webhook?.url_hint ?? '';
		webhookUrl = '';
		notifSavedForm = notifForm();
	}

	async function loadNotificationConfig() {
		try {
			const res = await fetch('/api/notifications/config');
			if (res.ok) {
				applyNotificationConfig(await res.json());
				notifLoadFailed = false;
				return;
			}
		} catch {
			// Falls through to failed
		}
		notifLoadFailed = true;
	}

	/**
	 * NET-273: a channel or rule was created or deleted. A clean form reloads (a deleted settings
	 * channel turns its switch off); an edited one keeps the edits and can't be saved until reloaded.
	 */
	export async function channelsChanged(): Promise<void> {
		if (notifUnsaved) {
			conflict = true;
			return;
		}
		await loadNotificationConfig();
	}

	/** Replaces the form with the daemon's settings: the conflict notice's and the failed load's button. */
	// OLD CODE: run(async () => {…}); (review L5: a read, which doesn't hold a tab switch)
	const reloadPreferences = () =>
		run(async () => {
			await loadNotificationConfig();
			if (!notifLoadFailed) conflict = false;
		}, false);

	async function saveNotifications() {
		notifSaving = true;
		notifMessage = '';
		notifError = false;
		try {
			// OLD CODE START — NET-224: POSTed to a route that couldn't save (F3: 501)
			// const res = await fetch('/api/notifications/config', {
			// 	method: 'POST',
			// 	headers: { 'Content-Type': 'application/json' },
			// 	body: JSON.stringify({
			// 		severityThreshold,
			// 		email: {
			// 			enabled: emailEnabled,
			// 			recipients: emailAddress ? [emailAddress] : [],
			// 		},
			// 		webhook: {
			// 			url: webhookUrl || null,
			// 		},
			// 	}),
			// });
			// if (res.ok) {
			// 	notifMessage = 'Notification settings saved successfully.';
			// } else {
			// OLD CODE END
			const res = await fetch('/api/notifications/config', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					min_severity: SEVERITY_VALUES.indexOf(severityThreshold) + 1,
					email: {
						enabled: emailEnabled,
						recipients: emailAddress.split(',').map((a) => a.trim()).filter(Boolean),
					},
					// a blank URL keeps the saved one
					webhook: { enabled: webhookEnabled, url: webhookUrl.trim() },
					new_device: newDevice,
					data_cap: dataCap,
					quiet: { enabled: quietEnabled, start: quietStart, end: quietEnd, critical_through: quietCritical },
				}),
			});
			// OLD CODE START — review L2: a body that couldn't be read, even after the daemon saved, said "Failed to connect"
			// if (res.ok) {
			// 	applyNotificationConfig(await res.json());
			// 	notifMessage = 'Notification settings saved.';
			// } else {
			// 	const data = await res.json();
			// 	notifMessage = data.error || 'Failed to save notification settings.';
			// 	notifError = true;
			// }
			// OLD CODE END
			const data = await res.json().catch(() => null);
			if (!res.ok) {
				notifMessage = data?.error || `Not saved: NetTap answered ${res.status}.`;
				notifError = true;
				return;
			}
			try {
				applyNotificationConfig(data);
				notifMessage = 'Notification settings saved.';
			} catch {
				notifMessage = "Saved, but the page couldn't read the settings back. Reload the page to see them.";
				notifError = true;
			}
		} catch {
			// OLD CODE: notifMessage = 'Failed to connect to server.'; (review L2: only fetch itself throws here now)
			notifMessage = "Couldn't reach NetTap, so nothing was saved.";
			notifError = true;
		} finally {
			notifSaving = false;
		}
	}

	// NET-273: a save that worked may add or remove a settings channel, so the lists beside it reload
	const save = () =>
		run(async () => {
			await saveNotifications();
			if (!notifError) await onsaved();
		});

	// A test send writes a delivery, so Recent deliveries beside it reloads after it (review L4)
	const sendTest = () =>
		run(async () => {
			await sendTestNotification();
			await onsaved();
		});

	async function sendTestNotification() {
		testingSending = true;
		testMessage = '';
		testError = false;
		try {
			const res = await fetch('/api/notifications/test', { method: 'POST' });
			const data = await res.json();
			if (res.ok) {
				testMessage = 'Test notification sent successfully.';
			} else {
				testMessage = data.error || 'Failed to send test notification.';
				testError = true;
			}
		} catch {
			testMessage = 'Failed to connect to server.';
			testError = true;
		} finally {
			testingSending = false;
		}
	}

	const severityOptions: { value: string; label: string }[] = [
		{ value: 'critical', label: 'Critical only' },
		{ value: 'high', label: 'High and above' },
		{ value: 'medium', label: 'Medium and above' },
		{ value: 'low', label: 'All severities' },
	];

	// The form loads once here, and again when the tab opens again or a channel changes
	onMount(() => {
		// OLD CODE: loadNotificationConfig(); (review L5: a channel change could reload under it)
		void run(loadNotificationConfig, false);
	});
</script>

<!-- OLD CODE: sub="Which alerts reach you · by email and webhook" (NET-224: the daemon sends them now) -->
<!-- OLD CODE: sub="Which alerts reach you · by email and webhook, with or without this page open" (NET-319: new devices too) -->
<!-- OLD CODE: sub="Which alerts and new devices reach you · by email and webhook, with or without this page open" (F6: data cap warnings too) -->
<Card title="Notification preferences" sub="Which alerts, new devices and data cap warnings reach you · by email and webhook, with or without this page open" class="c-12">
	<!-- NET-273: disabled while the tab's lock is held, so nothing is typed into a form a reply is about to replace -->
	<fieldset class="stack prefs" disabled={locked}>
		{#if notifLoadFailed}
			<!-- OLD CODE: {@render feedback('Could not load the current notification settings, so saving is off. Reload the page to try again.', true)} (NET-273: a button reloads the form) -->
			<div class="notice is-error" role="alert">
				<Icon name="warn" /><span>Could not load the current notification settings, so saving is off.</span>
				<button class="btn" type="button" onclick={reloadPreferences}>Reload preferences</button>
			</div>
		{/if}
		{#if conflict}
			<div class="notice is-warn" role="status">
				<Icon name="warn" /><span>Channels changed since you started editing these preferences.</span>
				<button class="btn" type="button" onclick={reloadPreferences}>Reload preferences</button>
			</div>
		{/if}
		<Feedback message={notifMessage} isError={notifError} />

		<div class="form-grid">
			<div class="field">
				<label class="label" for="severity-threshold">Alert severity threshold</label>
				<select class="select" id="severity-threshold" bind:value={severityThreshold}>
					{#each severityOptions as opt (opt.value)}
						<option value={opt.value}>{opt.label}</option>
					{/each}
				</select>
				<p class="field-help">Only notify for alerts at or above this severity level.</p>
			</div>
			<!-- OLD CODE START — NET-224: the URL field had no on/off, and blank meant "no webhook"; the daemon never sends the saved URL back, so blank now keeps it
			<div class="field">
				<label class="label" for="webhook-url">Webhook URL</label>
				<input class="input mono" id="webhook-url" type="url" bind:value={webhookUrl} placeholder="https://hooks.example.com/nettap" />
				<p class="field-help">POST JSON payloads will be sent to this URL for each alert.</p>
			</div>
			OLD CODE END -->
		</div>

		<!-- NET-319: new devices reach the same webhook and email as alerts -->
		<div class="switch-row">
			<input type="checkbox" role="switch" class="switch" id="new-device-toggle" bind:checked={newDevice} aria-describedby="new-device-toggle-help" />
			<div>
				<label class="label" for="new-device-toggle">Tell me about new devices</label>
				<p class="field-help" id="new-device-toggle-help">A message when a device joins your network for the first time, through the webhook and email below, whatever the severity threshold.</p>
			</div>
		</div>

		<!-- F6 (NET-339): data cap warnings reach the same webhook and email -->
		<div class="switch-row">
			<input type="checkbox" role="switch" class="switch" id="data-cap-toggle" bind:checked={dataCap} aria-describedby="data-cap-toggle-help" />
			<div>
				<label class="label" for="data-cap-toggle">Tell me when I near my data cap</label>
				<p class="field-help" id="data-cap-toggle-help">
					A message at 80% and 100% of your monthly cap, and when the month is on track to go over, through the webhook and email below, whatever the severity threshold. Set the cap in the <a class="link" href="?tab=network">Network tab</a>.
				</p>
			</div>
		</div>

		<!-- F8 (NET-330): quiet hours hold every channel's messages overnight, then send one -->
		<div class="switch-row">
			<input
				type="checkbox"
				role="switch"
				class="switch"
				id="quiet-toggle"
				checked={quietEnabled}
				onchange={(e) => setQuietEnabled(e.currentTarget.checked)}
				aria-describedby="quiet-toggle-help"
			/>
			<div>
				<label class="label" for="quiet-toggle">Hold notifications overnight</label>
				<p class="field-help" id="quiet-toggle-help">Alerts, new devices and data cap warnings wait, then arrive as one message when quiet hours end.</p>
			</div>
		</div>

		{#if quietEnabled}
			<div class="form-grid">
				<div class="field">
					<label class="label" for="quiet-start">From</label>
					<input
						class="input"
						id="quiet-start"
						type="time"
						bind:value={quietStart}
						aria-invalid={quietProblem ? 'true' : undefined}
						aria-describedby={quietProblem ? 'quiet-zone-help quiet-error' : 'quiet-zone-help'}
					/>
				</div>
				<div class="field">
					<label class="label" for="quiet-end">To</label>
					<input
						class="input"
						id="quiet-end"
						type="time"
						bind:value={quietEnd}
						aria-invalid={quietProblem ? 'true' : undefined}
						aria-describedby={quietProblem ? 'quiet-zone-help quiet-error' : 'quiet-zone-help'}
					/>
				</div>
			</div>
			{#if quietProblem}<p class="field-error" id="quiet-error" role="alert">{quietProblem}</p>{/if}
			<p class="field-help" id="quiet-zone-help">
				Times are in your time zone, {tz}. Change it in the <a class="link" href="?tab=display">Display tab</a>.
			</p>
			<div class="switch-row">
				<input type="checkbox" role="switch" class="switch" id="quiet-critical-toggle" bind:checked={quietCritical} aria-describedby="quiet-critical-toggle-help" />
				<div>
					<label class="label" for="quiet-critical-toggle">Critical alerts come through</label>
					<p class="field-help" id="quiet-critical-toggle-help">A critical alert is sent at once, on its own. Held notifications stay held until quiet hours end.</p>
				</div>
			</div>
		{/if}

		<div class="switch-row">
			<input type="checkbox" role="switch" class="switch" id="webhook-toggle" bind:checked={webhookEnabled} aria-describedby="webhook-toggle-help" />
			<div>
				<label class="label" for="webhook-toggle">Send alerts to a webhook</label>
				<p class="field-help" id="webhook-toggle-help">NetTap POSTs a JSON message for each batch of alerts, with or without this page open. Turning it off keeps the URL.</p>
			</div>
		</div>

		{#if webhookEnabled}
			<div class="form-grid">
				<div class="field">
					<label class="label" for="webhook-url">Webhook URL</label>
					<input
						class="input mono"
						id="webhook-url"
						type="url"
						bind:value={webhookUrl}
						placeholder={webhookHasUrl ? `Saved (${webhookHint}): leave blank to keep it` : 'https://hooks.example.com/nettap'}
					/>
					<p class="field-help">http:// or https:// only. An address on your network works (ntfy, Gotify).</p>
				</div>
			</div>
		{/if}

		<div class="switch-row">
			<input type="checkbox" role="switch" class="switch" id="email-toggle" bind:checked={emailEnabled} aria-describedby="email-toggle-help" />
			<div>
				<label class="label" for="email-toggle">Enable email alerts</label>
				<p class="field-help" id="email-toggle-help">Send alert notifications to the addresses below, through the SMTP server in API keys.</p>
			</div>
		</div>

		{#if emailEnabled}
			{#if !smtpConfigured}
				<!-- OLD CODE: <span>Email needs an SMTP server: set it in the API keys tab first.</span> (NET-273: the tab is a link) -->
				<p class="notice is-warn" role="status"><Icon name="warn" /><span>Email needs an SMTP server: set it in the <a class="link" href="?tab=api-keys">API keys tab</a> first.</span></p>
			{/if}
			<div class="form-grid">
				<div class="field">
					<!-- OLD CODE: <label …>Recipient email</label> with type="email" (NET-224: several recipients, comma-separated) -->
					<label class="label" for="email-address">Recipient emails</label>
					<input class="input" id="email-address" type="text" bind:value={emailAddress} placeholder="admin@example.com, ops@example.com" />
				</div>
			</div>
		{/if}

		<div class="form-actions">
			{#if notifUnsaved}<span class="unsaved">Unsaved changes</span>{/if}
			<!-- OLD CODE: <button … disabled={testingSending}> (review L3: it tested the saved settings, whatever the form said) -->
			<!-- OLD CODE: onclick={() => run(sendTestNotification)} (review L4: Recent deliveries reloads after a test send) -->
			<button class="btn" type="button" onclick={sendTest} disabled={testingSending || notifUnsaved} aria-describedby={notifUnsaved ? 'notif-test-help' : undefined}>
				{testingSending ? 'Sending…' : 'Send test notification'}
			</button>
			<!-- OLD CODE: disabled={notifSaving || notifLoadFailed} (NET-273: also off after a channel change, until the form is reloaded) -->
			<!-- OLD CODE: disabled={notifSaving || notifLoadFailed || conflict} (F8: also off while the quiet hours times are invalid) -->
			<button class="btn primary" type="button" onclick={save} disabled={notifSaving || notifLoadFailed || conflict || !!quietProblem}>
				{notifSaving ? 'Saving…' : 'Save notification settings'}
			</button>
		</div>
		{#if notifUnsaved}
			<p class="field-help" id="notif-test-help">Save first: the test uses the saved settings.</p>
		{/if}
		<Feedback message={testMessage} isError={testError} />
	</fieldset>
</Card>

<style>
	.prefs {
		border: 0;
		padding: 0;
		margin: 0;
		min-width: 0;
	}

	.notice .btn {
		margin-left: auto;
		flex: none;
	}
</style>
