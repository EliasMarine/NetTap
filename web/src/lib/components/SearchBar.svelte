<script lang="ts">
	import { executeSearch, getSearchSuggestions } from '$lib/api/search';
	import type { SearchResponse, SearchSuggestion } from '$lib/api/search';

	let query = $state('');
	let suggestions = $state<SearchSuggestion[]>([]);
	let showSuggestions = $state(false);
	let selectedIndex = $state(-1);
	let searching = $state(false);
	let results = $state<SearchResponse | null>(null);
	let debounceTimer = $state<ReturnType<typeof setTimeout> | null>(null);

	function debounce(fn: () => void, ms: number) {
		if (debounceTimer) clearTimeout(debounceTimer);
		debounceTimer = setTimeout(fn, ms);
	}

	function handleInput() {
		const value = query.trim();
		if (value.length < 2) {
			suggestions = [];
			showSuggestions = false;
			selectedIndex = -1;
			return;
		}
		debounce(async () => {
			const res = await getSearchSuggestions(value);
			suggestions = res.suggestions;
			showSuggestions = suggestions.length > 0;
			selectedIndex = -1;
		}, 300);
	}

	async function handleSearch() {
		const value = query.trim();
		if (!value) return;
		showSuggestions = false;
		searching = true;
		try {
			results = await executeSearch(value);
		} finally {
			searching = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (!showSuggestions || suggestions.length === 0) {
			if (e.key === 'Enter') {
				handleSearch();
			}
			return;
		}

		if (e.key === 'ArrowDown') {
			e.preventDefault();
			selectedIndex = Math.min(selectedIndex + 1, suggestions.length - 1);
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			selectedIndex = Math.max(selectedIndex - 1, -1);
		} else if (e.key === 'Enter') {
			e.preventDefault();
			if (selectedIndex >= 0 && selectedIndex < suggestions.length) {
				query = suggestions[selectedIndex].text;
				showSuggestions = false;
				selectedIndex = -1;
			}
			handleSearch();
		} else if (e.key === 'Escape') {
			showSuggestions = false;
			selectedIndex = -1;
		}
	}

	function selectSuggestion(index: number) {
		query = suggestions[index].text;
		showSuggestions = false;
		selectedIndex = -1;
		handleSearch();
	}

	function handleBlur() {
		// Delay so click events on suggestions fire first
		setTimeout(() => {
			showSuggestions = false;
		}, 200);
	}

	function formatTimestamp(result: Record<string, unknown>): string {
		const ts = result.timestamp || result['@timestamp'] || result.ts;
		if (typeof ts === 'string') return ts;
		return '';
	}

	function getKeyFields(result: Record<string, unknown>): [string, unknown][] {
		const skip = new Set(['_id', '_index', 'timestamp', '@timestamp', 'ts']);
		return Object.entries(result)
			.filter(([k]) => !skip.has(k))
			.slice(0, 5);
	}
</script>

<div class="search-bar-container">
	<div class="search-input-wrapper">
		<svg class="search-icon" viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
			<path
				fill-rule="evenodd"
				d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z"
				clip-rule="evenodd"
			/>
		</svg>
		<input
			class="input search-input"
			type="text"
			placeholder="Search your network..."
			bind:value={query}
			oninput={handleInput}
			onkeydown={handleKeydown}
			onblur={handleBlur}
			onfocus={() => {
				if (suggestions.length > 0) showSuggestions = true;
			}}
		/>
		<button class="btn btn-primary search-btn" onclick={handleSearch} disabled={searching || !query.trim()}>
			{searching ? 'Searching...' : 'Search'}
		</button>
	</div>

	{#if showSuggestions && suggestions.length > 0}
		<ul class="suggestions-dropdown" role="listbox">
			{#each suggestions as suggestion, i}
				<li
					class="suggestion-item"
					class:selected={i === selectedIndex}
					role="option"
					aria-selected={i === selectedIndex}
					onmousedown={() => selectSuggestion(i)}
				>
					{suggestion.text}
				</li>
			{/each}
		</ul>
	{/if}

	<p class="search-hint">Powered by natural language -- describe what you want to find.</p>

	{#if searching}
		<div class="search-loading">
			<span class="spinner"></span> Searching...
		</div>
	{/if}

	{#if results && !searching}
		<div class="search-results">
			<p class="results-summary">
				{results.total} result{results.total !== 1 ? 's' : ''} for "<strong>{results.query}</strong>"
				{#if results.description}
					<span class="results-description">-- {results.description}</span>
				{/if}
			</p>

			{#if results.results.length === 0}
				<div class="no-results">No results found. Try rephrasing your query.</div>
			{:else}
				<div class="results-list">
					{#each results.results as result}
						<div class="card result-card">
							<div class="result-header">
								<span class="badge">{result._index}</span>
								{#if formatTimestamp(result)}
									<span class="result-timestamp">{formatTimestamp(result)}</span>
								{/if}
							</div>
							<div class="result-fields">
								{#each getKeyFields(result) as [key, value]}
									<div class="result-field">
										<span class="field-key">{key}:</span>
										<span class="field-value">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
									</div>
								{/each}
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.search-bar-container {
		position: relative;
		width: 100%;
	}

	.search-input-wrapper {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		position: relative;
	}

	.search-icon {
		position: absolute;
		left: 12px;
		color: var(--text-muted);
		pointer-events: none;
		z-index: 1;
	}

	.search-input {
		flex: 1;
		padding-left: 38px;
	}

	.search-btn {
		flex-shrink: 0;
	}

	.search-hint {
		font-size: var(--text-xs);
		color: var(--text-muted);
		margin-top: var(--space-xs);
	}

	.suggestions-dropdown {
		position: absolute;
		top: 100%;
		left: 0;
		right: 0;
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: 0 0 var(--radius-md) var(--radius-md);
		list-style: none;
		padding: 0;
		margin: 0;
		max-height: 240px;
		overflow-y: auto;
		z-index: 100;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
	}

	.suggestion-item {
		padding: var(--space-sm) var(--space-md);
		cursor: pointer;
		font-size: var(--text-sm);
		color: var(--text-primary);
		transition: background var(--transition-fast);
	}

	.suggestion-item:hover,
	.suggestion-item.selected {
		background: var(--bg-tertiary);
	}

	.search-loading {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		margin-top: var(--space-md);
		color: var(--text-muted);
		font-size: var(--text-sm);
	}

	.spinner {
		display: inline-block;
		width: 16px;
		height: 16px;
		border: 2px solid var(--border-default);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.search-results {
		margin-top: var(--space-lg);
	}

	.results-summary {
		font-size: var(--text-sm);
		color: var(--text-secondary);
		margin-bottom: var(--space-md);
	}

	.results-description {
		color: var(--text-muted);
	}

	.no-results {
		text-align: center;
		padding: var(--space-xl);
		color: var(--text-muted);
		font-size: var(--text-sm);
	}

	.results-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.result-card {
		padding: var(--space-md);
	}

	.result-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: var(--space-sm);
	}

	.result-timestamp {
		font-size: var(--text-xs);
		color: var(--text-muted);
		font-family: var(--font-mono);
	}

	.result-fields {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.result-field {
		display: flex;
		gap: var(--space-sm);
		font-size: var(--text-xs);
	}

	.field-key {
		color: var(--text-muted);
		font-weight: 500;
		flex-shrink: 0;
	}

	.field-value {
		color: var(--text-primary);
		font-family: var(--font-mono);
		word-break: break-all;
	}
</style>
