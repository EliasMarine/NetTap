<script lang="ts">
	import { goto } from '$app/navigation';

	let searchIp = $state('');

	function handleSearch() {
		const trimmed = searchIp.trim();
		if (trimmed) goto(`/lookup/whois/${encodeURIComponent(trimmed)}`);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') handleSearch();
	}
</script>

<svelte:head>
	<title>WHOIS Lookup | NetTap</title>
</svelte:head>

<div class="lookup-page">
	<div class="back-nav">
		<a href="/tools" class="btn btn-secondary btn-sm">
			<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
			</svg>
			Back to Tools
		</a>
	</div>

	<div class="page-header">
		<h1>WHOIS Lookup</h1>
		<p class="page-desc">Query registration data for any IP address: owner, ASN, CIDR range, registrar, and contact information.</p>
	</div>

	<div class="input-card">
		<div class="input-row">
			<div class="input-group">
				<span class="input-label">IP Address</span>
				<input
					type="text"
					class="input-field"
					placeholder="e.g. 8.8.8.8"
					bind:value={searchIp}
					onkeydown={handleKeydown}
				/>
			</div>
			<button class="btn btn-primary" onclick={handleSearch} disabled={!searchIp.trim()}>
				<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
				</svg>
				Lookup
			</button>
		</div>
	</div>

	<div class="empty-state">
		<div class="empty-icon">
			<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
				<path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2" />
				<rect x="9" y="3" width="6" height="4" rx="2" />
				<path d="M9 14l2 2 4-4" />
			</svg>
		</div>
		<h3>Enter an IP Address</h3>
		<p class="text-muted">Type an IP address above and press Enter or click Lookup to query WHOIS data.</p>
	</div>
</div>

<style>
	.lookup-page { display: flex; flex-direction: column; gap: var(--space-lg); }
	.back-nav { display: flex; }
	.page-header { display: flex; flex-direction: column; gap: var(--space-xs); }
	.page-header h1 { font-size: var(--text-2xl); font-weight: 700; color: var(--text-primary); }
	.page-desc { color: var(--text-secondary); font-size: var(--text-sm); }
	.input-card { background: var(--bg-secondary); border: 1px solid var(--border-dim); border-radius: var(--radius-lg); padding: var(--space-lg); }
	.input-row { display: flex; gap: var(--space-md); align-items: flex-end; }
	.input-group { flex: 1; display: flex; flex-direction: column; gap: 6px; }
	.input-label { font-size: var(--text-xs); font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; }
	.input-field { padding: 10px 14px; background: var(--bg-input); border: 1px solid var(--border-default); border-radius: var(--radius-md); color: var(--text-primary); font-size: var(--text-sm); font-family: var(--font-mono); outline: none; transition: border-color var(--transition-fast); width: 100%; }
	.input-field::placeholder { color: var(--text-dim); }
	.input-field:focus { border-color: var(--accent); }
	.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: var(--space-3xl); text-align: center; background-color: var(--bg-secondary); border: 1px solid var(--border-default); border-radius: var(--radius-lg); }
	.empty-icon { color: var(--text-muted); margin-bottom: var(--space-md); }
	.empty-state h3 { font-size: var(--text-xl); font-weight: 600; color: var(--text-primary); margin-bottom: var(--space-sm); }
</style>
