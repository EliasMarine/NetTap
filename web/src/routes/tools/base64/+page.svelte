<script lang="ts">
	/** Base64 / Hex Converter — Pure frontend, no API calls. */

	// ---------------------------------------------------------------------------
	// Operations
	// ---------------------------------------------------------------------------

	type Operation = 'base64-encode' | 'base64-decode' | 'hex-encode' | 'hex-decode' | 'url-encode' | 'url-decode';

	const operations: { value: Operation; label: string }[] = [
		{ value: 'base64-encode', label: 'Base64 Encode' },
		{ value: 'base64-decode', label: 'Base64 Decode' },
		{ value: 'hex-encode', label: 'Hex Encode' },
		{ value: 'hex-decode', label: 'Hex Decode' },
		{ value: 'url-encode', label: 'URL Encode' },
		{ value: 'url-decode', label: 'URL Decode' },
	];

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let input = $state('');
	let operation = $state<Operation>('base64-encode');
	let copyFeedback = $state(false);

	// ---------------------------------------------------------------------------
	// Conversion logic
	// ---------------------------------------------------------------------------

	function convert(text: string, op: Operation): { output: string; error: string } {
		if (!text) return { output: '', error: '' };

		try {
			switch (op) {
				case 'base64-encode':
					return { output: btoa(unescape(encodeURIComponent(text))), error: '' };
				case 'base64-decode':
					return { output: decodeURIComponent(escape(atob(text.trim()))), error: '' };
				case 'hex-encode': {
					const encoder = new TextEncoder();
					const bytes = encoder.encode(text);
					const hex = Array.from(bytes)
						.map((b) => b.toString(16).padStart(2, '0'))
						.join('');
					return { output: hex, error: '' };
				}
				case 'hex-decode': {
					const cleaned = text.replace(/\s/g, '');
					if (!/^[0-9a-fA-F]*$/.test(cleaned)) {
						return { output: '', error: 'Invalid hex input' };
					}
					if (cleaned.length % 2 !== 0) {
						return { output: '', error: 'Hex string must have even length' };
					}
					const bytes = new Uint8Array(
						cleaned.match(/.{2}/g)!.map((byte) => parseInt(byte, 16))
					);
					const decoder = new TextDecoder();
					return { output: decoder.decode(bytes), error: '' };
				}
				case 'url-encode':
					return { output: encodeURIComponent(text), error: '' };
				case 'url-decode':
					return { output: decodeURIComponent(text), error: '' };
				default:
					return { output: '', error: 'Unknown operation' };
			}
		} catch (e) {
			return { output: '', error: e instanceof Error ? e.message : 'Conversion failed' };
		}
	}

	let result = $derived(convert(input, operation));

	async function copyToClipboard() {
		if (!result.output) return;
		try {
			await navigator.clipboard.writeText(result.output);
			copyFeedback = true;
			setTimeout(() => { copyFeedback = false; }, 2000);
		} catch {
			// Clipboard API may not be available
		}
	}
</script>

<svelte:head>
	<title>Base64 / Hex Converter | NetTap</title>
</svelte:head>

