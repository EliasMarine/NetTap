<script lang="ts">
	/**
	 * SSL Certificate Viewer — Inspect SSL/TLS certificates for any host.
	 *
	 * Layout:
	 *   - Back button to /tools
	 *   - Host + Port inputs
	 *   - Result card: Subject CN, Issuer, Serial, Validity, SANs, Fingerprint, Chain
	 *   - Collapsible raw output
	 *   - Reads URL query params: ?host=X
	 */

	import { page } from '$app/stores';
	import { sslCertInspect } from '$api/tools';
	import type { SslCertResult } from '$api/tools';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let host = $state('');
	let port = $state(443);
	let result = $state<SslCertResult | null>(null);
	let loading = $state(false);
	let error = $state('');
	let showRaw = $state(false);

	// ---------------------------------------------------------------------------
	// Read URL query params on load
	// ---------------------------------------------------------------------------

	$effect(() => {
		const params = $page.url.searchParams;
		const h = params.get('host');
		if (h) host = h;
	});

	// ---------------------------------------------------------------------------
	// Lookup
	// ---------------------------------------------------------------------------

	async function handleInspect() {
		const trimmed = host.trim();
		if (!trimmed) return;

		loading = true;
		error = '';
		result = null;
		showRaw = false;

		try {
			result = await sslCertInspect(trimmed, port);
			if (result.error) error = result.error;
		} catch (e) {
			error = e instanceof Error ? e.message : 'SSL inspection failed';
		} finally {
			loading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') handleInspect();
	}

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function validityBadge(notAfter: string): { label: string; cls: string } {
		if (!notAfter) return { label: 'Unknown', cls: 'badge-muted' };
		const expiry = new Date(notAfter);
		const now = new Date();
		const daysLeft = Math.floor((expiry.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
		if (daysLeft < 0) return { label: `Expired ${Math.abs(daysLeft)}d ago`, cls: 'badge-danger' };
		if (daysLeft <= 30) return { label: `Expires in ${daysLeft}d`, cls: 'badge-warning' };
		return { label: `Valid (${daysLeft}d remaining)`, cls: 'badge-success' };
	}

	function formatDate(d: string): string {
		if (!d) return '--';
		try {
			return new Date(d).toLocaleDateString('en-US', {
				year: 'numeric',
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit',
				timeZoneName: 'short',
			});
		} catch {
			return d;
		}
	}

	let validity = $derived(result ? validityBadge(result.not_after) : null);
</script>

<svelte:head>
	<title>SSL Certificate Viewer | NetTap</title>
</svelte:head>

<div class="ssl-page">
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
		<h1>SSL Certificate Viewer</h1>
		<p class="page-desc">Inspect SSL/TLS certificates, check validity, and view certificate chains</p>
	</div>

	<!-- Input card -->
	<div class="input-card">
		<div class="input-row">
			<div class="input-group">
				<span class="input-label">Host</span>
				<input
					type="text"
					class="input-field"
					placeholder="example.com"
					bind:value={host}
					onkeydown={handleKeydown}
				/>
			</div>
			<div class="input-group input-sm">
				<span class="input-label">Port</span>
				<input
					type="number"
					class="input-field"
					bind:value={port}
					min="1"
					max="65535"
				/>
			</div>
			<button class="btn btn-primary" onclick={handleInspect} disabled={loading || !host.trim()}>
				{#if loading}
					<span class="spinner"></span>
					Inspecting...
				{:else}
					<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0110 0v4" />
					</svg>
					Inspect
				{/if}
			</button>
		</div>
	</div>

	<!-- Loading state -->
	{#if loading}
		<div class="card loading-card">
			<div class="skeleton skeleton-block"></div>
			<div class="skeleton-grid">
				{#each Array(6) as _}
					<div class="skeleton skeleton-field"></div>
				{/each}
			</div>
		</div>
	{:else if error}
		<!-- Error state -->
		<div class="empty-state">
			<div class="empty-icon">
				<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
					<circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
				</svg>
			</div>
			<h3>Inspection Failed</h3>
			<p class="text-muted">{error}</p>
		</div>
	{:else if result && !result.error}
		<!-- Results -->
		<div class="card result-card">
			<!-- Header -->
			<div class="result-header">
				<h2 class="mono">{result.host}:{result.port}</h2>
				{#if validity}
					<span class="badge {validity.cls}">{validity.label}</span>
				{/if}
			</div>

			<!-- Certificate Info -->
			<div class="section">
				<h3 class="section-title">Certificate Info</h3>
				<div class="result-grid">
					<div class="result-field">
						<span class="field-label">Subject CN</span>
						<span class="field-value">{result.subject?.CN || result.subject?.commonName || '--'}</span>
					</div>
					<div class="result-field">
						<span class="field-label">Issuer</span>
						<span class="field-value">{result.issuer?.CN || result.issuer?.O || result.issuer?.commonName || '--'}</span>
					</div>
					<div class="result-field">
						<span class="field-label">Serial Number</span>
						<span class="field-value mono">{result.serial || '--'}</span>
					</div>
				</div>
			</div>

			<!-- Validity -->
			<div class="section">
				<h3 class="section-title">Validity</h3>
				<div class="result-grid">
					<div class="result-field">
						<span class="field-label">Not Before</span>
						<span class="field-value">{formatDate(result.not_before)}</span>
					</div>
					<div class="result-field">
						<span class="field-label">Not After</span>
						<span class="field-value">{formatDate(result.not_after)}</span>
					</div>
				</div>
			</div>

			<!-- SANs -->
			{#if result.san && result.san.length > 0}
				<div class="section">
					<h3 class="section-title">Subject Alternative Names ({result.san.length})</h3>
					<div class="san-list">
						{#each result.san as name}
							<span class="san-badge">{name}</span>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Fingerprint -->
			<div class="section">
				<h3 class="section-title">Fingerprint</h3>
				<div class="result-field">
					<span class="field-label">SHA-256</span>
					<span class="field-value mono fingerprint">{result.fingerprint_sha256 || '--'}</span>
				</div>
			</div>

			<!-- Chain -->
			{#if result.chain && result.chain.length > 0}
				<div class="section">
					<h3 class="section-title">Certificate Chain ({result.chain.length})</h3>
					<div class="chain-list">
						{#each result.chain as cert, i}
							<div class="chain-item">
								<span class="chain-index">{i + 1}</span>
								<span class="chain-subject">{cert}</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Raw output -->
			{#if result.raw}
				<div class="raw-section">
					<button class="btn btn-secondary btn-sm" onclick={() => showRaw = !showRaw}>
						{showRaw ? 'Hide' : 'Show'} Raw Certificate Output
					</button>
					{#if showRaw}
						<pre class="raw-output">{result.raw}</pre>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.ssl-page {
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

	.input-sm {
		max-width: 100px;
		flex: 0 0 auto;
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

	/* Result card */
	.result-card {
		display: flex;
		flex-direction: column;
		gap: var(--space-xl);
	}

	.result-header {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		flex-wrap: wrap;
	}

	.result-header h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--accent);
	}

	/* Sections */
	.section {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.section-title {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding-bottom: var(--space-xs);
		border-bottom: 1px solid var(--border-dim);
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

	.fingerprint {
		font-size: var(--text-xs);
		word-break: break-all;
		line-height: var(--leading-relaxed);
	}

	/* SANs */
	.san-list {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
	}

	.san-badge {
		display: inline-block;
		padding: 4px 10px;
		background: var(--bg-tertiary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-sm);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	/* Certificate chain */
	.chain-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.chain-item {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-sm) var(--space-md);
		background: var(--bg-tertiary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-sm);
	}

	.chain-index {
		flex-shrink: 0;
		width: 24px;
		height: 24px;
		display: flex;
		align-items: center;
		justify-content: center;
		background: var(--accent-muted);
		color: var(--accent);
		border-radius: 50%;
		font-size: var(--text-xs);
		font-weight: 700;
		font-family: var(--font-mono);
	}

	.chain-subject {
		font-size: var(--text-sm);
		color: var(--text-primary);
		word-break: break-all;
	}

	/* Validity badges */
	.badge-success {
		background: var(--green-dim);
		color: var(--green);
		border: 1px solid rgba(0, 230, 118, 0.2);
	}

	.badge-warning {
		background: var(--amber-dim);
		color: var(--amber);
		border: 1px solid rgba(255, 171, 0, 0.2);
	}

	.badge-danger {
		background: var(--red-dim);
		color: var(--red);
		border: 1px solid rgba(255, 71, 87, 0.2);
	}

	.badge-muted {
		background: var(--bg-tertiary);
		color: var(--text-muted);
		border: 1px solid var(--border-dim);
	}

	/* Raw output */
	.raw-section {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.raw-output {
		padding: var(--space-md);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-secondary);
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		overflow-x: auto;
		white-space: pre-wrap;
		word-break: break-all;
		max-height: 400px;
		overflow-y: auto;
		line-height: var(--leading-relaxed);
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

	/* Loading state */
	.loading-card {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.skeleton {
		background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--border-muted) 50%, var(--bg-tertiary) 75%);
		background-size: 200% 100%;
		animation: shimmer 1.5s infinite;
		border-radius: var(--radius-sm);
	}

	.skeleton-block {
		height: 48px;
		width: 240px;
	}

	.skeleton-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
		gap: var(--space-lg);
	}

	.skeleton-field {
		height: 56px;
		width: 100%;
	}

	@keyframes shimmer {
		0% { background-position: 200% 0; }
		100% { background-position: -200% 0; }
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

		.input-sm {
			max-width: 100%;
		}

		.result-header h2 {
			font-size: var(--text-xl);
		}

		.result-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
