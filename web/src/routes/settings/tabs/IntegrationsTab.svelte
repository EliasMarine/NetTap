<!--
  Settings › Integrations (NET-273: moved from the Settings page): the UniFi controller. Its status
  loads with its form, so it registers no page refresh (a Refresh would replace what is typed).
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { getUnifiStatus } from '$lib/api/unifi';
	import { loadFailed } from '$lib/utils/load-failed';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import StatStrip from '$lib/components/ui/StatStrip.svelte';
	import Feedback from '../Feedback.svelte';

	interface Props {
		/** The form differs from what was last loaded or saved, or an API key is typed. */
		dirty?: boolean;
		/** A save or a connection test is running. */
		busy?: boolean;
	}

	let { dirty = $bindable(false), busy = $bindable(false) }: Props = $props();

	// --- UniFi Integration state ---
	let unifiControllerUrl = $state('');
	let unifiApiKey = $state('');
	let unifiSiteId = $state('');
	let unifiSites = $state<{ id: string; name?: string; desc?: string }[]>([]);
	let unifiConfigured = $state(false);
	let unifiConnected = $state(false);
	let unifiCacheCounts = $state<{ clients: number; devices: number } | null>(null);
	let unifiLastPoll = $state<string | null>(null);
	let unifiLoading = $state(true);
	// #96: a failed status read used to show the form as "not configured"
	let unifiStatusFailed = $state(false);
	let unifiSaving = $state(false);
	let unifiTesting = $state(false);
	let unifiMessage = $state('');
	let unifiError = $state(false);
	let unifiSitesLoading = $state(false);
	// NET-273: the form as last loaded or saved, so the page can guard an unsaved edit
	const unifiForm = () => JSON.stringify([unifiControllerUrl.trim(), unifiSiteId.trim()]);
	let unifiSavedForm = $state<string | null>(null);
	const unifiUnsaved = $derived(unifiSavedForm !== null && (unifiForm() !== unifiSavedForm || unifiApiKey.trim() !== ''));

	$effect(() => {
		dirty = unifiUnsaved;
		busy = unifiSaving || unifiTesting;
	});

	// --- UniFi functions ---
	// OLD CODE START — read `last_poll`, which the daemon never sends (it sends
	// `last_poll_time` in epoch seconds), so "Last Poll" never showed
	// async function loadUnifiStatus() {
	// 	unifiLoading = true;
	// 	try {
	// 		const res = await fetch('/api/integrations/unifi/status');
	// 		if (res.ok) {
	// 			const data = await res.json();
	// 			unifiConfigured = data.configured ?? false;
	// 			unifiControllerUrl = data.controller_url ?? '';
	// 			unifiConnected = data.connected ?? false;
	// 			unifiCacheCounts = data.cache_counts ?? null;
	// 			unifiLastPoll = data.last_poll ?? null;
	// 			if (data.site_id) unifiSiteId = data.site_id;
	// 		}
	// 	} catch {
	// 		// Will use defaults
	// 	} finally {
	// 		unifiLoading = false;
	// 	}
	// }
	// OLD CODE END
	function unifiPollIso(epochSeconds: unknown): string | null {
		return typeof epochSeconds === 'number' && epochSeconds > 0
			? new Date(epochSeconds * 1000).toISOString()
			: null;
	}

	async function loadUnifiStatus() {
		unifiLoading = true;
		try {
			const status = await getUnifiStatus();
			unifiConfigured = status.configured;
			unifiControllerUrl = status.controller_url ?? '';
			unifiConnected = status.connected;
			unifiCacheCounts = status.configured
				? { clients: status.cache_counts.clients ?? 0, devices: status.cache_counts.devices ?? 0 }
				: null;
			unifiLastPoll = unifiPollIso(status.last_poll_time);
			if (status.site_id) unifiSiteId = status.site_id;
			unifiStatusFailed = false;
		} catch {
			unifiStatusFailed = true;
		} finally {
			unifiSavedForm = unifiForm();
			unifiLoading = false;
		}
	}

	async function loadUnifiSites() {
		unifiSitesLoading = true;
		try {
			const res = await fetch('/api/integrations/unifi/sites');
			if (res.ok) {
				const data = await res.json();
				unifiSites = data.sites ?? [];
			}
		} catch {
			// Sites will remain empty
		} finally {
			unifiSitesLoading = false;
		}
	}

	async function saveUnifiConfig() {
		unifiSaving = true;
		unifiMessage = '';
		unifiError = false;

		if (!unifiControllerUrl.trim()) {
			unifiMessage = 'Controller URL is required.';
			unifiError = true;
			unifiSaving = false;
			return;
		}
		if (!unifiApiKey.trim() && !unifiConfigured) {
			unifiMessage = 'API Key is required.';
			unifiError = true;
			unifiSaving = false;
			return;
		}

		try {
			const payload: Record<string, string> = {
				controller_url: unifiControllerUrl.trim(),
			};
			// Only send api_key if user entered one (leave blank to keep existing)
			if (unifiApiKey.trim()) {
				payload.api_key = unifiApiKey.trim();
			}
			// OLD CODE START — a whitespace-only site id was posted as-is
			// if (unifiSiteId) {
			// 	payload.site_id = unifiSiteId;
			// }
			// OLD CODE END
			// Omit site_id when blank so the daemon keeps the saved site
			const siteId = unifiSiteId.trim();
			if (siteId) {
				payload.site_id = siteId;
			}

			// The form as sent: an edit typed while the save runs stays unsaved (review L1)
			const sent = unifiForm();
			const sentKey = unifiApiKey;
			const res = await fetch('/api/integrations/unifi/configure', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload),
			});
			const data = await res.json();
			if (res.ok) {
				unifiMessage = 'UniFi configuration saved successfully.';
				unifiConfigured = true;
				// OLD CODE START — review L1: cleared a key typed during the save, and counted every edit as saved
				// unifiApiKey = ''; // Clear after save
				// unifiSavedForm = unifiForm();
				// OLD CODE END
				if (unifiApiKey === sentKey) unifiApiKey = ''; // Clear after save
				unifiSavedForm = sent;
				// Now test the connection
				await testUnifiConnection();
			} else {
				unifiMessage = data.error || 'Failed to save UniFi configuration.';
				unifiError = true;
			}
		} catch {
			unifiMessage = 'Failed to connect to server.';
			unifiError = true;
		} finally {
			unifiSaving = false;
		}
	}

	async function testUnifiConnection() {
		unifiTesting = true;
		unifiMessage = '';
		unifiError = false;

		try {
			const res = await fetch('/api/integrations/unifi/test', { method: 'POST' });
			const data = await res.json();
			if (res.ok && data.success) {
				unifiConnected = true;
				unifiMessage = 'Connection successful.';
				if (data.status?.cache_counts) {
					unifiCacheCounts = data.status.cache_counts;
				}
				// OLD CODE START — `last_poll` is not a daemon field
				// if (data.status?.last_poll) {
				// 	unifiLastPoll = data.status.last_poll;
				// }
				// OLD CODE END
				unifiLastPoll = unifiPollIso(data.status?.last_poll_time) ?? unifiLastPoll;
				// Fetch available sites
				await loadUnifiSites();
			} else {
				unifiConnected = false;
				unifiMessage = data.error || data.message || 'Connection test failed.';
				unifiError = true;
			}
		} catch {
			unifiConnected = false;
			unifiMessage = 'Failed to connect to server.';
			unifiError = true;
		} finally {
			unifiTesting = false;
		}
	}

	function formatUnifiPollTime(isoString: string): string {
		const diff = Date.now() - new Date(isoString).getTime();
		const secs = Math.floor(diff / 1000);
		if (secs < 60) return `${secs}s ago`;
		const mins = Math.floor(secs / 60);
		if (mins < 60) return `${mins}m ago`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h ago`;
		return `${Math.floor(hours / 24)}d ago`;
	}

	onMount(() => {
		loadUnifiStatus();
	});
</script>

{#snippet configured(set: boolean | undefined)}
	{#if set}<span class="chip is-ok"><Icon name="check" />Configured</span>{/if}
{/snippet}

<div class="grid">
	<Card title="UniFi controller" sub="Device names, models and networks from UniFi · API key sign-in" class="c-12">
		{#snippet actions()}
			{#if unifiConfigured}
				<span class={['chip', unifiConnected ? 'is-ok' : 'is-bad']}>
					<Icon name={unifiConnected ? 'check' : 'warn'} />{unifiConnected ? 'Connected' : 'Disconnected'}
				</span>
			{/if}
		{/snippet}
		{#if unifiLoading}
			<CardState state="loading" title="Loading UniFi status" />
		{:else}
			<div class="stack">
				<p class="field-help">
					Connect to your UniFi controller to enrich device data with friendly names, models, and network assignments. Uses API key authentication (UniFi OS 10.2.93+).
				</p>
				<Feedback message={unifiMessage} isError={unifiError} />
				{#if unifiStatusFailed}
					<div class="notice is-warn" role="status"><Icon name="warn" />{loadFailed('the UniFi status')} The controller may already be set up.</div>
				{/if}

				{#if unifiConfigured && (unifiCacheCounts || unifiLastPoll)}
					<StatStrip
						stats={[
							...(unifiCacheCounts
								? [
										{ key: 'clients', label: 'Cached clients', value: String(unifiCacheCounts.clients) },
										{ key: 'devices', label: 'Cached devices', value: String(unifiCacheCounts.devices) },
									]
								: []),
							...(unifiLastPoll ? [{ key: 'poll', label: 'Last poll', value: formatUnifiPollTime(unifiLastPoll) }] : []),
						]}
					/>
				{/if}

				<div class="form-grid">
					<div class="field">
						<label class="label" for="unifi-url">Controller URL</label>
						<input class="input mono" id="unifi-url" type="url" bind:value={unifiControllerUrl} placeholder="https://192.168.1.1" />
						<p class="field-help">Full URL to your UniFi controller (e.g. https://192.168.1.1 or https://unifi.local:8443).</p>
					</div>

					<div class="field">
						<div class="label-row"><label class="label" for="unifi-api-key">API key</label>{@render configured(unifiConfigured)}</div>
						<input
							class="input mono"
							id="unifi-api-key"
							type="password"
							bind:value={unifiApiKey}
							placeholder={unifiConfigured ? 'Leave blank to keep current key' : 'Paste your UniFi API key'}
							autocomplete="off"
							spellcheck="false"
						/>
						<p class="field-help">
							Generate an API key in UniFi OS: Settings · System · Advanced · API Key.
							{#if unifiConfigured}
								Leave blank to keep the currently saved key.
							{/if}
						</p>
					</div>

					<div class="field">
						<label class="label" for="unifi-site">Site</label>
						{#if unifiSites.length > 0}
							<select class="select" id="unifi-site" bind:value={unifiSiteId}>
								<option value="">Select a site…</option>
								{#each unifiSites as site (site.id)}
									<option value={site.id}>{site.desc || site.name || site.id}</option>
								{/each}
							</select>
							<p class="field-help">Select which UniFi site to poll for device data.</p>
						{:else if unifiSitesLoading}
							<p class="field-help">Loading sites…</p>
						{:else}
							<input class="input mono" id="unifi-site" type="text" bind:value={unifiSiteId} placeholder="default" />
							<p class="field-help">Enter a site ID manually, or save and test the connection to auto-discover sites. Most setups use "default".</p>
						{/if}
					</div>
				</div>

				<div class="form-actions">
					{#if unifiUnsaved}<span class="unsaved">Unsaved changes</span>{/if}
					{#if unifiConfigured}
						<button class="btn" type="button" onclick={testUnifiConnection} disabled={unifiTesting || unifiSaving}>
							{unifiTesting ? 'Testing…' : 'Test connection'}
						</button>
					{/if}
					<button class="btn primary" type="button" onclick={saveUnifiConfig} disabled={unifiSaving || unifiTesting}>
						{unifiSaving ? 'Saving…' : 'Save configuration'}
					</button>
				</div>
			</div>
		{/if}
	</Card>
</div>
