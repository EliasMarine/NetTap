<script lang="ts">
	/**
	 * WHOIS Lookup — Displays WHOIS registration data for an IP address.
	 *
	 * Layout:
	 *   - Back button
	 *   - Search bar to look up any IP
	 *   - Results card with parsed WHOIS fields
	 *   - Collapsible raw WHOIS output
	 *   - Quick action links to related lookups
	 */

	import { page } from '$app/stores';
	import { goto } from '$app/navigation';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let ip = $derived($page.params.ip);
	let result = $state<{ ip: string; raw: string; parsed: Record<string, string>; error: string | null } | null>(null);
	let loading = $state(true);
	let error = $state('');
	let searchIp = $state('');
	let showRaw = $state(false);

	// ---------------------------------------------------------------------------
	// Lookup
	// ---------------------------------------------------------------------------

	async function lookup(targetIp: string) {
		loading = true;
		error = '';
		try {
			const res = await fetch(`/api/lookup/whois/${encodeURIComponent(targetIp)}`);
			if (!res.ok) throw new Error('Lookup failed');
			result = await res.json();
			if (result?.error) error = result.error;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Lookup failed';
			result = null;
		} finally {
			loading = false;
		}
	}

	function handleSearch() {
		const trimmed = searchIp.trim();
		if (trimmed) {
			goto(`/lookup/whois/${encodeURIComponent(trimmed)}`);
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			handleSearch();
		}
	}

	// ---------------------------------------------------------------------------
	// Reactive fetch on route param change
	// ---------------------------------------------------------------------------

	$effect(() => {
		if (ip) {
			searchIp = decodeURIComponent(ip);
			lookup(decodeURIComponent(ip));
		}
	});
</script>

<svelte:head>
	<title>WHOIS Lookup — {ip ? decodeURIComponent(ip) : ''} | NetTap</title>
</svelte:head>

<div class="whois-page">
	<!-- Back button -->
	<div class="back-nav">
		<button class="btn btn-secondary btn-sm" onclick={() => history.back()}>
			<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
			</svg>
			Back
		</button>
	</div>

	<!-- Page header + search -->
	<div class="page-header">
		<h1>WHOIS Lookup</h1>
		<div class="search-bar">
			<input
				type="text"
				class="input"
				placeholder="Enter an IP address..."
				bind:value={searchIp}
				onkeydown={handleKeydown}
			/>
			<button class="btn btn-primary btn-sm" onclick={handleSearch}>
				<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
				</svg>
				Lookup
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
			<h3>Lookup Failed</h3>
			<p class="text-muted">{error}</p>
		</div>
	{:else if result}
		<!-- Results -->
		<div class="card result-card">
			<!-- IP header -->
			<div class="result-header">
				<h2 class="mono">{result.ip}</h2>
			</div>

			<!-- Parsed fields grid -->
			{#if result.parsed && Object.keys(result.parsed).length > 0}
				<div class="result-grid">
					{#each Object.entries(result.parsed) as [key, value]}
						<div class="result-field">
							<span class="field-label">{key}</span>
							<span class="field-value">{value || '--'}</span>
						</div>
					{/each}
				</div>
			{:else}
				<p class="text-muted">No parsed WHOIS fields available.</p>
			{/if}

			<!-- Raw WHOIS output -->
			{#if result.raw}
				<div class="raw-section">
					<button class="btn btn-secondary btn-sm" onclick={() => showRaw = !showRaw}>
						{showRaw ? 'Hide' : 'Show'} Raw WHOIS Output
					</button>
					{#if showRaw}
						<pre class="raw-output">{result.raw}</pre>
					{/if}
				</div>
			{/if}
		</div>

		<!-- Quick actions -->
		<div class="actions-row">
			<button class="btn btn-secondary btn-sm" onclick={() => goto(`/devices/${encodeURIComponent(result?.ip ?? '')}`)}>
				View Device Details
			</button>
			<button class="btn btn-secondary btn-sm" onclick={() => goto(`/geoip/${encodeURIComponent(result?.ip ?? '')}`)}>
				GeoIP Lookup
			</button>
			<button class="btn btn-secondary btn-sm" onclick={() => goto(`/lookup/dns/${encodeURIComponent(result?.ip ?? '')}`)}>
				DNS Lookup
			</button>
		</div>
	{/if}
</div>

<style>
	.whois-page {
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
		gap: var(--space-md);
	}

	.page-header h1 {
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--text-primary);
	}

	.search-bar {
		display: flex;
		gap: var(--space-sm);
		max-width: 480px;
	}

	.search-bar .input {
		flex: 1;
		padding: var(--space-sm) var(--space-md);
		font-size: var(--text-sm);
		font-family: var(--font-mono);
		color: var(--text-primary);
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		outline: none;
		transition: border-color var(--transition-fast);
	}

	.search-bar .input:focus {
		border-color: var(--accent);
	}

	.search-bar .input::placeholder {
		color: var(--text-muted);
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
		display: flex;
		align-items: center;
		gap: var(--space-xs);
	}

	/* Raw WHOIS output */
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

	/* Actions row */
	.actions-row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-sm);
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

	.empty-state p {
		max-width: 480px;
		line-height: var(--leading-relaxed);
	}

	/* Responsive */
	@media (max-width: 768px) {
		.result-header h2 {
			font-size: var(--text-2xl);
		}

		.result-grid {
			grid-template-columns: 1fr;
		}

		.search-bar {
			max-width: 100%;
		}
	}
</style>
