<script lang="ts">
	import {
		exportConfig,
		downloadConfigFile,
		validateConfig,
		importConfig,
		readConfigFile,
	} from '$lib/api/backup';
	import type { ValidationResult, ImportResult } from '$lib/api/backup';
	import Card from '$lib/components/ui/Card.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	// Export
	let exporting = $state(false);
	let exportMessage = $state('');
	let exportError = $state(false);
	let lastExportDate = $state<string | null>(null);

	// Import
	let importFile = $state<File | null>(null);
	let importing = $state(false);
	let validating = $state(false);
	let validation = $state<ValidationResult | null>(null);
	let importResult = $state<ImportResult | null>(null);
	let importError = $state('');
	let importData = $state<unknown>(null);

	// Drag state
	let isDragging = $state(false);

	// ---------------------------------------------------------------------------
	// Export
	// ---------------------------------------------------------------------------

	async function handleExport() {
		exporting = true;
		exportMessage = '';
		exportError = false;

		try {
			await downloadConfigFile();
			lastExportDate = new Date().toLocaleString();
			exportMessage = 'Configuration exported successfully';
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

	async function processFile(file: File) {
		importFile = file;
		importResult = null;
		importError = '';
		validating = true;

		try {
			importData = await readConfigFile(file);
			validation = await validateConfig(importData);
		} catch (e) {
			importError = e instanceof Error ? e.message : 'Failed to read file';
			validation = null;
		} finally {
			validating = false;
		}
	}

	async function handleImport() {
		if (!importData) return;

		importing = true;
		importError = '';

		try {
			importResult = await importConfig(importData);
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
		importFile = null;
		validation = null;
		importResult = null;
		importError = '';
		importData = null;
	}
</script>

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

<div class="grid">
	<Card title="Export configuration" sub="One JSON file · every NetTap setting" class="c-6">
		<p class="card-text">
			Download all NetTap settings as a JSON file. Includes capture mode, retention policies,
			notification channels, device aliases, excluded IPs, and bandwidth cap.
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
			<div class={['notice', exportError ? 'is-error' : 'is-ok']} role={exportError ? 'alert' : 'status'}>
				<Icon name={exportError ? 'warn' : 'check'} />{exportMessage}
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
				<span class="dim num">{(importFile.size / 1024).toFixed(1)} KB</span>
				<button class="btn" type="button" onclick={resetImport}>Remove</button>
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
									<dt>{name.replace(/_/g, ' ')}</dt>
									<dd class="num">{info.size} items</dd>
								{/each}
							</dl>
						</div>
					{/if}

					{#if validation.is_valid}
						<div class="form-actions">
							<button class="btn primary" type="button" onclick={handleImport} disabled={importing}>
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
						<b>{importResult.success ? 'Import successful' : 'Import failed'}</b>
						{#if importResult.applied.length > 0}
							<p>Applied sections: {importResult.applied.join(', ')}</p>
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
