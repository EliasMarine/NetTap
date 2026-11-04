/**
 * Client-side API helpers for natural language search endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SearchResult {
	_id: string;
	_index: string;
	[key: string]: unknown;
}

export interface SearchResponse {
	query: string;
	description: string;
	index: string;
	total: number;
	results: SearchResult[];
}

// OLD CODE START — the daemon's suggest() returns plain strings (daemon/services/nl_search.py), never { text }
// export interface SearchSuggestion {
// 	text: string;
// }
// OLD CODE END

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Execute a natural language search query.
 * The daemon translates the query into OpenSearch DSL and returns results.
 */
export async function executeSearch(query: string): Promise<SearchResponse> {
	const res = await fetch('/api/search', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ query }),
	});

	// OLD CODE START — #96: a failed search read as "No results found"
	// if (!res.ok) {
	// 	return {
	// 		query,
	// 		description: '',
	// 		index: '',
	// 		total: 0,
	// 		results: [],
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Search failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Get typeahead suggestions for a partial query string.
 */
export async function getSearchSuggestions(
	partial: string
): Promise<{ suggestions: string[] }> {
	const qs = new URLSearchParams({ q: partial });
	const res = await fetch(`/api/search/suggest?${qs.toString()}`);

	if (!res.ok) {
		return { suggestions: [] };
	}

	return res.json();
}
