<!--
  Settings › Capture (NET-273: moved from the Settings page): the PCAP capture switch and file size,
  and the Live bandwidth card. Forms only, so it registers no page refresh.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchCaptureStatus, toggleCapture, updateCaptureSettings } from '$lib/api/capture';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import LiveBandwidthCard from '../LiveBandwidthCard.svelte';
	import Feedback from '../Feedback.svelte';

	interface Props {
		/** The file size differs from what was last loaded or saved. */
		dirty?: boolean;
		/** A switch change or a save is running. */
		busy?: boolean;
	}

	let { dirty = $bindable(false), busy = $bindable(false) }: Props = $props();

	// --- Capture state ---
	let captureEnabled = $state(true);
	let captureMaxFileSize = $state(100);
	let captureRotateMinutes = $state<number | null>(null);
	let captureContainerRunning = $state(false);
	let captureContainerStatus = $state('unknown');
	let captureLoading = $state(true);
	let captureLoadFailed = $state(false);
	let captureToggling = $state(false);
	let captureSaving = $state(false);
	let captureMessage = $state('');
	let captureError = $state(false);
	// NET-273: the size as last loaded or saved, so the page can guard an unsaved edit
	let captureSavedSize = $state<number | null>(null);
	const captureUnsaved = $derived(captureSavedSize !== null && captureMaxFileSize !== captureSavedSize);
	let liveBandwidthBusy = $state(false);

	$effect(() => {
		dirty = captureUnsaved;
		busy = captureToggling || captureSaving || liveBandwidthBusy;
	});

	// --- Capture functions ---
	async function loadCaptureSettings() {
		captureLoading = true;
		try {
			const status = await fetchCaptureStatus();
			captureLoadFailed = false;
			captureEnabled = status.enabled;
			captureMaxFileSize = status.maxFileSizeMB;
			captureSavedSize = status.maxFileSizeMB;
			captureRotateMinutes = status.rotateMinutes ?? null;
			captureContainerRunning = status.containerRunning;
			captureContainerStatus = status.containerStatus;
		} catch {
			captureLoadFailed = true;
		} finally {
			captureLoading = false;
		}
	}

	async function handleCaptureToggle() {
		captureToggling = true;
		captureMessage = '';
		captureError = false;
		try {
			const result = await toggleCapture(!captureEnabled);
			captureEnabled = result.enabled;
			captureContainerRunning = result.containerRunning;
			captureContainerStatus = result.containerStatus;
			captureMessage = captureEnabled ? 'PCAP capture enabled' : 'PCAP capture disabled';
		} catch (err) {
			captureError = true;
			captureMessage = err instanceof Error ? err.message : 'Toggle failed';
		} finally {
			captureToggling = false;
		}
	}

	async function saveCaptureSettings() {
		captureSaving = true;
		captureMessage = '';
		captureError = false;
		try {
			const result = await updateCaptureSettings({ maxFileSizeMB: captureMaxFileSize });
			captureMaxFileSize = result.maxFileSizeMB;
			captureSavedSize = result.maxFileSizeMB;
			// OLD CODE START — 2026-11-06 (NET-166): netsniff-ng counts this setting in MiB, not MB
			// captureMessage = result.restarted
			// 	? `File size updated to ${result.maxFileSizeMB} MB. Container restarted.`
			// 	: `File size updated to ${result.maxFileSizeMB} MB.`;
			// OLD CODE END
			captureMessage = result.restarted
				? `File size updated to ${result.maxFileSizeMB} MiB. Container restarted.`
				: `File size updated to ${result.maxFileSizeMB} MiB.`;
		} catch (err) {
			captureError = true;
			captureMessage = err instanceof Error ? err.message : 'Save failed';
		} finally {
			captureSaving = false;
		}
	}

	onMount(() => {
		loadCaptureSettings();
	});
</script>

