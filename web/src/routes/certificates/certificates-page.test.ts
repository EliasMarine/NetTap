import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import CertificatesPage from './+page.svelte';
import { refreshPage } from '$lib/stores/pageRefresh';
import type { CertificateOverview, CertSite } from '$lib/api/certificates';
import { OVERVIEW, OVERVIEW_EMPTY } from '../../../e2e/visual/fixtures/certificates';

// NET-154: one overview request; a failure never reads as "nothing needs a look", and figures
// from an earlier window are never shown as the window the pills now select.

const REGISTRY = {
	devices: [
		{ mac: 'aa', display_name: 'Work laptop', ips: ['192.168.1.42'], last_seen: '2026-11-05T00:00:00Z' },
		{ mac: 'bb', display_name: 'Office NAS', ips: ['192.168.1.10'], last_seen: '2026-11-05T00:00:00Z' },
	],
	total: 2,
};

type Reply = unknown | ((url: string) => unknown);

function stubDaemon(replies: Record<string, Reply>): void {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const reply = replies[url.split('?')[0]];
			const body = typeof reply === 'function' ? reply(url) : reply;
			return body
				? { ok: true, status: 200, json: async () => body }
				: { ok: false, status: 503, json: async () => ({ error: 'Certificate data is unavailable right now.' }) };
		}),
	);
}

// "Needs a look" is also a card title and a filter, so find the one inside a KPI card
const kpi = (label: string) => screen.getAllByText(label).map((e) => e.closest('.kpi')).find(Boolean) as HTMLElement;

