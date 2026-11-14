<!--
  Settings › API keys (NET-273: moved from the Settings page): GeoIP and SMTP credentials. Which keys
  are set loads with the form, so it registers no page refresh.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import Feedback from '../Feedback.svelte';

	interface Props {
		/** A value is typed and not saved. */
		dirty?: boolean;
		/** A save is running. */
		busy?: boolean;
	}

	let { dirty = $bindable(false), busy = $bindable(false) }: Props = $props();

	// --- API Keys state ---
	let apiKeysStatus = $state<Record<string, boolean>>({});
	let apiKeysLoading = $state(true);
	let apiKeysSaving = $state(false);
	let apiKeysMessage = $state('');
	let apiKeysError = $state(false);
	// Track modified fields only — don't send unchanged values
	let apiKeyValues = $state<Record<string, string>>({});
	// NET-273: a typed value is an unsaved change; the saved ones are never shown
	const apiKeysUnsaved = $derived(Object.values(apiKeyValues).some((v) => v?.trim()));

	$effect(() => {
		dirty = apiKeysUnsaved;
		busy = apiKeysSaving;
	});

	async function loadApiKeys() {
		apiKeysLoading = true;
		try {
			const res = await fetch('/api/settings/api-keys');
			if (res.ok) {
				const data = await res.json();
				apiKeysStatus = data.keys ?? {};
			}
		} catch {
			// Will use empty default
		} finally {
			apiKeysLoading = false;
		}
	}

	async function saveApiKeys() {
		apiKeysSaving = true;
		apiKeysMessage = '';
		apiKeysError = false;

		// Only send fields that have been modified (non-empty)
		const payload: Record<string, string> = {};
		for (const [key, value] of Object.entries(apiKeyValues)) {
			if (value.trim()) {
				payload[key] = value.trim();
			}
		}

		if (Object.keys(payload).length === 0) {
			apiKeysMessage = 'No changes to save. Enter a value in at least one field.';
			apiKeysError = true;
			apiKeysSaving = false;
			return;
		}

		try {
			const res = await fetch('/api/settings/api-keys', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload),
			});
			const data = await res.json();
			if (res.ok) {
				apiKeysMessage = `Saved ${data.saved_count ?? Object.keys(payload).length} key(s) successfully.`;
				apiKeysStatus = data.keys ?? apiKeysStatus;
				// OLD CODE START — review L1: also wiped a value typed while the save ran
				// // Clear input fields after successful save
				// apiKeyValues = {};
				// OLD CODE END
				// Clear the fields that were saved; one changed during the save keeps its value
				apiKeyValues = Object.fromEntries(Object.entries(apiKeyValues).filter(([key, value]) => value.trim() !== (payload[key] ?? '')));
			} else {
				apiKeysMessage = data.error || 'Failed to save API keys.';
				apiKeysError = true;
			}
		} catch {
			apiKeysMessage = 'Failed to connect to server.';
			apiKeysError = true;
		} finally {
			apiKeysSaving = false;
		}
	}

	onMount(() => {
		loadApiKeys();
	});
</script>