<div class="converter-page">
	<!-- Back nav -->
	<div class="back-nav">
		<a href="/tools" class="back-link">
			<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
			</svg>
			Back to Tools
		</a>
	</div>

	<!-- Page header -->
	<div class="page-header">
		<div class="header-left">
			<h1>Base64 / Hex Converter</h1>
			<p class="text-muted">Encode and decode data. No data leaves your browser.</p>
		</div>
		<span class="header-badge">Client-side</span>
	</div>

	<!-- Operation selector -->
	<div class="operation-bar">
		<span class="input-label">Operation</span>
		<select class="operation-select" bind:value={operation}>
			{#each operations as op}
				<option value={op.value}>{op.label}</option>
			{/each}
		</select>
	</div>

	<!-- Converter panels -->
	<div class="converter-panels">
		<!-- Input panel -->
		<div class="panel">
			<div class="panel-header">
				<span class="panel-label">Input</span>
				<span class="char-count">{input.length} chars</span>
			</div>
			<textarea
				class="panel-textarea"
				placeholder="Enter text to convert..."
				bind:value={input}
				rows="12"
			></textarea>
		</div>

		<!-- Output panel -->
		<div class="panel">
			<div class="panel-header">
				<span class="panel-label">Output</span>
				<div class="panel-actions">
					<span class="char-count">{result.output.length} chars</span>
					<button
						class="copy-btn"
						onclick={copyToClipboard}
						disabled={!result.output}
						title="Copy to clipboard"
					>
						{#if copyFeedback}
							<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<polyline points="20 6 9 17 4 12" />
							</svg>
							Copied
						{:else}
							<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<rect x="9" y="9" width="13" height="13" rx="2" />
								<path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
							</svg>
							Copy
						{/if}
					</button>
				</div>
			</div>
			{#if result.error}
				<div class="error-output">{result.error}</div>
			{:else}
				<textarea
					class="panel-textarea output"
					readonly
					rows="12"
					value={result.output}
				></textarea>
			{/if}
		</div>
	</div>
</div>

<style>
	.converter-page {
		max-width: 1100px;
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	/* Back nav */
	.back-nav {
		display: flex;
	}

	.back-link {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 6px 14px;
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-sm);
		color: var(--text-secondary);
		font-size: var(--text-sm);
		font-weight: 500;
		text-decoration: none;
		transition: all var(--transition-fast);
	}

	.back-link:hover {
		background: var(--bg-tertiary);
		color: var(--text-primary);
		border-color: var(--border-default);
		text-decoration: none;
	}

	/* Page header */
	.page-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	.header-left h1 {
		font-size: var(--text-3xl);
		font-weight: 700;
		letter-spacing: -0.02em;
		margin-bottom: var(--space-xs);
	}

	.header-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 5px 12px;
		background: var(--cyan-dim);
		border: 1px solid rgba(0, 212, 255, 0.2);
		border-radius: 20px;
		color: var(--cyan);
		font-size: var(--text-xs);
		font-weight: 600;
		font-family: var(--font-mono);
	}

	/* Operation selector */
	.operation-bar {
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	.input-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.operation-select {
		padding: 8px 14px;
		background: var(--bg-input);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		color: var(--text-primary);
		font-size: var(--text-base);
		font-family: var(--font-sans);
		outline: none;
		cursor: pointer;
		transition: border-color var(--transition-fast);
		appearance: auto;
	}

	.operation-select:focus {
		border-color: var(--purple);
	}

	/* Converter panels */
	.converter-panels {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-md);
	}

	.panel {
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-lg);
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}

	.panel-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 16px;
		border-bottom: 1px solid var(--border-dim);
		background: var(--bg-elevated);
	}

	.panel-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.panel-actions {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.char-count {
		font-size: var(--text-xs);
		color: var(--text-dim);
		font-family: var(--font-mono);
	}

	.panel-textarea {
		flex: 1;
		width: 100%;
		padding: var(--space-md);
		background: transparent;
		border: none;
		color: var(--text-primary);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		resize: vertical;
		outline: none;
		line-height: 1.6;
	}

	.panel-textarea::placeholder {
		color: var(--text-dim);
	}

	.panel-textarea.output {
		color: var(--purple);
	}

	/* Copy button */
	.copy-btn {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 4px 10px;
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		color: var(--text-secondary);
		font-size: var(--text-xs);
		font-weight: 500;
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.copy-btn:hover:not(:disabled) {
		background: var(--bg-tertiary);
		color: var(--text-primary);
		border-color: var(--border-bright);
	}

	.copy-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	/* Error output */
	.error-output {
		padding: var(--space-md);
		color: var(--red);
		font-size: var(--text-sm);
		font-family: var(--font-mono);
	}

	@media (max-width: 768px) {
		.converter-panels {
			grid-template-columns: 1fr;
		}
	}
</style>
