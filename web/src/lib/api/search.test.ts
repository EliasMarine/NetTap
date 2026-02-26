import { describe, it, expect, vi, afterEach } from 'vitest';
import { executeSearch, getSearchSuggestions } from './search';

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

function mockFetchSuccess(body: unknown, status = 200): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: status >= 200 && status < 300,
			status,
			json: () => Promise.resolve(body),
		}),
	);
}

function mockFetchFailure(status = 500): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: false,
			status,
			json: () => Promise.reject(new Error('no body')),
		}),
	);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('search API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- executeSearch -------------------------------------------------------

	describe('executeSearch', () => {
		it('sends POST with query body and returns parsed results', async () => {
			const expected = {
				query: 'DNS queries to external servers',
				description: 'Searching DNS connections',
				index: 'zeek-dns-*',
				total: 5,
				results: [
					{ _id: 'abc1', _index: 'zeek-dns-2026.02', query: 'example.com' },
					{ _id: 'abc2', _index: 'zeek-dns-2026.02', query: 'evil.com' },
				],
			};
			mockFetchSuccess(expected);

			const result = await executeSearch('DNS queries to external servers');

			expect(fetch).toHaveBeenCalledWith('/api/search', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ query: 'DNS queries to external servers' }),
			});
			expect(result.total).toBe(5);
			expect(result.results).toHaveLength(2);
		});

		it('returns empty results on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await executeSearch('failing query');

			expect(result.total).toBe(0);
			expect(result.results).toEqual([]);
			expect(result.query).toBe('failing query');
		});

		it('preserves query string in fallback response', async () => {
			mockFetchFailure(502);

			const result = await executeSearch('some search');

			expect(result.query).toBe('some search');
			expect(result.description).toBe('');
			expect(result.index).toBe('');
		});

		it('returns results with correct _id and _index fields', async () => {
			const expected = {
				query: 'TLS connections',
				description: 'TLS handshake records',
				index: 'zeek-ssl-*',
				total: 1,
				results: [
					{ _id: 'tls-1', _index: 'zeek-ssl-2026.02', server_name: 'cdn.example.com' },
				],
			};
			mockFetchSuccess(expected);

			const result = await executeSearch('TLS connections');

			expect(result.results[0]._id).toBe('tls-1');
			expect(result.results[0]._index).toBe('zeek-ssl-2026.02');
		});
	});

	// -- getSearchSuggestions ------------------------------------------------

	describe('getSearchSuggestions', () => {
		it('sends GET with query parameter and returns suggestions', async () => {
			const expected = {
				suggestions: [
					{ text: 'DNS queries from 192.168.1.0/24' },
					{ text: 'DNS queries to external resolvers' },
				],
			};
			mockFetchSuccess(expected);

			const result = await getSearchSuggestions('DNS quer');

			expect(fetch).toHaveBeenCalledWith('/api/search/suggest?q=DNS+quer');
			expect(result.suggestions).toHaveLength(2);
			expect(result.suggestions[0].text).toBe('DNS queries from 192.168.1.0/24');
		});

		it('returns empty suggestions on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getSearchSuggestions('fail');

			expect(result.suggestions).toEqual([]);
		});

		it('URL-encodes special characters in partial query', async () => {
			mockFetchSuccess({ suggestions: [] });

			await getSearchSuggestions('src_ip=10.0.0.1 & port=443');

			const fetchCall = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(fetchCall).toContain('q=');
			expect(fetchCall).not.toContain('src_ip=10.0.0.1 & port=443');
		});

		it('handles empty partial query string', async () => {
			mockFetchSuccess({ suggestions: [] });

			const result = await getSearchSuggestions('');

			expect(result.suggestions).toEqual([]);
			expect(fetch).toHaveBeenCalledWith('/api/search/suggest?q=');
		});
	});
});