<div class="grid">
	<!-- OLD CODE: sub="Packet capture container · file size in MB" (NET-166: netsniff-ng counts MiB) -->
	<Card title="PCAP capture" sub="Packet capture container · file size in MiB" class="c-12">
		{#if captureLoading}
			<CardState state="loading" title="Loading capture settings" />
		{:else if captureLoadFailed}
			<CardState state="error" title="Could not load the current capture settings, so changes are off." message="Reload the page to try again." />
		{:else}
			<div class="stack">
				<Feedback message={captureMessage} isError={captureError} />
				<dl class="facts flush">
					<dt>Container status</dt>
					<dd>
						{#if captureContainerRunning}
							<span class="chip is-ok"><Icon name="check" />Running</span>
						{:else}
							<span class="chip">{captureContainerStatus}</span>
						{/if}
					</dd>
				</dl>

				<div class="switch-row">
					<!-- the API decides the state: the click is cancelled and the switch follows the answer -->
					<input
						type="checkbox"
						role="switch"
						class="switch"
						id="capture-toggle"
						checked={captureEnabled}
						disabled={captureToggling}
						aria-describedby="capture-toggle-help"
						onclick={(e) => {
							e.preventDefault();
							handleCaptureToggle();
						}}
					/>
					<div>
						<label class="label" for="capture-toggle">PCAP collection</label>
						<!-- OLD CODE START — claimed "capturing packets" even with the container stopped
						<span class="capture-toggle-label">{captureEnabled ? 'Enabled — capturing packets' : 'Disabled — no new captures'}</span>
						OLD CODE END -->
						<p class="state-line">
							{#if !captureEnabled}
								Disabled — no new captures
							{:else if captureContainerRunning}
								Enabled — capturing packets
							{:else if captureContainerStatus === 'unknown'}
								Enabled — capture status unknown
							{:else}
								Enabled — capture container not running
							{/if}
						</p>
						<p class="field-help" id="capture-toggle-help">When disabled, the capture container is stopped. Existing PCAP files remain accessible.</p>
					</div>
				</div>

				<div class="form-grid">
					<div class="field">
						<label class="label" for="max-file-size">Max file size</label>
						<div class="unit-field">
							<input class="input" id="max-file-size" type="number" bind:value={captureMaxFileSize} min={10} max={10000} />
							<!-- OLD CODE: <span class="dim">MB</span> (NET-166: netsniff-ng's PCAP_ROTATE_MB counts mebibytes) -->
							<span class="dim">MiB</span>
						</div>
						<!-- OLD CODE START — 2026-11-02: the 100 MB default was never what netsniff used
						<p class="field-help">Individual PCAP files rotate at this size. Default: 100 MB. Range: 10–10,000 MB.</p>
						OLD CODE END -->
						<!-- OLD CODE START — 2026-11-06 (NET-166): said MB, but netsniff-ng counts MiB
						<p class="field-help">
							A new file starts at this size{captureRotateMinutes ? ` or every ${captureRotateMinutes} minutes, whichever comes first` : ''}. Range: 10–10,000 MB.
						</p>
						OLD CODE END -->
						<p class="field-help">
							A new file starts at this size{captureRotateMinutes ? ` or every ${captureRotateMinutes} minutes, whichever comes first` : ''}. Range: 10–10,000 MiB.
							1 MiB is 1,048,576 bytes, so a 256 MiB file shows as 268.4 MB on the PCAP page.
						</p>
					</div>
				</div>

				<div class="form-actions">
					{#if captureUnsaved}<span class="unsaved">Unsaved changes</span>{/if}
					<button class="btn primary" type="button" onclick={saveCaptureSettings} disabled={captureSaving}>
						{captureSaving ? 'Saving…' : 'Save capture settings'}
					</button>
				</div>
			</div>
		{/if}
	</Card>
	<LiveBandwidthCard bind:busy={liveBandwidthBusy} />
</div>

<style>
	.state-line {
		font-size: var(--text-sm);
		color: var(--text-2);
	}
</style>
