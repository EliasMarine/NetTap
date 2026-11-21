<!--
  Settings › Backup & restore (NET-273: was /settings/backup, moved whole). Forms only, so it registers
  no page refresh. `busy` holds a tab switch while a restore runs, so the next tab reads restored values.
-->
<script lang="ts">
	import {
		// OLD CODE: exportConfig, (NET-344: no caller left; downloadConfigFile saves the daemon's exact bytes)
		downloadConfigFile,
		validateConfig,
		importConfig,
		readConfigFile,
		restoreBody,
	} from '$lib/api/backup';
	import type { ValidationResult, ImportResult } from '$lib/api/backup';
	import Card from '$lib/components/ui/Card.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { formatTime } from '$lib/utils/time';
	import { refreshCaptureMode } from '$lib/stores/captureMode';

	/** NET-273: true while a restore runs. */
	let { busy = $bindable(false) }: { busy?: boolean } = $props();

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	// Export
	let exporting = $state(false);
	let exportMessage = $state('');
	let exportError = $state(false);
	// NET-344: the download note says the backup left out old acknowledgements
	let exportLeftOut = $state(false);
	let lastExportDate = $state<string | null>(null);

	// Import
	let importFile = $state<File | null>(null);
	let importing = $state(false);
	let validating = $state(false);
	let validation = $state<ValidationResult | null>(null);
	let importResult = $state<ImportResult | null>(null);
	let importError = $state('');
	// OLD CODE: let importData = $state<unknown>(null); (NET-344: Apply sends the exact body that was validated)
	/** The body whose validation finished for the current selection; set together with `validation`. */
	let importBody = $state<string | null>(null);
	/** NET-344: bumped by each selection and by Remove, so a slower, older read or validation is dropped. */
	let generation = 0;
	// A9: restoring a different capture mode restarts capture, so it waits for this box
	let applyCapture = $state(false);

	$effect(() => {
		busy = importing;
	});

	/** Section names as the owner knows them */
	const SECTION_LABELS: Record<string, string> = {
		capture_mode_config: 'Capture mode',
		storage_retention: 'Retention',
		notification_channels: 'Notification channels',
		notification_rules: 'Notification rules',
		notification_quiet: 'Quiet hours',
		device_aliases: 'Device names',
		device_pictures: 'Device pictures',
		device_details: 'Device details',
		excluded_ips: 'Excluded IPs',
		bandwidth_cap: 'Bandwidth cap',
		home_location: 'Home location',
		alert_acknowledgements: 'Alert acknowledgements',
		alert_suppressions: 'Alert suppressions',
	};
	// OLD CODE: const label = (section: string) => SECTION_LABELS[section] ?? section.replace(/_/g, ' ');
	// L6: own keys only, so a daemon key such as 'constructor' never reads Object.prototype
	const label = (section: string) =>
		Object.hasOwn(SECTION_LABELS, section) ? SECTION_LABELS[section] : section.replace(/_/g, ' ');

	/** "Import successful" only when nothing was skipped or failed */
	let resultTitle = $derived.by(() => {
		if (!importResult) return '';
		const skipped = importResult.skipped?.length ?? 0;
		if (importResult.errors.length) return importResult.applied.length ? 'Partly imported' : 'Import failed';
		return skipped ? 'Imported, some sections skipped' : 'Import successful';
	});

	// Drag state
	let isDragging = $state(false);

	// ---------------------------------------------------------------------------
	// Export
	// ---------------------------------------------------------------------------

	async function handleExport() {
		exporting = true;
		exportMessage = '';
		exportError = false;
		exportLeftOut = false;

		try {
			// OLD CODE: await downloadConfigFile();
			const { leftOut } = await downloadConfigFile();
			lastExportDate = formatTime(Date.now());
			// OLD CODE: exportMessage = 'Configuration exported successfully';
			exportLeftOut = leftOut > 0;
			exportMessage = exportLeftOut
				? `Backup saved. It leaves out the ${leftOut.toLocaleString('en-GB')} oldest alert acknowledgement${leftOut === 1 ? '' : 's'} to stay under the 16 MB restore limit; after a restore those alerts show as not acknowledged.`
				: 'Configuration exported successfully';
		} catch (e) {
			exportError = true;
			exportMessage = e instanceof Error ? e.message : 'Export failed';
		} finally {
			exporting = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Import
	// ---------------------------------------------------------------------------

	async function handleFileSelect(event: Event) {
		const input = event.target as HTMLInputElement;
		if (input.files && input.files[0]) {
			await processFile(input.files[0]);
		}
	}

	async function handleDrop(event: DragEvent) {
		event.preventDefault();
		isDragging = false;

		if (event.dataTransfer?.files && event.dataTransfer.files[0]) {
			await processFile(event.dataTransfer.files[0]);
		}
	}

	function handleDragOver(event: DragEvent) {
		event.preventDefault();
		isDragging = true;
	}

	function handleDragLeave() {
		isDragging = false;
	}

	// OLD CODE START — NET-344: a slower read or validation of an earlier file could land under the new one
	// async function processFile(file: File) {
	// 	importFile = file;
	// 	importResult = null;
	// 	importError = '';
	// 	applyCapture = false;
	// 	validating = true;
	//
	// 	try {
	// 		importData = await readConfigFile(file);
	// 		validation = await validateConfig(importData);
	// 	} catch (e) {
	// 		importError = e instanceof Error ? e.message : 'Failed to read file';
	// 		validation = null;
	// 	} finally {
	// 		validating = false;
	// 	}
	// }
	// OLD CODE END
	async function processFile(file: File) {
		const current = ++generation;
		importFile = file;
		importResult = null;
		importError = '';
		applyCapture = false;
		validation = null;
		importBody = null;
		validating = true;

		try {
			const { text, data } = await readConfigFile(file);
			if (current !== generation) return;
			const body = restoreBody(text, data);
			const result = await validateConfig(body);
			if (current !== generation) return;
			validation = result;
			importBody = body;
		} catch (e) {
			if (current !== generation) return;
			importError = e instanceof Error ? e.message : 'Failed to read file';
			validation = null;
		} finally {
			if (current === generation) validating = false;
		}
	}

	async function handleImport() {
		// OLD CODE: if (!importData) return;
		if (!importBody) return;

		importing = true;
		importError = '';

		try {
			// OLD CODE: importResult = await importConfig(importData);
			// OLD CODE: importResult = await importConfig(importData, applyCapture && validation?.capture_restart === true);
			importResult = await importConfig(importBody, applyCapture && validation?.capture_restart === true);
			// review M2: the pages that word things by capture mode read it again
			if (importResult.applied?.includes('capture_mode_config')) void refreshCaptureMode();
			if (!importResult.success) {
				importError = importResult.errors.join(', ');
			}
		} catch (e) {
			importError = e instanceof Error ? e.message : 'Import failed';
		} finally {
			importing = false;
		}
	}

	function resetImport() {
		generation++;
		importFile = null;
		validation = null;
		importResult = null;
		importError = '';
		// OLD CODE: importData = null;
		importBody = null;
		validating = false;
	}
</script>

<!-- OLD CODE START — NET-273: a tab of Settings now; the page's title, heading and intro line say it
<svelte:head>
	<title>Backup and restore | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a class="back" href="/settings"><Icon name="back" />Settings</a>
		<h1 class="page-title">Backup and restore</h1>
		<p class="page-sub">Export your NetTap configuration to a file, or restore it from one</p>
	</div>
</div>
OLD CODE END -->

<div class="grid">
	<!-- OLD CODE: <Card title="Export configuration" sub="One JSON file · every NetTap setting" class="c-6"> (NET-349: the card then lists what it leaves out) -->
	<Card title="Export configuration" sub="One JSON file · the settings listed below" class="c-6">
		<!-- OLD CODE START — A9: "all NetTap settings", though it skipped capture mode and retention
		<p class="card-text">
			Download all NetTap settings as a JSON file. Includes capture mode, retention policies,
			notification channels, device aliases, excluded IPs, and bandwidth cap.
		</p>
		OLD CODE END -->
		<p class="card-text">
			<!-- OLD CODE: "…, notification channels and rules, …" (F8: quiet hours are exported too) -->
			<!-- OLD CODE: "…, device names and pictures, …" (F2: device details are exported too) -->
			Download your NetTap settings as a JSON file: capture mode, retention, notification channels,
			rules and quiet hours, device names, pictures and details, excluded IPs, bandwidth cap, home
			location, alert acknowledgements and suppressions.
		</p>
		<p class="card-text">
			Left out: passwords, API keys and tokens (the admin login, notification passwords, webhook
			URLs and tokens, UniFi, ET Pro), investigations, your own Suricata rules, report schedules,
			PCAP capture settings, and the captured traffic, logs and alerts themselves. After a restore,
			enter the notification passwords, URLs and tokens again in Settings › Notifications.
		</p>

		<div class="form-actions start">
			<button class="btn primary" type="button" onclick={handleExport} disabled={exporting}>
				<Icon name="download" />{exporting ? 'Exporting…' : 'Export configuration'}
			</button>
			{#if lastExportDate}
				<span class="dim">Last export: {lastExportDate}</span>
			{/if}
		</div>

		{#if exportMessage}
			<!-- OLD CODE START — NET-344: no warn style for a backup that left out acknowledgements
			<div class={['notice', exportError ? 'is-error' : 'is-ok']} role={exportError ? 'alert' : 'status'}>
				<Icon name={exportError ? 'warn' : 'check'} />{exportMessage}
			</div>
			OLD CODE END -->
			<div
				class={['notice', exportError ? 'is-error' : exportLeftOut ? 'is-warn' : 'is-ok']}
				role={exportError ? 'alert' : 'status'}
			>
				<Icon name={exportError || exportLeftOut ? 'warn' : 'check'} /><span>{exportMessage}</span>
			</div>
		{/if}
	</Card>

	<Card title="Import configuration" sub="A file from an earlier export · checked before it is applied" class="c-6">
		<p class="card-text">
			Upload a previously exported configuration file to restore settings.
			The file will be validated before applying.
		</p>

		{#if !importFile}
			<!-- The drop target only widens the mouse path; the file input is the keyboard path -->
			<div
				class={['dropzone', isDragging && 'dragging']}
				role="region"
				aria-label="Drop a configuration file"
				ondrop={handleDrop}
				ondragover={handleDragOver}
				ondragleave={handleDragLeave}
			>
				<span class="state-ic"><Icon name="logs" /></span>
				<p>Drag and drop a configuration file here</p>
				<p class="dim">or</p>
				<label class="btn file-label">
					Choose file
					<input type="file" accept=".json" onchange={handleFileSelect} class="sr-only" />
				</label>
			</div>
		{:else}
			<div class="selected-file">
				<span class="mono">{importFile.name}</span>
				<!-- OLD CODE: {(importFile.size / 1024).toFixed(1)} KB (NET-166: 1024-based under a decimal label) -->
				<span class="dim num">{(importFile.size / 1000).toFixed(1)} KB</span>
				<!-- OLD CODE: <button class="btn" type="button" onclick={resetImport}>Remove</button> (NET-344: a restore's result must stay under its own file) -->
				<button class="btn" type="button" onclick={resetImport} disabled={importing}>Remove</button>
			</div>

			{#if validating}
				<div class="notice" role="status">Validating configuration…</div>
			{/if}

			{#if validation}
				<div class="validation">
					<div class={['notice', validation.is_valid ? 'is-ok' : 'is-error']} role="status">
						<Icon name={validation.is_valid ? 'check' : 'warn'} />
						{validation.is_valid ? 'Valid configuration' : 'Invalid configuration'}
					</div>

					{#if validation.errors.length > 0}
						<div>
							<h3 class="eyebrow">Errors</h3>
							<ul class="issues">
								{#each validation.errors as err}
									<li>{err}</li>
								{/each}
							</ul>
						</div>
					{/if}

					{#if validation.warnings.length > 0}
						<div>
							<h3 class="eyebrow">Warnings</h3>
							<ul class="issues">
								{#each validation.warnings as warn}
									<li>{warn}</li>
								{/each}
							</ul>
						</div>
					{/if}

					{#if Object.keys(validation.preview).length > 0}
						<div>
							<h3 class="eyebrow">Sections to import</h3>
							<dl class="facts flush">
								{#each Object.entries(validation.preview) as [name, info]}
									<!-- OLD CODE: <dt>{name.replace(/_/g, ' ')}</dt> (A9: the owner's names) -->
									<dt>{label(name)}</dt>
									<dd class="num">{info.size} items</dd>
								{/each}
							</dl>
						</div>
					{/if}

					{#if validation.is_valid && validation.capture_restart}
						<label class="check-row">
							<input type="checkbox" bind:checked={applyCapture} />
							<span>
								Also restore the capture mode. This restarts the capture containers, so capture
								pauses for about a minute. Left unticked, the capture mode stays as it is.
							</span>
						</label>
					{/if}

					{#if validation.is_valid}
						<div class="form-actions">
							<!-- OLD CODE: disabled={importing} (NET-344: only the body validated for this selection is sent) -->
							<button class="btn primary" type="button" onclick={handleImport} disabled={importing || !importBody}>
								{importing ? 'Importing…' : 'Apply configuration'}
							</button>
						</div>
					{/if}
				</div>
			{/if}

			{#if importResult}
				<div
					class={['notice', importResult.success ? 'is-ok' : 'is-error']}
					role={importResult.success ? 'status' : 'alert'}
				>
					<Icon name={importResult.success ? 'check' : 'warn'} />
					<div>
						<!-- OLD CODE START — A9: "Import successful" while sections were skipped
						<b>{importResult.success ? 'Import successful' : 'Import failed'}</b>
						{#if importResult.applied.length > 0}
							<p>Applied sections: {importResult.applied.join(', ')}</p>
						{/if}
						OLD CODE END -->
						<b>{resultTitle}</b>
						{#if importResult.applied.length > 0}
							<p>Restored: {importResult.applied.map(label).join(', ')}</p>
						{/if}
						{#if importResult.skipped?.length}
							<p>Skipped:</p>
							<ul class="issues">
								{#each importResult.skipped as item (item.section)}
									<li>{label(item.section)}: {item.reason}</li>
								{/each}
							</ul>
						{/if}
						{#if importResult.errors.length > 0}
							<p>Errors: {importResult.errors.join(', ')}</p>
						{/if}
						{#if importResult.warnings.length > 0}
							<p>Warnings: {importResult.warnings.join(', ')}</p>
						{/if}
					</div>
				</div>
			{/if}

			{#if importError && !importResult}
				<div class="notice is-error" role="alert"><Icon name="warn" />{importError}</div>
			{/if}
		{/if}
	</Card>
</div>

<style>
	.card-text { color: var(--text-2); font-size: var(--text-sm); line-height: 1.5; margin-bottom: var(--sp-4); }
	.form-actions.start { justify-content: flex-start; align-items: center; margin: 0 0 var(--sp-4); }
	.dropzone {
		display: flex; flex-direction: column; align-items: center; gap: var(--sp-2); text-align: center;
		padding: var(--sp-6) var(--sp-4); border: 1px dashed var(--line-strong); border-radius: var(--r-md);
		background: var(--surface-1); color: var(--text-2); font-size: var(--text-sm);
		transition: background var(--dur-fast);
	}
	.dropzone.dragging { background: var(--surface-2); border-color: var(--accent); }
	.file-label { cursor: pointer; }
	.file-label:focus-within { outline: 2px solid var(--focus); outline-offset: 2px; }
	.selected-file { display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap; margin-bottom: var(--sp-4); font-size: var(--text-sm); }
	.selected-file .btn { margin-left: auto; }
	.validation { display: flex; flex-direction: column; gap: var(--sp-4); margin-bottom: var(--sp-4); }
	.issues { margin: var(--sp-2) 0 0; padding-left: var(--sp-5); font-size: var(--text-sm); color: var(--text-2); }
	.facts.flush { border-top: 0; padding-top: 0; margin-top: var(--sp-2); }
	.facts dt { text-transform: capitalize; }
	.notice p { margin-top: var(--sp-1); }
</style>
