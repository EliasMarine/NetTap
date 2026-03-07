<script lang="ts">
	import { dnsRecon } from '$api/tools';
	import type { DnsReconResult, DnsReconRecord } from '$api/tools';

	// ---------------------------------------------------------------------------
	// Record type definitions with display metadata
	// ---------------------------------------------------------------------------

	interface RecordTypeDef {
		type: string;
		label: string;
		defaultSelected: boolean;
	}

	const recordTypeDefs: RecordTypeDef[] = [
		{ type: 'A', label: 'Address Records', defaultSelected: true },
		{ type: 'AAAA', label: 'IPv6 Address Records', defaultSelected: true },
		{ type: 'CNAME', label: 'Canonical Name Records', defaultSelected: true },
		{ type: 'MX', label: 'Mail Exchange Records', defaultSelected: true },
		{ type: 'NS', label: 'Name Server Records', defaultSelected: true },
		{ type: 'TXT', label: 'Text Records', defaultSelected: true },
		{ type: 'SOA', label: 'Start of Authority', defaultSelected: true },
		{ type: 'PTR', label: 'Pointer Records', defaultSelected: false },
		{ type: 'SRV', label: 'Service Records', defaultSelected: false },
	];

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let domain = $state('');
	let selectedTypes = $state<Set<string>>(
		new Set(recordTypeDefs.filter((d) => d.defaultSelected).map((d) => d.type))
	);
	let result = $state<DnsReconResult | null>(null);
	let loading = $state(false);
	let error = $state('');

	// ---------------------------------------------------------------------------
	// Actions
	// ---------------------------------------------------------------------------

	function toggleType(type: string) {
		const next = new Set(selectedTypes);
		if (next.has(type)) {
			next.delete(type);
		} else {
			next.add(type);
		}
		selectedTypes = next;
	}

	async function handleLookup() {
		const trimmed = domain.trim();
		if (!trimmed) return;

		loading = true;
		error = '';
		result = null;

		try {
			const types = [...selectedTypes];
			result = await dnsRecon(trimmed, types.length > 0 ? types : undefined);
			if (result.errors && result.errors.length > 0) {
				error = result.errors.join('; ');
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'DNS lookup failed';
		} finally {
			loading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			handleLookup();
		}
	}

	// Ordered record types to display (match order of recordTypeDefs)
	let orderedResultTypes = $derived(
		result
			? recordTypeDefs
					.map((d) => d.type)
					.filter((t) => result!.records[t] !== undefined)
			: []
	);

	function getTypeDef(type: string): RecordTypeDef {
		return recordTypeDefs.find((d) => d.type === type) || { type, label: type, defaultSelected: false };
	}
</script>

<svelte:head>
	<title>DNS Reconnaissance | NetTap</title>
</svelte:head>

<div class="dns-recon-page">
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
			<h1>DNS Reconnaissance</h1>
			<p class="text-muted">Enumerate all DNS records for any domain using dig</p>
		</div>
	</div>

	<!-- Input card -->
	<div class="input-card">
		<div class="input-row">
			<div class="input-group">
				<span class="input-label">Domain</span>
				<input
					class="input-field"
					type="text"
					placeholder="example.com"
					bind:value={domain}
					onkeydown={handleKeydown}
				/>
			</div>
			<button class="btn btn-primary" onclick={handleLookup} disabled={loading || !domain.trim()}>
				{#if loading}
					Looking up...
				{:else}
					<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
					</svg>
					Lookup
				{/if}
			</button>
		</div>

		<div>
			<span class="input-label" style="margin-bottom: 8px; display:block;">Record Types</span>
			<div class="record-types">
				{#each recordTypeDefs as def}
					<button
						class="record-type-chip"
						class:selected={selectedTypes.has(def.type)}
						onclick={() => toggleType(def.type)}
					>
						{def.type}
					</button>
				{/each}
			</div>
		</div>
	</div>

	<!-- Loading skeleton -->
	{#if loading}
		<div class="skeleton-container">
			{#each Array(3) as _}
				<div class="skeleton-section">
					<div class="skeleton skeleton-header"></div>
					<div class="skeleton skeleton-row"></div>
					<div class="skeleton skeleton-row short"></div>
				</div>
			{/each}
		</div>
	{/if}

	<!-- Error -->
	{#if error && !loading}
		<div class="error-banner">
			<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
			</svg>
			{error}
		</div>
	{/if}

	<!-- Results -->
	{#if result && !loading}
		<!-- Results summary -->
		<div class="results-summary">
			<span class="result-badge count">{result.total_records} records found</span>
			<span class="result-badge time">{result.record_types_queried.length} queries</span>
		</div>

		<!-- Results by type -->
		{#each orderedResultTypes as type}
			{@const records = result.records[type] || []}
			{@const def = getTypeDef(type)}
			<div class="record-section">
				<div class="record-header">
					<div class="record-type-label">
						<span class="type-badge {type}">{type}</span>
						<span class="record-type-name">{def.label}</span>
					</div>
					<span class="record-count">{records.length} record{records.length !== 1 ? 's' : ''}</span>
				</div>

				{#if records.length > 0}
					<table class="record-table">
						<thead>
							<tr>
								<th>Name</th>
								<th>TTL</th>
								<th>Value</th>
							</tr>
						</thead>
						<tbody>
							{#each records as record}
								<tr>
									<td>{record.name}</td>
									<td class="ttl-value">{record.ttl}</td>
									<td class="record-value">{record.value}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{:else}
					<div class="no-records">No {type} records found</div>
				{/if}
			</div>
		{/each}
	{/if}
</div>

<style>
	.dns-recon-page {
		max-width: 960px;
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
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

	/* Input card */
	.input-card {
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-lg);
		padding: var(--space-lg);
	}

	.input-row {
		display: flex;
		gap: 12px;
		margin-bottom: var(--space-md);
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
		font-size: var(--text-base);
		font-family: var(--font-mono);
		outline: none;
		transition: border-color var(--transition-fast);
	}

	.input-field::placeholder {
		color: var(--text-dim);
	}

	.input-field:focus {
		border-color: var(--teal);
	}

	/* Record type chips */
	.record-types {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}

	.record-type-chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 4px 12px;
		background: var(--bg-elevated);
		border: 1px solid var(--border-dim);
		border-radius: 20px;
		color: var(--text-muted);
		font-size: var(--text-xs);
		font-family: var(--font-mono);
		font-weight: 600;
		cursor: pointer;
		transition: all var(--transition-fast);
		user-select: none;
	}

	.record-type-chip:hover {
		border-color: var(--border-bright);
		color: var(--text-secondary);
	}

	.record-type-chip.selected {
		background: var(--teal-dim);
		border-color: rgba(29, 233, 182, 0.3);
		color: var(--teal);
	}

	/* Results summary */
	.results-summary {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
	}

	.result-badge {
		padding: 4px 10px;
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		font-weight: 600;
		font-family: var(--font-mono);
	}

	.result-badge.count {
		background: var(--teal-dim);
		color: var(--teal);
	}

	.result-badge.time {
		background: var(--bg-elevated);
		color: var(--text-muted);
	}

	/* Record section */
	.record-section {
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-lg);
		overflow: hidden;
	}

	.record-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 14px 20px;
		border-bottom: 1px solid var(--border-dim);
	}

	.record-type-label {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.record-type-name {
		font-weight: 500;
	}

	.type-badge {
		padding: 3px 10px;
		border-radius: var(--radius-sm);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		font-weight: 700;
		letter-spacing: 0.03em;
	}

	.type-badge.A { background: var(--blue-dim); color: var(--blue); }
	.type-badge.AAAA { background: var(--purple-dim); color: var(--purple); }
	.type-badge.MX { background: var(--amber-dim); color: var(--amber); }
	.type-badge.NS { background: var(--green-dim); color: var(--green); }
	.type-badge.TXT { background: var(--teal-dim); color: var(--teal); }
	.type-badge.SOA { background: var(--red-dim); color: var(--red); }
	.type-badge.CNAME { background: rgba(255, 255, 255, 0.06); color: var(--text-secondary); }
	.type-badge.PTR { background: var(--orange-dim); color: var(--orange); }
	.type-badge.SRV { background: var(--cyan-dim); color: var(--cyan); }

	.record-count {
		font-size: var(--text-xs);
		color: var(--text-muted);
		font-family: var(--font-mono);
	}

	/* Record table */
	.record-table {
		width: 100%;
		border-collapse: collapse;
	}

	.record-table th {
		text-align: left;
		padding: 10px 20px;
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-dim);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		background: var(--bg-elevated);
		border-bottom: 1px solid var(--border-dim);
	}

	.record-table td {
		padding: 10px 20px;
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		color: var(--text-primary);
		border-bottom: 1px solid var(--border-dim);
	}

	.record-table tr:last-child td {
		border-bottom: none;
	}

	.record-table tr:hover td {
		background: rgba(255, 255, 255, 0.02);
	}

	.ttl-value {
		color: var(--text-muted);
	}

	.record-value {
		color: var(--teal);
		word-break: break-all;
	}

	.no-records {
		padding: 16px 20px;
		text-align: center;
		color: var(--text-muted);
		font-size: var(--text-sm);
		font-style: italic;
	}

	/* Error banner */
	.error-banner {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-md);
		background: var(--red-dim);
		border: 1px solid rgba(255, 71, 87, 0.3);
		border-radius: var(--radius-md);
		color: var(--red);
		font-size: var(--text-sm);
	}

	/* Loading skeleton */
	.skeleton-container {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.skeleton-section {
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-lg);
		padding: var(--space-lg);
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.skeleton {
		background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--border-muted) 50%, var(--bg-tertiary) 75%);
		background-size: 200% 100%;
		animation: shimmer 1.5s infinite;
		border-radius: var(--radius-sm);
	}

	.skeleton-header {
		height: 24px;
		width: 200px;
	}

	.skeleton-row {
		height: 40px;
		width: 100%;
	}

	.skeleton-row.short {
		width: 60%;
	}

	@keyframes shimmer {
		0% { background-position: 200% 0; }
		100% { background-position: -200% 0; }
	}

	@media (max-width: 768px) {
		.input-row {
			flex-direction: column;
		}

		.record-table th,
		.record-table td {
			padding: 8px 12px;
		}
	}
</style>
