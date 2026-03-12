<script lang="ts">
	import { goto } from '$app/navigation';

	let searchIp = $state('');

	function handleSearch() {
		const trimmed = searchIp.trim();
		if (trimmed) goto(`/lookup/dns/${encodeURIComponent(trimmed)}`);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') handleSearch();
	}
</script>

<svelte:head>
	<title>Reverse DNS Lookup | NetTap</title>
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
		<h1>Reverse DNS Lookup</h1>
		<p class="page-desc">Resolve IP addresses to hostnames and perform forward verification.</p>
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
				<circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" />
				<path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
			</svg>
		</div>
		<h3>Enter an IP Address</h3>
		<p class="text-muted">Type an IP address above and press Enter or click Lookup to resolve its hostname.</p>
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
