import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getCyberChefStatus,
	getRecipes,
	buildRecipeUrl,
	type CyberChefStatus,
} from './cyberchef';

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

function mockFetchFailure(status = 500, body?: unknown): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: false,
			status,
			json: () => (body !== undefined ? Promise.resolve(body) : Promise.reject(new Error('no body'))),
		}),
	);
}

function mockFetchNetworkError(): void {
	vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('cyberchef API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getCyberChefStatus --------------------------------------------------

	describe('getCyberChefStatus', () => {
		it('returns parsed status on success', async () => {
			const expected: CyberChefStatus = {
				available: true,
				version: '10.8.2',
				container_running: true,
				container_name: 'nettap-cyberchef',
			};
			mockFetchSuccess(expected);

			const result = await getCyberChefStatus();

			expect(fetch).toHaveBeenCalledWith('/api/cyberchef/status');
			expect(result).toEqual(expected);
		});

		it('returns offline defaults on HTTP error', async () => {
			mockFetchFailure(503);

			const result = await getCyberChefStatus();

			expect(result.available).toBe(false);
			expect(result.version).toBe('');
			expect(result.container_running).toBe(false);
			expect(result.container_name).toBe('');
		});

		it('handles network failure gracefully', async () => {
			mockFetchNetworkError();

			await expect(getCyberChefStatus()).rejects.toThrow('Failed to fetch');
		});
	});

	// -- getRecipes ----------------------------------------------------------

	describe('getRecipes', () => {
		it('returns all recipes when no category is supplied', async () => {
			const expected = {
				recipes: [
					{
						name: 'Base64 Decode',
						description: 'Decode Base64 encoded data',
						category: 'decode',
						recipe_fragment: 'From_Base64',
					},
				],
				count: 1,
			};
			mockFetchSuccess(expected);

			const result = await getRecipes();

			expect(fetch).toHaveBeenCalledWith('/api/cyberchef/recipes');
			expect(result).toEqual(expected);
		});

		it('appends category query parameter when supplied', async () => {
			mockFetchSuccess({ recipes: [], count: 0 });

			await getRecipes('network');

			expect(fetch).toHaveBeenCalledWith('/api/cyberchef/recipes?category=network');
		});

		it('encodes special characters in the category parameter', async () => {
			mockFetchSuccess({ recipes: [], count: 0 });

			await getRecipes('data analysis');

			expect(fetch).toHaveBeenCalledWith('/api/cyberchef/recipes?category=data%20analysis');
		});

		it('returns empty list on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getRecipes();

			expect(result.recipes).toEqual([]);
			expect(result.count).toBe(0);
		});
	});

	// -- buildRecipeUrl ------------------------------------------------------

	describe('buildRecipeUrl', () => {
		it('sends correct POST body and returns URL', async () => {
			const expected = { url: 'http://localhost:8000/#recipe=From_Base64&input=SGVsbG8=' };
			mockFetchSuccess(expected);

			const result = await buildRecipeUrl('From_Base64', 'Hello');

			expect(fetch).toHaveBeenCalledWith('/api/cyberchef/url', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					recipe_fragment: 'From_Base64',
					input_data: 'Hello',
				}),
			});
			expect(result).toEqual(expected);
		});

		it('throws an error on HTTP failure with error body', async () => {
			mockFetchFailure(400, { error: 'Invalid recipe fragment' });

			await expect(buildRecipeUrl('bad_recipe', 'data')).rejects.toThrow('Invalid recipe fragment');
		});

		it('throws a fallback error when response body is not JSON', async () => {
			vi.stubGlobal(
				'fetch',
				vi.fn().mockResolvedValue({
					ok: false,
					status: 502,
					json: () => Promise.reject(new Error('not json')),
				}),
			);

			await expect(buildRecipeUrl('recipe', 'data')).rejects.toThrow(
				'Failed to build recipe URL (HTTP 502)',
			);
		});

		it('throws on network failure', async () => {
			mockFetchNetworkError();

			await expect(buildRecipeUrl('recipe', 'data')).rejects.toThrow('Failed to fetch');
		});
	});
});
