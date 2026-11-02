import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import InvestigationsPage from './+page.svelte';

// #96: a failed request returned an empty list and zero stats, so the page said
// "No Investigations" with 0 in every tab when nothing was loaded.

function stubDaemon(replies: Record<string, unknown>): void {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const body = replies[url.split('?')[0]];
			return body
				? { ok: true, status: 200, json: async () => body }
				: { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

describe('Investigations page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says the list could not be loaded instead of "No Investigations"', async () => {
		stubDaemon({});
		render(InvestigationsPage);
		await vi.waitFor(() => expect(screen.getByText("Couldn't load investigations")).toBeInTheDocument());
		expect(screen.queryByText('No Investigations')).not.toBeInTheDocument();
		expect(screen.getAllByText('—').length).toBeGreaterThan(0);
		expect(screen.queryByText('0')).not.toBeInTheDocument();
	});

	it('still says "No Investigations" when there are none', async () => {
		stubDaemon({
			'/api/investigations': { investigations: [] },
			'/api/investigations/stats': { total: 0, by_status: {}, by_severity: {} },
		});
		render(InvestigationsPage);
		await vi.waitFor(() => expect(screen.getByText('No Investigations')).toBeInTheDocument());
		expect(screen.queryByText(/Couldn't/)).not.toBeInTheDocument();
	});
});
