import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import SearchBar from './SearchBar.svelte';

// #96: a failed search read as "0 results ... No results found"

function stubSearch(reply: { ok: boolean; status: number; body?: unknown }): void {
	vi.stubGlobal('fetch', vi.fn(async () => ({ ok: reply.ok, status: reply.status, json: async () => reply.body })));
}

async function search(text: string): Promise<void> {
	await fireEvent.input(screen.getByPlaceholderText('Search your network...'), { target: { value: text } });
	await fireEvent.click(screen.getByRole('button', { name: 'Search' }));
}

describe('SearchBar', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('says the search failed instead of "No results found"', async () => {
		stubSearch({ ok: false, status: 503 });
		render(SearchBar);
		await search('dns to 8.8.8.8');
		expect(await screen.findByText("Couldn't search: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText(/No results found/)).not.toBeInTheDocument();
	});

	it('still says "No results found" when the search really finds nothing', async () => {
		stubSearch({ ok: true, status: 200, body: { query: 'q', description: '', index: '', total: 0, results: [] } });
		render(SearchBar);
		await search('q');
		expect(await screen.findByText(/No results found/)).toBeInTheDocument();
	});
});
