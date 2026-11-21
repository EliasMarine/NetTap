import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
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


// NET-349: the drawer is modal now, so its failures show inside it, kept per investigation
describe('Investigations — failures inside the drawer', () => {
	afterEach(() => vi.unstubAllGlobals());

	const inv = (id: string, title: string) => ({
		id, title, description: '', status: 'open', severity: 'medium', created_at: '2026-11-21T10:00:00Z',
		updated_at: '2026-11-21T10:00:00Z', alert_ids: [], device_ips: [], notes: [], tags: [],
	});

	async function openDrawer(title: string) {
		await fireEvent.click(screen.getByRole('button', { name: `Open investigation ${title}` }));
		await fireEvent.click(screen.getByRole('button', { name: 'View full details' }));
		return screen.getByRole('dialog', { name: title });
	}

	async function addNote(drawer: HTMLElement, text: string) {
		await fireEvent.click(within(drawer).getByRole('button', { name: 'Notes' }));
		await fireEvent.input(within(drawer).getByPlaceholderText('Add a note…'), { target: { value: text } });
		await fireEvent.click(within(drawer).getByRole('button', { name: 'Add note' }));
	}

	it("keeps B's failure in B's drawer when A's earlier save fails later, and never shows A's", async () => {
		let failA: () => void = () => {};
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string, init?: { method?: string }) => {
				const path = url.split('?')[0];
				const fail = { ok: false, status: 500, json: async () => ({}) };
				if (path === '/api/investigations/a/notes') return new Promise((r) => (failA = () => r(fail)));
				if (path === '/api/investigations/b/notes') return fail;
				if (path === '/api/investigations' && !init?.method)
					return { ok: true, status: 200, json: async () => ({ investigations: [inv('a', 'Router scan'), inv('b', 'Camera beacon')] }) };
				if (path === '/api/investigations/stats')
					return { ok: true, status: 200, json: async () => ({ total: 2, by_status: { open: 2 }, by_severity: { medium: 2 } }) };
				return fail;
			}),
		);
		render(InvestigationsPage);
		await vi.waitFor(() => expect(screen.getByRole('button', { name: 'Open investigation Router scan' })).toBeInTheDocument());

		const a = await openDrawer('Router scan');
		await addNote(a, 'checked the router');
		await fireEvent.click(within(a).getByRole('button', { name: 'Close' }));

		const b = await openDrawer('Camera beacon');
		await addNote(b, 'camera is fine');
		await vi.waitFor(() => expect(b).toHaveTextContent("Couldn't save the note: the request failed."));

		failA();
		await new Promise((r) => setTimeout(r, 0));
		expect(b).toHaveTextContent("Couldn't save the note: the request failed.");
		expect(screen.getAllByRole('alert')).toHaveLength(1);

		await fireEvent.click(within(b).getByRole('button', { name: 'Dismiss' }));
		expect(b).not.toHaveTextContent("Couldn't save the note");
	});
});