{#snippet configured(set: boolean | undefined)}
	{#if set}<span class="chip is-ok"><Icon name="check" />Configured</span>{/if}
{/snippet}

<div class="grid">
	<Card title="API keys and credentials" sub="Stored on this NetTap · never shown after saving" class="c-12">
		{#if apiKeysLoading}
			<CardState state="loading" title="Loading API key status" />
		{:else}
			<div class="stack">
				<p class="field-help">
					Configure external service credentials. Keys are stored securely on disk and never displayed after saving.
					Fields marked "Configured" already have a value saved: leave the input blank to keep the existing value.
				</p>
				<Feedback message={apiKeysMessage} isError={apiKeysError} />

				<section class="key-group" aria-labelledby="keys-geoip">
					<h3 class="eyebrow" id="keys-geoip">GeoIP lookups</h3>
					<div class="form-grid">
						<div class="field">
							<div class="label-row"><label class="label" for="maxmind-key">MaxMind licence key</label>{@render configured(apiKeysStatus['MAXMIND_LICENSE_KEY'])}</div>
							<input
								class="input mono"
								id="maxmind-key"
								type="password"
								bind:value={apiKeyValues['MAXMIND_LICENSE_KEY']}
								placeholder={apiKeysStatus['MAXMIND_LICENSE_KEY'] ? 'Leave blank to keep current value' : 'Enter MaxMind licence key'}
							/>
							<p class="field-help">Required for GeoIP map visualisations. Get a free key at <a class="link" href="https://www.maxmind.com/en/geolite2/signup" target="_blank" rel="noopener">maxmind.com</a>.</p>
						</div>
					</div>
				</section>

				<section class="key-group" aria-labelledby="keys-ids">
					<h3 class="eyebrow" id="keys-ids">IDS rules</h3>
					<!-- OLD CODE START — NET-191 slice 2: this key was saved to the daemon's env file and never reached Suricata.
					     The ET Pro code has one place now, Settings › Suricata rules.
					<div class="form-grid">
						<div class="field">
							<div class="label-row"><label class="label" for="et-pro-key">Emerging Threats Pro key</label>{@render configured(apiKeysStatus['SURICATA_ET_PRO_KEY'])}</div>
							<input
								class="input mono"
								id="et-pro-key"
								type="password"
								bind:value={apiKeyValues['SURICATA_ET_PRO_KEY']}
								placeholder={apiKeysStatus['SURICATA_ET_PRO_KEY'] ? 'Leave blank to keep current value' : 'Enter ET Pro key (optional)'}
							/>
							<p class="field-help">Optional. Enables Proofpoint's commercial Suricata ruleset. Free ET Open rules are used by default.</p>
						</div>
					</div>
					OLD CODE END -->
					<!-- OLD CODE: <a class="link" href="/settings/suricata-rules">Settings › Suricata rules</a> (NET-273: a tab of this page now) -->
					<p class="field-help">
						The optional Emerging Threats Pro code is set in <a class="link" href="?tab=suricata-rules">Settings › Suricata rules</a>,
						which checks it with Proofpoint before Suricata uses it.
					</p>
				</section>

				<section class="key-group" aria-labelledby="keys-smtp">
					<h3 class="eyebrow" id="keys-smtp">SMTP (email alerts)</h3>
					<p class="field-help">Required for email notifications. Configure your SMTP server details below, then enable email alerts in the Notifications tab.</p>
					<div class="form-grid">
						<div class="field">
							<div class="label-row"><label class="label" for="smtp-host">SMTP host</label>{@render configured(apiKeysStatus['SMTP_HOST'])}</div>
							<input class="input mono" id="smtp-host" type="text" bind:value={apiKeyValues['SMTP_HOST']} placeholder={apiKeysStatus['SMTP_HOST'] ? 'Leave blank to keep current' : 'smtp.gmail.com'} />
							<p class="field-help">SMTP server hostname.</p>
						</div>
						<div class="field">
							<div class="label-row"><label class="label" for="smtp-port">SMTP port</label>{@render configured(apiKeysStatus['SMTP_PORT'])}</div>
							<input class="input mono" id="smtp-port" type="text" bind:value={apiKeyValues['SMTP_PORT']} placeholder={apiKeysStatus['SMTP_PORT'] ? 'Leave blank to keep current' : '587'} />
							<p class="field-help">587 for STARTTLS, 465 for SSL/TLS.</p>
						</div>
						<div class="field">
							<div class="label-row"><label class="label" for="smtp-username">SMTP username</label>{@render configured(apiKeysStatus['SMTP_USERNAME'])}</div>
							<input class="input" id="smtp-username" type="text" bind:value={apiKeyValues['SMTP_USERNAME']} placeholder={apiKeysStatus['SMTP_USERNAME'] ? 'Leave blank to keep current' : 'user@example.com'} />
							<p class="field-help">Your SMTP login username or email.</p>
						</div>
						<div class="field">
							<div class="label-row"><label class="label" for="smtp-password">SMTP password</label>{@render configured(apiKeysStatus['SMTP_PASSWORD'])}</div>
							<input class="input" id="smtp-password" type="password" bind:value={apiKeyValues['SMTP_PASSWORD']} placeholder={apiKeysStatus['SMTP_PASSWORD'] ? 'Leave blank to keep current' : 'App password or SMTP password'} />
							<p class="field-help">For Gmail, use an App Password (not your account password).</p>
						</div>
						<div class="field">
							<div class="label-row"><label class="label" for="smtp-sender">Sender email</label>{@render configured(apiKeysStatus['SMTP_SENDER_EMAIL'])}</div>
							<input class="input" id="smtp-sender" type="email" bind:value={apiKeyValues['SMTP_SENDER_EMAIL']} placeholder={apiKeysStatus['SMTP_SENDER_EMAIL'] ? 'Leave blank to keep current' : 'nettap@example.com'} />
							<p class="field-help">The "From" address on alert emails.</p>
						</div>
					</div>
				</section>

				<!-- OLD CODE START — NET-224: nothing read this URL; the Notifications tab sets the webhook the daemon uses
				<section class="key-group" aria-labelledby="keys-webhook">
					<h3 class="eyebrow" id="keys-webhook">Webhook</h3>
					<div class="form-grid">
						<div class="field">
							<div class="label-row"><label class="label" for="webhook-url-keys">Webhook URL</label>{@render configured(apiKeysStatus['WEBHOOK_URL'])}</div>
							<input
								class="input mono"
								id="webhook-url-keys"
								type="url"
								bind:value={apiKeyValues['WEBHOOK_URL']}
								placeholder={apiKeysStatus['WEBHOOK_URL'] ? 'Leave blank to keep current' : 'https://hooks.slack.com/services/…'}
							/>
							<p class="field-help">Also configurable in the Notifications tab. JSON alert payloads are POSTed here.</p>
						</div>
					</div>
				</section>
				OLD CODE END -->

				<div class="form-actions">
					{#if apiKeysUnsaved}<span class="unsaved">Unsaved changes</span>{/if}
					<button class="btn primary" type="button" onclick={saveApiKeys} disabled={apiKeysSaving}>
						{apiKeysSaving ? 'Saving…' : 'Save API keys'}
					</button>
				</div>
			</div>
		{/if}
	</Card>
</div>

<style>
	.key-group {
		display: flex;
		flex-direction: column;
		gap: var(--sp-3);
		padding-top: var(--sp-4);
		border-top: 1px solid var(--line);
	}
</style>
