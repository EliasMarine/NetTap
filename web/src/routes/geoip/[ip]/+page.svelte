<script lang="ts">
	/**
	 * GeoIP Lookup — Displays geolocation data for an IP address.
	 *
	 * Layout:
	 *   - Back button
	 *   - Search bar to look up any IP
	 *   - Results card with country (flag), city, coordinates, ASN, org
	 *   - Coordinates link to Google Maps
	 *   - Private IP badge when applicable
	 */

	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { lookupGeoIP } from '$api/geoip';
	import type { GeoIPResult } from '$api/geoip';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let ip = $derived($page.params.ip);
	let result = $state<GeoIPResult | null>(null);
	let loading = $state(true);
	let error = $state('');
	let searchIp = $state('');

	// ---------------------------------------------------------------------------
	// Lookup
	// ---------------------------------------------------------------------------

	async function lookup(targetIp: string) {
		loading = true;
		error = '';
		try {
			result = await lookupGeoIP(targetIp);
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
			goto(`/geoip/${encodeURIComponent(trimmed)}`);
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			handleSearch();
		}
	}

	// ---------------------------------------------------------------------------
	// Country code to flag emoji
	// ---------------------------------------------------------------------------

	function countryCodeToFlag(code: string): string {
		if (!code || code.length !== 2 || code === 'XX') return '';
		const upper = code.toUpperCase();
		const codePoints = [...upper].map(
			(c) => 0x1f1e6 + c.charCodeAt(0) - 65
		);
		return String.fromCodePoint(...codePoints);
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
	<title>GeoIP Lookup — {ip ? decodeURIComponent(ip) : ''} | NetTap</title>
</svelte:head>

<div class="geoip-page">
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
		<h1>GeoIP Lookup</h1>
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
				{#if result.is_private}
					<span class="badge badge-warning">Private IP</span>
				{/if}
			</div>

			<!-- Data grid -->
			<div class="result-grid">
				<!-- Country -->
				<div class="result-field">
					<span class="field-label">Country</span>
					<span class="field-value">
						{#if result.country_code && result.country_code !== 'XX'}
							<span class="flag">{countryCodeToFlag(result.country_code)}</span>
						{/if}
						{result.country || '--'}
						{#if result.country_code && result.country_code !== 'XX'}
							<span class="text-muted">({result.country_code})</span>
						{/if}
					</span>
				</div>

				<!-- City -->
				<div class="result-field">
					<span class="field-label">City</span>
					<span class="field-value">{result.city || '--'}</span>
				</div>

				<!-- Coordinates -->
				<div class="result-field">
					<span class="field-label">Coordinates</span>
					<span class="field-value">
						{#if result.latitude != null && result.longitude != null}
							<a
								href="https://www.google.com/maps/search/?api=1&query={result.latitude},{result.longitude}"
								target="_blank"
								rel="noopener noreferrer"
								class="coord-link"
							>
								{result.latitude.toFixed(4)}, {result.longitude.toFixed(4)}
								<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
									<path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" />
								</svg>
							</a>
						{:else}
							--
						{/if}
					</span>
				</div>

				<!-- ASN -->
				<div class="result-field">
					<span class="field-label">ASN</span>
					<span class="field-value mono">{result.asn != null ? `AS${result.asn}` : '--'}</span>
				</div>

				<!-- Organization -->
				<div class="result-field">
					<span class="field-label">Organization</span>
					<span class="field-value">{result.organization || '--'}</span>
				</div>

				<!-- Private -->
				<div class="result-field">
					<span class="field-label">Is Private</span>
					<span class="field-value">
						{#if result.is_private}
							<span class="badge badge-warning">Yes</span>
						{:else}
							<span class="badge badge-success">No (Public)</span>
						{/if}
					</span>
				</div>
			</div>

			<!-- Map placeholder -->
			{#if result.latitude != null && result.longitude != null}
				<div class="map-placeholder">
					<svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
						<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
						<circle cx="12" cy="10" r="3" />
					</svg>
					<span class="text-muted">
						{result.latitude.toFixed(4)}, {result.longitude.toFixed(4)}
					</span>
					<a
						href="https://www.google.com/maps/search/?api=1&query={result.latitude},{result.longitude}"
						target="_blank"
						rel="noopener noreferrer"
						class="btn btn-secondary btn-sm"
					>
						Open in Google Maps
					</a>
				</div>
			{/if}
		</div>

		<!-- Quick actions -->
		<div class="actions-row">
			<button class="btn btn-secondary btn-sm" onclick={() => goto(`/devices/${encodeURIComponent(result?.ip ?? '')}`)}>
				View Device Details
			</button>
			<button class="btn btn-secondary btn-sm" onclick={() => goto(`/connections?filter=ip.src==${encodeURIComponent(result?.ip ?? '')}`)}>
				Filter Connections From
			</button>
			<button class="btn btn-secondary btn-sm" onclick={() => goto(`/connections?filter=ip.dst==${encodeURIComponent(result?.ip ?? '')}`)}>
				Filter Connections To
			</button>
		</div>
	{/if}
</div>

<style>
	.geoip-page {
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

	.flag {
		font-size: var(--text-xl);
	}

	.coord-link {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		color: var(--accent);
		text-decoration: none;
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		border-bottom: 1px dashed var(--border-default);
		transition: border-color var(--transition-fast), color var(--transition-fast);
	}

	.coord-link:hover {
		border-color: var(--accent);
		color: var(--accent-hover);
	}

	/* Map placeholder */
	.map-placeholder {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--space-sm);
		padding: var(--space-xl);
		background-color: var(--bg-tertiary);
		border: 1px dashed var(--border-default);
		border-radius: var(--radius-md);
		color: var(--text-muted);
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
