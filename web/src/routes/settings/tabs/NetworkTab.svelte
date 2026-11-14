<!--
  Settings › Network (NET-273: moved from the Settings page): the network location for the Live
  globe, and the IPs left out of device views. Forms only, so it registers no page refresh.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import LocationCard from '../LocationCard.svelte';
	import Feedback from '../Feedback.svelte';

	interface Props {
		/** The excluded list or the location differs from what was last loaded or saved. */
		dirty?: boolean;
		/** A save is running. */
		busy?: boolean;
	}

	let { dirty = $bindable(false), busy = $bindable(false) }: Props = $props();

	// --- Network state (excluded IPs) ---
	let excludedIps = $state<string[]>([]);
	/** NetTap's own IP: excluded automatically, so it's not the owner's to edit or save */
	let applianceIp = $state<string | null>(null);
	let newExcludedIp = $state('');
	let networkSaving = $state(false);
	let networkMessage = $state('');
	let networkError = $state(false);
	let networkLoading = $state(true);
	let networkLoadFailed = $state(false);
	// NET-273: the list as last loaded or saved, so the page can guard an unsaved edit
	let excludedSaved = $state<string | null>(null);
	const excludedUnsaved = $derived(excludedSaved !== null && JSON.stringify(excludedIps) !== excludedSaved);
	let locationDirty = $state(false);
	let locationWriting = $state(false);

	$effect(() => {
		dirty = excludedUnsaved || locationDirty;
		busy = networkSaving || locationWriting;
	});

	async function loadExcludedIps() {
		networkLoading = true;
		try {
			const res = await fetch('/api/settings/excluded-ips');
			if (res.ok) {
				const data = await res.json();
				// OLD CODE: excludedIps = data.excluded_ips ?? []; (a save then stored NetTap's own
				// IP, which outlived an address change and hid whichever device got it next, #79)
				applianceIp = data.appliance_ip ?? null;
				excludedIps = (data.excluded_ips ?? []).filter((ip: string) => ip !== applianceIp);
				excludedSaved = JSON.stringify(excludedIps);
				networkLoadFailed = false;
				return;
			}
			networkLoadFailed = true;
		} catch {
			networkLoadFailed = true;
		} finally {
			networkLoading = false;
		}
	}

	async function saveExcludedIps() {
		networkSaving = true;
		networkMessage = '';
		networkError = false;
		try {
			const res = await fetch('/api/settings/excluded-ips', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ excluded_ips: excludedIps }),
			});
			if (res.ok) {
				excludedSaved = JSON.stringify(excludedIps);
				networkMessage = 'Excluded IPs saved. Changes take effect immediately.';
			} else {
				const data = await res.json();
				networkMessage = data.error || 'Failed to save excluded IPs.';
				networkError = true;
			}
		} catch {
			networkMessage = 'Failed to connect to server.';
			networkError = true;
		} finally {
			networkSaving = false;
		}
	}

	function addExcludedIp() {
		const ip = newExcludedIp.trim();
		if (!ip) return;
		// Basic IP format validation
		if (!/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(ip)) {
			networkMessage = 'Please enter a valid IPv4 address.';
			networkError = true;
			return;
		}
		if (excludedIps.includes(ip)) {
			networkMessage = `${ip} is already in the exclusion list.`;
			networkError = true;
			return;
		}
		excludedIps = [...excludedIps, ip];
		newExcludedIp = '';
		networkMessage = '';
	}

	function removeExcludedIp(ip: string) {
		excludedIps = excludedIps.filter((i) => i !== ip);
	}

	onMount(() => {
		loadExcludedIps();
	});
</script>

<div class="grid">
	<LocationCard bind:dirty={locationDirty} bind:writing={locationWriting} />
	<Card title="Excluded IPs" sub="Hidden from device views · still in logs, alerts and connections" class="c-12">
		{#if networkLoading}
			<CardState state="loading" title="Loading the excluded IP list" />
		{:else if networkLoadFailed}
			<CardState state="error" title="Could not load the excluded IP list, so changes are off." message="Reload the page to try again." />
		{:else}
			<div class="stack">
				<p class="field-help">
					IPs in this list are hidden from device-centric views (Devices, Top Talkers, Risk Scores) but remain visible in Log Explorer, Alerts, and raw connection data.
					Useful for filtering out your ISP gateway's public IP or infrastructure addresses that appear on every connection.
				</p>
				<Feedback message={networkMessage} isError={networkError} />

				<div class="field">
					<label class="label" for="excluded-ip-new">IP address to exclude</label>
					<div class="inline-row">
						<input
							class="input mono"
							id="excluded-ip-new"
							type="text"
							bind:value={newExcludedIp}
							placeholder="e.g. 203.0.113.10"
							onkeydown={(e) => {
								if (e.key === 'Enter') addExcludedIp();
							}}
						/>
						<button class="btn" type="button" onclick={addExcludedIp}>Add</button>
					</div>
				</div>

				{#if applianceIp}
					<p class="dim">NetTap's own address, <span class="mono">{applianceIp}</span>, is always left out and isn't listed here.</p>
				{/if}
				{#if excludedIps.length === 0}
					<p class="dim">No IPs excluded. All IPs appear in device views.</p>
				{:else}
					<ul class="ip-list" aria-label="Excluded IPs">
						{#each excludedIps as ip (ip)}
							<li>
								<span class="mono">{ip}</span>
								<button class="icon-btn ghost" type="button" aria-label="Remove {ip}" onclick={() => removeExcludedIp(ip)}><Icon name="close" /></button>
							</li>
						{/each}
					</ul>
				{/if}

				<div class="form-actions">
					{#if excludedUnsaved}<span class="unsaved">Unsaved changes</span>{/if}
					<button class="btn primary" type="button" onclick={saveExcludedIps} disabled={networkSaving}>
						{networkSaving ? 'Saving…' : 'Save excluded IPs'}
					</button>
				</div>
			</div>
		{/if}
	</Card>
</div>

<style>
	.ip-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-wrap: wrap;
		gap: var(--sp-2);
	}

	.ip-list li {
		display: inline-flex;
		align-items: center;
		gap: var(--sp-1);
		padding-left: var(--sp-3);
		border-radius: var(--r-pill);
		background: var(--surface-2);
		border: 1px solid var(--line);
		font-size: var(--text-sm);
	}
</style>
