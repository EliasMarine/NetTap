import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import Page from './+page.svelte';
import { expectNoNestedInteractive } from '../../../tests/nested-interactive';

/** NET-262: the DNS page's "Compare resolvers" tab. */
vi.mock('$app/stores', () => ({
	page: { subscribe: (fn: (v: { url: URL }) => void) => (fn({ url: new URL('http://localhost/tools/dns-recon') }), () => {}) },
}));

// The daemon's reply to the real dig output in daemon/tests/dig_compare_fixtures.py (setup.ui.com A on the G11)
const REPLY = {
	name: 'setup.ui.com',
	record_type: 'A',
	results: [
		{
			resolver: '192.168.1.1',
			status: 'NOERROR',
			answers: [{ name: 'setup.ui.com.', ttl: 0, class: 'IN', type: 'A', value: '192.168.1.1', key: 'setup.ui.com IN A 192.168.1.1', scope: 'private' }],
			ttl: 0,
			latency_ms: 0,
			error: null,
		},
		{
			resolver: '1.1.1.1',
			status: 'NOERROR',
			answers: [
				{ name: 'setup.ui.com.', ttl: 32, class: 'IN', type: 'A', value: '3.169.231.76', key: 'setup.ui.com IN A 3.169.231.76', scope: 'public' },
				{ name: 'setup.ui.com.', ttl: 32, class: 'IN', type: 'A', value: '3.169.231.111', key: 'setup.ui.com IN A 3.169.231.111', scope: 'public' },
			],
			ttl: 32,
			latency_ms: 8,
			error: null,
		},
		{ resolver: '192.0.2.53', status: null, answers: [], ttl: null, latency_ms: null, error: 'No reply from NetTap' },
	],
};

function stubFetch(body: unknown, ok = true) {
	const fetch = vi.fn(async (_url: string, _init?: RequestInit) => ({ ok, status: ok ? 200 : 503, json: async () => body }));
	vi.stubGlobal('fetch', fetch);
	return fetch;
}

async function openCompare() {
	render(Page);
	await fireEvent.click(screen.getByRole('tab', { name: 'Compare resolvers' }));
}

async function fill(name: string, rows: [string, string][]) {
	await fireEvent.input(screen.getByLabelText('Name'), { target: { value: name } });
	for (const [i, [ip, label]] of rows.entries()) {
		if (!screen.queryByLabelText(`Resolver ${i + 1} address`)) await fireEvent.click(screen.getByRole('button', { name: 'Add resolver' }));
		await fireEvent.input(screen.getByLabelText(`Resolver ${i + 1} address`), { target: { value: ip } });
		await fireEvent.input(screen.getByLabelText(`Resolver ${i + 1} label`), { target: { value: label } });
	}
}

describe('DNS page: Compare resolvers tab', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		localStorage.clear();
	});

	it('keeps the lookup as the first tab and shows the compare form on its own tab', async () => {
		render(Page);
		expect(screen.getByRole('tab', { name: 'Lookup' })).toHaveAttribute('aria-selected', 'true');
		expect(screen.getByRole('button', { name: 'Lookup' })).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('tab', { name: 'Compare resolvers' }));
		expect(screen.getByRole('tabpanel')).toHaveAttribute('id', 'dns-panel-compare');
		expect(screen.getByText('Choose the resolvers')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Compare' })).toBeDisabled();
	});

	it('shows the loading state while the resolvers are asked', async () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		await openCompare();
		await fill('setup.ui.com', [['192.168.1.1', '']]);
		await fireEvent.click(screen.getByRole('button', { name: 'Compare' }));
		expect(within(screen.getByRole('tabpanel')).getByRole('status')).toHaveTextContent('Asking each resolver');
	});

	it('sends only the addresses, then shows the verdict and a sortable table with labels', async () => {
		const fetch = stubFetch(REPLY);
		await openCompare();
		await fireEvent.change(screen.getByLabelText('Record type'), { target: { value: 'A' } });
		await fill('setup.ui.com', [
			['192.168.1.1', 'Router'],
			[' 1.1.1.1 ', ''],
			['192.0.2.53', 'VPN'],
		]);
		await fireEvent.click(screen.getByRole('button', { name: 'Compare' }));

		expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({
			name: 'setup.ui.com',
			record_type: 'A',
			resolvers: ['192.168.1.1', '1.1.1.1', '192.0.2.53'],
		});
		const verdict = await screen.findByText(/^Resolvers disagree/);
		expect(verdict).toHaveTextContent(
			'Resolvers disagree: Router returns 192.168.1.1 (private); 1.1.1.1 returns 3.169.231.76 (public), 3.169.231.111 (public).'
		);
		expect(screen.getByText('This looks like split DNS.')).toBeInTheDocument();
		expect(screen.getByText(/^VPN did not reply\./)).toBeInTheDocument();

		const table = screen.getByRole('table', { name: 'Resolver replies' });
		expect(within(table).getAllByRole('columnheader').every((th) => th.hasAttribute('aria-sort'))).toBe(true);
		expect(within(table).getByText('Router')).toBeInTheDocument();
		expect(within(table).getByText('No reply')).toBeInTheDocument();
		expect(within(table).getByText('No reply from NetTap')).toBeInTheDocument();
		expectNoNestedInteractive(document.body);

		// the list is kept in this browser for the next visit, labels included
		expect(JSON.parse(localStorage.getItem('nettap-dns-compare-resolvers') ?? '[]')).toEqual([
			{ ip: '192.168.1.1', label: 'Router' },
			{ ip: ' 1.1.1.1 ', label: '' },
			{ ip: '192.0.2.53', label: 'VPN' },
		]);
	});

	it('shows the error state with the daemon reason when the compare fails', async () => {
		stubFetch({ error: 'DNS reconnaissance is busy. Try again in a moment.' }, false);
		await openCompare();
		await fill('setup.ui.com', [['192.168.1.1', '']]);
		await fireEvent.click(screen.getByRole('button', { name: 'Compare' }));
		expect(await screen.findByText('The compare failed')).toBeInTheDocument();
		expect(screen.getByText('DNS reconnaissance is busy. Try again in a moment.')).toBeInTheDocument();
	});

	it('adds rows up to six and removes them, keeping at least one', async () => {
		await openCompare();
		const add = screen.getByRole('button', { name: 'Add resolver' });
		for (let i = 0; i < 4; i++) await fireEvent.click(add);
		expect(screen.getByLabelText('Resolver 6 address')).toBeInTheDocument();
		expect(add).toBeDisabled();
		for (let i = 6; i > 1; i--) await fireEvent.click(screen.getByRole('button', { name: `Remove resolver ${i}` }));
		expect(screen.queryByLabelText('Resolver 2 address')).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Remove resolver 1' })).toBeDisabled();
	});

	it('starts from the resolver list saved in this browser', async () => {
		localStorage.setItem('nettap-dns-compare-resolvers', JSON.stringify([{ ip: '9.9.9.9', label: 'Quad9' }]));
		await openCompare();
		await vi.waitFor(() => expect(screen.getByLabelText('Resolver 1 address')).toHaveValue('9.9.9.9'));
		expect(screen.getByLabelText('Resolver 1 label')).toHaveValue('Quad9');
		expect(screen.queryByLabelText('Resolver 2 address')).not.toBeInTheDocument();
	});
});
