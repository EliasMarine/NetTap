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

export interface SearchSuggestion {
	text: string;
}

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

	if (!res.ok) {
		return {
			query,
			description: '',
			index: '',
			total: 0,
			results: [],
		};
	}

	return res.json();
}

/**
 * Get typeahead suggestions for a partial query string.
 */
export async function getSearchSuggestions(
	partial: string
): Promise<{ suggestions: SearchSuggestion[] }> {
	const qs = new URLSearchParams({ q: partial });
	const res = await fetch(`/api/search/suggest?${qs.toString()}`);

	if (!res.ok) {
		return { suggestions: [] };
	}

	return res.json();
}