describe('Certificates page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows loading, not zero counts, before the first answer', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(CertificatesPage);
		expect(kpi('Certificates seen')).toHaveTextContent('—');
		expect(screen.getAllByRole('status')[0]).toHaveAttribute('aria-busy', 'true');
	});

	it("says the load failed, with the daemon's reason, instead of nothing needs a look", async () => {
		stubDaemon({ '/api/devices/registry': REGISTRY });
		render(CertificatesPage);
		await vi.waitFor(() => expect(screen.getAllByText("Couldn't load certificate data: the request failed.").length).toBe(3));
		expect(screen.getAllByText('Certificate data is unavailable right now.').length).toBe(3);
		expect(screen.queryByText('Nothing needs a look')).not.toBeInTheDocument();
		expect(kpi('Needs a look')).toHaveTextContent('—');
	});

	it('says nothing needs a look only when the overview loaded with no findings', async () => {
		stubDaemon({ '/api/certificates/overview': OVERVIEW_EMPTY, '/api/devices/registry': REGISTRY });
		render(CertificatesPage);
		await screen.findByText('Nothing needs a look');
		expect(screen.getByText('No certificates from your own devices')).toBeInTheDocument();
		expect(kpi('Needs a look')).toHaveTextContent('0');
	});

	it('lists findings most serious first, naming devices from the registry', async () => {
		stubDaemon({ '/api/certificates/overview': OVERVIEW, '/api/devices/registry': REGISTRY });
		render(CertificatesPage);
		const rows = await screen.findAllByRole('button', { name: /got a certificate|used the certificate|connects to|runs out/ });
		expect(rows[0]).toHaveTextContent('Work laptop got a certificate for www.example.com from an unexpected authority');
		expect(rows.at(-1)).toHaveTextContent("Office NAS's certificate for nas.home.example runs out in 12 days");
		expect(kpi('Needs a look')).toHaveTextContent('5');
		expect(kpi('Needs a look')).toHaveTextContent('1 high · 2 medium · 2 low');
		expect(kpi("Your devices' certificates")).toHaveTextContent('on 3 services · soonest runs out in 12 days');
		expect(screen.getByText(/1 certificate has no stored details/)).toBeInTheDocument();
	});

	it('opens a finding in the drawer with links to drill down, and closes on Escape', async () => {
		stubDaemon({ '/api/certificates/overview': OVERVIEW, '/api/devices/registry': REGISTRY });
		render(CertificatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: /from an unexpected authority/ }));
		const drawer = screen.getByRole('complementary', { name: 'Certificate details' });
		expect(within(drawer).getByText('What to do')).toBeInTheDocument();
		expect(within(drawer).getByRole('link', { name: 'Work laptop' })).toHaveAttribute('href', '/devices/192.168.1.42');
		expect(within(drawer).getByRole('link', { name: /View connections/ })).toHaveAttribute('href', '/connections?ip=203.0.113.10');
		expect(within(drawer).getByRole('link', { name: /Check it now/ })).toHaveAttribute('href', '/tools/ssl-cert?host=www.example.com');
		expect(within(drawer).getByText('Example Unknown')).toBeInTheDocument();
		await fireEvent.keyDown(window, { key: 'Escape' });
		expect(screen.queryByRole('complementary', { name: 'Certificate details' })).not.toBeInTheDocument();
	});

	it('keeps the loaded window on screen and names both when a different window fails', async () => {
		stubDaemon({ '/api/certificates/overview': OVERVIEW, '/api/devices/registry': REGISTRY });
		render(CertificatesPage);
		await fireEvent.click(screen.getByRole('button', { name: '24h' }));
		await screen.findAllByText('last 24 hours');

		stubDaemon({ '/api/devices/registry': REGISTRY });
		await fireEvent.click(screen.getByRole('button', { name: '30d' }));
		await screen.findByText(/Couldn't load the last 30 days; showing the last 24 hours loaded at/);
		expect(kpi('Certificates seen')).toHaveTextContent('last 24 hours');
		expect(kpi('Certificates seen')).not.toHaveTextContent('last 30 days');
	});

	it('reports ok, partial and failed to the top bar', async () => {
		stubDaemon({ '/api/certificates/overview': OVERVIEW, '/api/devices/registry': REGISTRY });
		render(CertificatesPage);
		await screen.findAllByText('www.example.com');
		expect(await refreshPage()).toBe('ok');
		stubDaemon({ '/api/certificates/overview': OVERVIEW });
		expect(await refreshPage()).toBe('partial');
		stubDaemon({});
		expect(await refreshPage()).toBe('failed');
		expect(screen.getByText(/Couldn't refresh certificate data; showing the last figures loaded/)).toBeInTheDocument();
	});

	it('sorts the whole site list before cutting a page, and filters to what needs a look', async () => {
		const many: CertSite[] = Array.from({ length: 30 }, (_, i) => ({
			...OVERVIEW.sites[0],
			id: `s${i}.example`,
			name: `s${i}.example`,
			sessions: (i * 7) % 30 + 1,
			worst: null,
		}));
		const data: CertificateOverview = { ...OVERVIEW, sites: many, sites_total: 30 };
		stubDaemon({ '/api/certificates/overview': data, '/api/devices/registry': REGISTRY });
		const { container } = render(CertificatesPage);
		await screen.findByText(/Showing|of 30/);
		const sessions = () =>
			[...container.querySelectorAll('#cert-sites tbody tr')].map((r) => Number(r.querySelectorAll('td')[4]?.textContent?.replace(/,/g, '')));
		expect(sessions()[0]).toBe(30); // busiest first across all 30, not just the first page
		const header = [...container.querySelectorAll('#cert-sites th button')].find((b) => b.textContent?.trim().startsWith('Sessions'))!;
		await fireEvent.click(header);
		expect(sessions()[0]).toBe(1);
		await fireEvent.click(screen.getByRole('button', { name: 'Needs a look' }));
		expect(screen.getByText('No sites match')).toBeInTheDocument();
	});
});

// OLD CODE START — 2026-11-05 NET-154: tests of the previous page (four list endpoints, the MITM
// banner, the Expiring and Self-signed filters and the certificate dialog), all replaced.
// import { describe, it, expect, vi, afterEach } from 'vitest';
// import { render, screen, fireEvent } from '@testing-library/svelte';
// import CertificatesPage from './+page.svelte';
// import { refreshPage } from '$lib/stores/pageRefresh';
//
// // #96: a failed request returned an empty list, so the page said "No certificates found"
// // and left out the MITM warning as if no certificate issuer had changed.
//
// function stubDaemon(replies: Record<string, unknown>): void {
// 	vi.stubGlobal(
// 		'fetch',
// 		vi.fn(async (url: string) => {
// 			const body = replies[url.split('?')[0]];
// 			return body
// 				? { ok: true, status: 200, json: async () => body }
// 				: { ok: false, status: 503, json: async () => ({}) };
// 		}),
// 	);
// }
//
// describe('Certificates page', () => {
// 	afterEach(() => {
// 		vi.unstubAllGlobals();
// 	});
//
// 	it('says the certificates and issuer check failed instead of "none found"', async () => {
// 		stubDaemon({});
// 		render(CertificatesPage);
// 		await vi.waitFor(() => expect(screen.getByText("Couldn't load certificates: the request failed.")).toBeInTheDocument());
// 		expect(screen.queryByText('No certificates found for the selected filter.')).not.toBeInTheDocument();
// 		expect(screen.getByText(/Couldn't check for issuer changes/)).toBeInTheDocument();
// 	});
//
// 	it('still says none were found when the requests succeed with none', async () => {
// 		const empty = { from: '', to: '', certificates: [], count: 0 };
// 		stubDaemon({
// 			'/api/certificates': empty,
// 			'/api/certificates/issuer-changes': { from: '', to: '', changes: [], count: 0 },
// 		});
// 		render(CertificatesPage);
// 		await vi.waitFor(() => expect(screen.getByText('No certificates found for the selected filter.')).toBeInTheDocument());
// 		expect(screen.queryByText(/Couldn't/)).not.toBeInTheDocument();
// 	});
//
// 	// sort sweep on the G11: ascending Source put the 19 certificates with no source IP first
// 	it('sorts Source by number with blanks last both ways', async () => {
// 		const cert = (id: string, source_ip: string) => ({
// 			_id: id, timestamp: '', domain: `${id}.example`, server_name: '', subject: '', issuer: 'CA',
// 			not_before: '', not_after: '', tls_version: '', hash_sha256: id, source_ip, destination_ip: '',
// 			destination_port: 443, validation_status: 'ok', status: 'valid', days_until_expiry: null,
// 		});
// 		stubDaemon({
// 			'/api/certificates': { from: '', to: '', count: 3, certificates: [cert('a', '10.0.0.26'), cert('b', ''), cert('c', '10.0.0.235')] },
// 			'/api/certificates/issuer-changes': { from: '', to: '', changes: [], count: 0 },
// 		});
// 		const { container } = render(CertificatesPage);
// 		await vi.waitFor(() => expect(screen.getByText('a.example')).toBeInTheDocument());
// 		const sources = () => [...container.querySelectorAll('tbody tr')].map((r) => r.querySelectorAll('td')[5]?.textContent?.trim());
// 		// DataTable: the sort control is the header's button
// 		const source = [...container.querySelectorAll('th button')].find((b) => b.textContent?.trim().startsWith('Source'))!;
//
// 		await fireEvent.click(source);
// 		const first = sources();
// 		await fireEvent.click(source);
// 		const second = sources();
// 		const asc = first[0] === '10.0.0.26' ? first : second;
// 		const desc = asc === first ? second : first;
// 		expect(asc).toEqual(['10.0.0.26', '10.0.0.235', '']);
// 		expect(desc).toEqual(['10.0.0.235', '10.0.0.26', '']);
// 	});
// });
//
// const CERT = {
// 	_id: 'c1', timestamp: '', domain: 'nas.example', server_name: '', subject: 'CN=nas', issuer: 'Home CA',
// 	not_before: '', not_after: '', tls_version: 'TLSv12', hash_sha256: 'abc', source_ip: '10.0.0.5', destination_ip: '',
// 	destination_port: 443, validation_status: 'ok', status: 'valid', days_until_expiry: null,
// };
// const CHANGES = { from: '', to: '', changes: [], count: 0 };
// const STATS = { total_certs: 1, expiring_count: 0, expired_count: 0, self_signed_count: 0, issuer_changes_count: 0, from: '', to: '' };
//
// // PLAN §5.5: the loader is the top bar's Refresh; it keeps the chosen filter and says what failed.
// describe('Certificates page — refresh contract', () => {
// 	afterEach(() => {
// 		vi.unstubAllGlobals();
// 	});
//
// 	it('shows the loading state, not zero counts, before the first answer', () => {
// 		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
// 		render(CertificatesPage);
// 		expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true');
// 		expect(screen.getByText('Total certificates').closest('.kpi')).toHaveTextContent('—');
// 	});
//
// 	it('reports ok, partial and failed to the top bar', async () => {
// 		const list = { from: '', to: '', certificates: [CERT], count: 1 };
// 		stubDaemon({ '/api/certificates': list, '/api/certificates/issuer-changes': CHANGES, '/api/certificates/stats': STATS });
// 		render(CertificatesPage);
// 		await screen.findByText('nas.example');
// 		expect(await refreshPage()).toBe('ok');
//
// 		stubDaemon({ '/api/certificates': list, '/api/certificates/issuer-changes': CHANGES });
// 		expect(await refreshPage()).toBe('partial');
// 		expect(screen.getByText('Counts unavailable')).toBeInTheDocument();
//
// 		stubDaemon({});
// 		expect(await refreshPage()).toBe('failed');
// 	});
//
// 	it('keeps the chosen status filter when the page is refreshed', async () => {
// 		stubDaemon({ '/api/certificates/expiring': { from: '', to: '', certificates: [], count: 0 }, '/api/certificates/issuer-changes': CHANGES });
// 		render(CertificatesPage);
// 		await fireEvent.click(screen.getByRole('button', { name: 'Expiring' }));
// 		await screen.findByText('No certificates found for the selected filter.');
// 		const calls = vi.mocked(fetch).mock.calls.length;
//
// 		await refreshPage();
// 		const urls = vi.mocked(fetch).mock.calls.slice(calls).map(([u]) => String(u).split('?')[0]);
// 		expect(urls).toContain('/api/certificates/expiring');
// 		expect(urls).not.toContain('/api/certificates');
// 		expect(screen.getByRole('button', { name: 'Expiring' })).toHaveAttribute('aria-pressed', 'true');
// 	});
//
// 	it('opens a certificate from its row and closes on Escape', async () => {
// 		stubDaemon({ '/api/certificates': { from: '', to: '', certificates: [CERT], count: 1 }, '/api/certificates/issuer-changes': CHANGES });
// 		render(CertificatesPage);
// 		await fireEvent.click(await screen.findByRole('button', { name: 'Open certificate for nas.example' }));
// 		expect(screen.getByRole('dialog', { name: 'Certificate details' })).toHaveTextContent('Home CA');
// 		await fireEvent.keyDown(window, { key: 'Escape' });
// 		expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
// 	});
// });
// OLD CODE END
