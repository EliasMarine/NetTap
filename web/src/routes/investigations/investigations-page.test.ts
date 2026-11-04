import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
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

	it('says the list could not be loaded instead of "No investigations yet"', async () => {
		stubDaemon({});
		render(InvestigationsPage);
		await vi.waitFor(() => expect(screen.getByText(/^Couldn't load investigations/)).toBeInTheDocument());
		expect(screen.queryByText('No investigations yet')).not.toBeInTheDocument();
		expect(screen.getAllByText('—').length).toBeGreaterThan(0);
		expect(screen.queryByText('0')).not.toBeInTheDocument();
	});

	it('still says "No investigations yet" when there are none', async () => {
		stubDaemon({
			'/api/investigations': { investigations: [] },
			'/api/investigations/stats': { total: 0, by_status: {}, by_severity: {} },
		});
		render(InvestigationsPage);
		await vi.waitFor(() => expect(screen.getByText('No investigations yet')).toBeInTheDocument());
		expect(screen.queryByText(/Couldn't/)).not.toBeInTheDocument();
	});

	it('says a failed create failed, and keeps what was typed', async () => {
		const lists = vi.fn(async (url: string, init?: { method?: string }) => {
			const path = url.split('?')[0];
			if (path === '/api/investigations' && init?.method === 'POST') return { ok: false, status: 500, json: async () => ({}) };
			if (path === '/api/investigations') return { ok: true, status: 200, json: async () => ({ investigations: [] }) };
			if (path === '/api/investigations/stats')
				return { ok: true, status: 200, json: async () => ({ total: 0, by_status: {}, by_severity: {} }) };
			return { ok: false, status: 503, json: async () => ({}) };
		});
		vi.stubGlobal('fetch', lists);
		render(InvestigationsPage);
		await vi.waitFor(() => expect(screen.getByText('No investigations yet')).toBeInTheDocument());

		await fireEvent.click(screen.getByRole('button', { name: 'New investigation' }));
		const title = screen.getByPlaceholderText('Investigation title…') as HTMLInputElement;
		await fireEvent.input(title, { target: { value: 'Router scan' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Create investigation' }));

		await vi.waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent("Couldn't create the investigation"));
		expect((screen.getByPlaceholderText('Investigation title…') as HTMLInputElement).value).toBe('Router scan');
	});
});

