<script lang="ts">
	/**
	 * MAC Lookup — Look up the vendor/manufacturer for a MAC address (OUI).
	 *
	 * Layout:
	 *   - Back button to /tools
	 *   - Input field for MAC address (any format)
	 *   - Lookup button
	 *   - Result card with normalized MAC, OUI prefix, vendor, found badge
	 */

	import { macLookup } from '$api/tools';
	import type { MacLookupResult } from '$api/tools';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let mac = $state('');
	let result = $state<MacLookupResult | null>(null);
	let loading = $state(false);
	let error = $state('');

	// ---------------------------------------------------------------------------
	// Lookup
	// ---------------------------------------------------------------------------

	async function handleLookup() {
		const trimmed = mac.trim();
		if (!trimmed) return;

		loading = true;
		error = '';
		result = null;

		try {
			result = await macLookup(trimmed);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Lookup failed';
		} finally {
			loading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			handleLookup();
		}
	}
</script>

<svelte:head>
	<title>MAC Lookup | NetTap</title>
</svelte:head>

<div class="mac-page">
	<!-- Back button -->
	<div class="back-nav">
		<a href="/tools" class="btn btn-secondary btn-sm">
			<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
			</svg>
			Back to Tools
		</a>
	</div>

	<!-- Page header -->
	<div class="page-header">
		<h1>MAC Address Lookup</h1>
		<p class="page-desc">Look up the vendor or manufacturer for any MAC address (OUI database)</p>
	</div>

	<!-- Input card -->
	<div class="input-card">
		<div class="input-row">
			<div class="input-group">
				<span class="input-label">MAC Address</span>
				<input
					type="text"
					class="input-field"
					placeholder="AA:BB:CC:DD:EE:FF"
					bind:value={mac}
					onkeydown={handleKeydown}
				/>
			</div>
			<button class="btn btn-primary" onclick={handleLookup} disabled={loading || !mac.trim()}>
				{#if loading}
					<span class="spinner"></span>
					Looking up...
				{:else}
					<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
					</svg>
					Lookup
				{/if}
			</button>
		</div>
		<span class="input-hint">Accepts AA:BB:CC:DD:EE:FF, AA-BB-CC-DD-EE-FF, or AABBCCDDEEFF</span>
	</div>

	<!-- Error state -->
	{#if error}
		<div class="empty-state">
			<div class="empty-icon">
				<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
					<circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
				</svg>
			</div>
			<h3>Lookup Failed</h3>
			<p class="text-muted">{error}</p>
		</div>
	{:else if result}
		<!-- Result card -->
		<div class="card result-card">
			<div class="result-header">
				<h2 class="mono">{result.mac}</h2>
				{#if result.found}
					<span class="badge badge-success">Found</span>
				{:else}
					<span class="badge badge-warning">Not Found</span>
				{/if}
			</div>

			<div class="result-grid">
				<div class="result-field">
					<span class="field-label">Normalized MAC</span>
					<span class="field-value mono">{result.mac}</span>
				</div>

				<div class="result-field">
					<span class="field-label">OUI Prefix</span>
					<span class="field-value mono">{result.oui_prefix || '--'}</span>
				</div>

				<div class="result-field">
					<span class="field-label">Vendor / Manufacturer</span>
					<span class="field-value">{result.vendor || 'Unknown vendor'}</span>
				</div>
			</div>
		</div>
	{/if}
</div>

<style>
	.mac-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	/* Back nav */
	.back-nav {
		display: flex;
	}

	/* Page header */
	.page-header {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.page-header h1 {
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--text-primary);
	}

	.page-desc {
		color: var(--text-secondary);
		font-size: var(--text-sm);
	}

	/* Input card */
	.input-card {
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-lg);
		padding: var(--space-lg);
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.input-row {
		display: flex;
		gap: var(--space-md);
		align-items: flex-end;
	}

	.input-group {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.input-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.input-field {
		padding: 10px 14px;
		background: var(--bg-input);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		color: var(--text-primary);
		font-size: var(--text-sm);
		font-family: var(--font-mono);
		outline: none;
		transition: border-color var(--transition-fast);
		width: 100%;
	}

	.input-field::placeholder {
		color: var(--text-dim);
	}

	.input-field:focus {
		border-color: var(--accent);
	}

	.input-hint {
		font-size: var(--text-xs);
		color: var(--text-dim);
	}

	/* Result card */
	.result-card {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.result-header {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.result-header h2 {
		font-size: var(--text-3xl);
		font-weight: 700;
		color: var(--accent);
	}

	/* Data grid */
	.result-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
		gap: var(--space-lg);
	}

	.result-field {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.field-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.field-value {
		font-size: var(--text-md);
		color: var(--text-primary);
	}

	/* Spinner */
	.spinner {
		width: 14px;
		height: 14px;
		border: 2px solid rgba(255, 255, 255, 0.3);
		border-top-color: #fff;
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
		display: inline-block;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	/* Empty / error state */
	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--space-3xl);
		text-align: center;
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
	}

	.empty-icon {
		color: var(--text-muted);
		margin-bottom: var(--space-md);
	}

	.empty-state h3 {
		font-size: var(--text-xl);
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: var(--space-sm);
	}

	/* Responsive */
	@media (max-width: 768px) {
		.input-row {
			flex-direction: column;
		}

		.result-header h2 {
			font-size: var(--text-2xl);
		}

		.result-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
