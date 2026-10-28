<script lang="ts">
	import { onMount } from 'svelte';
	import {
		exportConfig,
		downloadConfigFile,
		validateConfig,
		importConfig,
		readConfigFile,
	} from '$lib/api/backup';
	import type { ValidationResult, ImportResult } from '$lib/api/backup';

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
	<title>Backup & Restore - NetTap</title>
</svelte:head>

<div class="page-container">
	<header class="page-header">
		<h1>Backup & Restore</h1>
		<p class="subtitle">Export and import your NetTap configuration</p>
	</header>

	<!-- Export Section -->
	<section class="card">
		<h2>Export Configuration</h2>
		<p class="description">
			Download all NetTap settings as a JSON file. Includes capture mode, retention policies,
			notification channels, device aliases, excluded IPs, and bandwidth cap.
		</p>

		<div class="export-actions">
			<button class="btn btn-primary" onclick={handleExport} disabled={exporting}>
				{exporting ? 'Exporting...' : 'Export Configuration'}
			</button>

			{#if lastExportDate}
				<span class="last-export">Last export: {lastExportDate}</span>
			{/if}
		</div>

		{#if exportMessage}
			<div class="message" class:error={exportError}>
				{exportMessage}
			</div>
		{/if}
	</section>

	<!-- Import Section -->
	<section class="card">
		<h2>Import Configuration</h2>
		<p class="description">
			Upload a previously exported configuration file to restore settings.
			The file will be validated before applying.
		</p>

		{#if !importFile}
			<!-- Drop zone -->
			<div
				class="dropzone"
				class:dragging={isDragging}
				role="button"
				tabindex="0"
				ondrop={handleDrop}
				ondragover={handleDragOver}
				ondragleave={handleDragLeave}
			>
				<div class="dropzone-content">
					<span class="dropzone-icon">&#128196;</span>
					<p>Drag and drop a configuration file here</p>
					<p class="dropzone-or">or</p>
					<label class="btn btn-secondary file-label">
						Choose File
						<input
							type="file"
							accept=".json"
							onchange={handleFileSelect}
							class="file-input"
						/>
					</label>
				</div>
			</div>
		{:else}
			<!-- File selected -->
			<div class="selected-file">
				<span class="file-name">{importFile.name}</span>
				<span class="file-size">
					({(importFile.size / 1024).toFixed(1)} KB)
				</span>
				<button class="btn btn-sm" onclick={resetImport}>Remove</button>
			</div>

			{#if validating}
				<div class="message">Validating configuration...</div>
			{/if}

			{#if validation}
				<!-- Validation results -->
				<div class="validation-results">
					<div class="validation-status" class:valid={validation.is_valid} class:invalid={!validation.is_valid}>
						{validation.is_valid ? 'Valid configuration' : 'Invalid configuration'}
					</div>

					{#if validation.errors.length > 0}
						<div class="validation-list errors">
							<h4>Errors</h4>
							<ul>
								{#each validation.errors as err}
									<li>{err}</li>
								{/each}
							</ul>
						</div>
					{/if}

					{#if validation.warnings.length > 0}
						<div class="validation-list warnings">
							<h4>Warnings</h4>
							<ul>
								{#each validation.warnings as warn}
									<li>{warn}</li>
								{/each}
							</ul>
						</div>
					{/if}

					{#if Object.keys(validation.preview).length > 0}
						<div class="preview">
							<h4>Sections to import</h4>
							<div class="preview-grid">
								{#each Object.entries(validation.preview) as [name, info]}
									<div class="preview-item">
										<span class="section-name">{name.replace(/_/g, ' ')}</span>
										<span class="section-info">{info.size} items</span>
									</div>
								{/each}
							</div>
						</div>
					{/if}

					{#if validation.is_valid}
						<button
							class="btn btn-primary"
							onclick={handleImport}
							disabled={importing}
						>
							{importing ? 'Importing...' : 'Apply Configuration'}
						</button>
					{/if}
				</div>
			{/if}

			{#if importResult}
				<div class="import-result" class:success={importResult.success} class:failure={!importResult.success}>
					<h4>{importResult.success ? 'Import Successful' : 'Import Failed'}</h4>
					{#if importResult.applied.length > 0}
						<p>Applied sections: {importResult.applied.join(', ')}</p>
					{/if}
					{#if importResult.errors.length > 0}
						<p class="import-errors">Errors: {importResult.errors.join(', ')}</p>
					{/if}
					{#if importResult.warnings.length > 0}
						<p class="import-warnings">Warnings: {importResult.warnings.join(', ')}</p>
					{/if}
				</div>
			{/if}

			{#if importError && !importResult}
				<div class="message error">{importError}</div>
			{/if}
		{/if}
	</section>
</div>

<style>
	.page-container {
		max-width: 800px;
		margin: 0 auto;
		padding: 1.5rem;
	}

	.page-header {
		margin-bottom: 1.5rem;
	}

	.page-header h1 {
		font-size: 1.75rem;
		font-weight: 700;
		color: var(--text-primary, #e4e4e7);
		margin: 0;
	}

	.subtitle {
		color: var(--text-secondary, #a1a1aa);
		margin: 0.25rem 0 0;
		font-size: 0.9rem;
	}

	.card {
		background: var(--surface-card, #1a1a2e);
		border: 1px solid var(--border-color, #2d2d44);
		border-radius: 0.75rem;
		padding: 1.5rem;
		margin-bottom: 1.5rem;
	}

	h2 {
		font-size: 1.1rem;
		font-weight: 600;
		color: var(--text-primary, #e4e4e7);
		margin: 0 0 0.5rem;
	}

	.description {
		color: var(--text-secondary, #a1a1aa);
		font-size: 0.875rem;
		margin: 0 0 1rem;
		line-height: 1.5;
	}

	.export-actions {
		display: flex;
		align-items: center;
		gap: 1rem;
	}

	.last-export {
		color: var(--text-muted, #52525b);
		font-size: 0.8rem;
	}

	.btn {
		padding: 0.5rem 1rem;
		border: 1px solid var(--border-color, #2d2d44);
		border-radius: 0.5rem;
		cursor: pointer;
		font-size: 0.875rem;
		transition: all 0.15s;
		background: var(--surface-card, #1a1a2e);
		color: var(--text-primary, #e4e4e7);
	}

	.btn:hover {
		border-color: var(--accent-blue, #3b82f6);
	}

	.btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.btn-primary {
		background: var(--accent-blue, #3b82f6);
		border-color: var(--accent-blue, #3b82f6);
		color: #fff;
	}

	.btn-primary:hover:not(:disabled) {
		background: #2563eb;
	}

	.btn-secondary {
		background: var(--surface-elevated, #252540);
	}

	.btn-sm {
		padding: 0.25rem 0.5rem;
		font-size: 0.75rem;
	}

	.message {
		margin-top: 0.75rem;
		padding: 0.625rem 1rem;
		border-radius: 0.5rem;
		font-size: 0.875rem;
		background: rgba(34, 197, 94, 0.1);
		border: 1px solid rgba(34, 197, 94, 0.3);
		color: #22c55e;
	}

	.message.error {
		background: rgba(239, 68, 68, 0.1);
		border-color: rgba(239, 68, 68, 0.3);
		color: #ef4444;
	}

	.dropzone {
		border: 2px dashed var(--border-color, #2d2d44);
		border-radius: 0.75rem;
		padding: 2rem;
		text-align: center;
		cursor: pointer;
		transition: all 0.15s;
	}

	.dropzone:hover,
	.dropzone.dragging {
		border-color: var(--accent-blue, #3b82f6);
		background: rgba(59, 130, 246, 0.05);
	}

	.dropzone-content {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.5rem;
	}

	.dropzone-icon {
		font-size: 2rem;
		opacity: 0.5;
	}

	.dropzone-content p {
		color: var(--text-secondary, #a1a1aa);
		font-size: 0.875rem;
		margin: 0;
	}

	.dropzone-or {
		color: var(--text-muted, #52525b) !important;
		font-size: 0.75rem !important;
	}

	.file-label {
		display: inline-flex;
		align-items: center;
	}

	.file-input {
		display: none;
	}

	.selected-file {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		background: var(--surface-input, #0f0f1a);
		border: 1px solid var(--border-color, #2d2d44);
		border-radius: 0.5rem;
		margin-bottom: 1rem;
	}

	.file-name {
		font-family: 'JetBrains Mono', monospace;
		font-size: 0.875rem;
		color: var(--text-primary, #e4e4e7);
	}

	.file-size {
		color: var(--text-muted, #52525b);
		font-size: 0.8rem;
	}

	.validation-results {
		margin-top: 1rem;
	}

	.validation-status {
		padding: 0.5rem 1rem;
		border-radius: 0.5rem;
		font-weight: 600;
		font-size: 0.875rem;
		margin-bottom: 0.75rem;
	}

	.validation-status.valid {
		background: rgba(34, 197, 94, 0.1);
		border: 1px solid rgba(34, 197, 94, 0.3);
		color: #22c55e;
	}

	.validation-status.invalid {
		background: rgba(239, 68, 68, 0.1);
		border: 1px solid rgba(239, 68, 68, 0.3);
		color: #ef4444;
	}

	.validation-list {
		margin-bottom: 0.75rem;
	}

	.validation-list h4 {
		font-size: 0.8rem;
		font-weight: 600;
		margin: 0 0 0.25rem;
	}

	.validation-list.errors h4 {
		color: #ef4444;
	}

	.validation-list.warnings h4 {
		color: #f59e0b;
	}

	.validation-list ul {
		margin: 0;
		padding-left: 1.25rem;
		font-size: 0.8rem;
	}

	.validation-list.errors li {
		color: #ef4444;
	}

	.validation-list.warnings li {
		color: #f59e0b;
	}

	.preview {
		margin-bottom: 1rem;
	}

	.preview h4 {
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--text-secondary, #a1a1aa);
		margin: 0 0 0.5rem;
	}

	.preview-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
		gap: 0.5rem;
	}

	.preview-item {
		display: flex;
		justify-content: space-between;
		padding: 0.5rem 0.75rem;
		background: var(--surface-input, #0f0f1a);
		border-radius: 0.375rem;
		font-size: 0.8rem;
	}

	.section-name {
		color: var(--text-primary, #e4e4e7);
		text-transform: capitalize;
	}

	.section-info {
		color: var(--text-muted, #52525b);
	}

	.import-result {
		margin-top: 1rem;
		padding: 0.75rem 1rem;
		border-radius: 0.5rem;
		font-size: 0.875rem;
	}

	.import-result.success {
		background: rgba(34, 197, 94, 0.1);
		border: 1px solid rgba(34, 197, 94, 0.3);
	}

	.import-result.failure {
		background: rgba(239, 68, 68, 0.1);
		border: 1px solid rgba(239, 68, 68, 0.3);
	}

	.import-result h4 {
		margin: 0 0 0.5rem;
		font-size: 0.9rem;
	}

	.import-result.success h4 {
		color: #22c55e;
	}

	.import-result.failure h4 {
		color: #ef4444;
	}

	.import-result p {
		margin: 0.25rem 0;
		color: var(--text-secondary, #a1a1aa);
		font-size: 0.8rem;
	}

	.import-errors {
		color: #ef4444 !important;
	}

	.import-warnings {
		color: #f59e0b !important;
	}
</style>
