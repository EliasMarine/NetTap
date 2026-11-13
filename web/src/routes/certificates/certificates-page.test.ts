import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import type { writable } from 'svelte/store';
import CertificatesPage from './+page.svelte';
import { refreshPage } from '$lib/stores/pageRefresh';
import type { CertificateOverview, CertSite } from '$lib/api/certificates';
import { OVERVIEW, OVERVIEW_EMPTY } from '../../../e2e/visual/fixtures/certificates';
import { LAN_POLICY } from '../../../e2e/visual/fixtures/drilldown';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

// NET-160: the page reads ?site=&server=&from=&to= from the URL
const pageStore = vi.hoisted(() => ({ value: null as unknown as ReturnType<typeof writable> }));
vi.mock('$app/stores', async () => {
	const { writable: w } = await import('svelte/store');
	pageStore.value = w({ url: new URL('http://localhost/certificates') });
	return { page: pageStore.value };
});
const openUrl = (search: string) => pageStore.value.set({ url: new URL(`http://localhost/certificates${search}`) });

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
		openUrl('');
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
		// OLD CODE START: stubDaemon({ '/api/certificates/overview': OVERVIEW, '/api/devices/registry': REGISTRY }); OLD CODE END
		// NET-160: a device link goes to its device page once the LAN policy says it is on your network
		stubDaemon({ '/api/certificates/overview': OVERVIEW, '/api/devices/registry': REGISTRY, '/api/network/lan': LAN_POLICY });
		render(CertificatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: /from an unexpected authority/ }));
		const drawer = screen.getByRole('complementary', { name: 'Certificate details' });
		expect(within(drawer).getByText('What to do')).toBeInTheDocument();
		// OLD CODE START: expect(within(drawer).getByRole('link', { name: 'Work laptop' })).toHaveAttribute('href', '/devices/192.168.1.42'); OLD CODE END
		await vi.waitFor(() => expect(within(drawer).getByRole('link', { name: 'Work laptop' })).toHaveAttribute('href', '/devices/192.168.1.42'));
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

// NET-160: the address and domain pages link here with a site and/or server and their window
describe('Certificates page — drill-down filter', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		openUrl('');
	});

	const WWW = OVERVIEW.sites.find((x) => x.name === 'www.example.com')!;
	const site = (over: Partial<CertSite>): CertSite => ({ ...WWW, ...over });
	const only = (sites: CertSite[]): CertificateOverview => ({ ...OVERVIEW, sites, sites_total: sites.length, findings: [], findings_total: 0 });
	const overviewCalls = () =>
		vi.mocked(fetch).mock.calls.map(([u]) => new URL(String(u), 'http://x')).filter((u) => u.pathname === '/api/certificates/overview');

	it('sends the site, server and the link window, and shows the window as Custom', async () => {
		// a fortnight ago: the default 7 days would never reach it
		openUrl('?site=www.example.com&server=203.0.113.10&from=2026-10-20T08:00:00Z&to=2026-10-21T08:00:00Z');
		stubDaemon({ '/api/certificates/overview': only([WWW]), '/api/devices/registry': REGISTRY, '/api/network/lan': LAN_POLICY });
		render(CertificatesPage);
		await vi.waitFor(() => expect(overviewCalls().length).toBe(1));
		expect(Object.fromEntries(overviewCalls()[0].searchParams)).toEqual({
			from: '2026-10-20T08:00:00.000Z',
			to: '2026-10-21T08:00:00.000Z',
			site: 'www.example.com',
			server: '203.0.113.10',
		});
		expect(screen.getByRole('button', { name: 'Custom' })).toHaveAttribute('aria-pressed', 'true');
		expect(await screen.findByText(/Showing only the site www.example.com served by 203.0.113.10/)).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Show all certificates' })).toHaveAttribute('href', '/certificates');
		await vi.waitFor(() => expect(kpi('Certificates seen')).toHaveTextContent(/window 20 Oct, \d\d:\d\d to 21 Oct, \d\d:\d\d/));
	});

	// NET-249: a chart's trailing slot is a one-millisecond window; it must not fall back to 7 days
	it('loads exactly a link window with from == to, as Custom', async () => {
		openUrl('?site=www.example.com&from=2026-10-20T08:00:00.000Z&to=2026-10-20T08:00:00.000Z');
		stubDaemon({ '/api/certificates/overview': only([WWW]), '/api/devices/registry': REGISTRY, '/api/network/lan': LAN_POLICY });
		render(CertificatesPage);
		await vi.waitFor(() => expect(overviewCalls().length).toBe(1));
		expect(Object.fromEntries(overviewCalls()[0].searchParams)).toMatchObject({ from: '2026-10-20T08:00:00.000Z', to: '2026-10-20T08:00:00.000Z' });
		expect(screen.getByRole('button', { name: 'Custom' })).toHaveAttribute('aria-pressed', 'true');
	});

	it('opens the one matching site, linking its name to the domain page', async () => {
		openUrl('?site=www.example.com&from=2026-11-05T00:00:00Z&to=2026-11-06T00:00:00Z');
		stubDaemon({ '/api/certificates/overview': only([WWW]), '/api/devices/registry': REGISTRY, '/api/network/lan': LAN_POLICY });
		const { container } = render(CertificatesPage);
		const drawer = await screen.findByRole('complementary', { name: 'Certificate details' });
		expect(within(drawer).getByRole('heading', { name: 'www.example.com' })).toBeInTheDocument();
		expect(within(drawer).getByRole('link', { name: 'Open domain page' })).toHaveAttribute('href', '/domain/www.example.com');
		await vi.waitFor(() => expect(within(drawer).getByRole('link', { name: '203.0.113.10' })).toHaveAttribute('href', '/address/203.0.113.10'));
		expect(within(drawer).getByRole('link', { name: 'Work laptop' })).toHaveAttribute('href', '/devices/192.168.1.42');
		expectNoNestedInteractive(container);
	});

	it.each([
		['IPv4', '203.0.113.50', '/address/203.0.113.50'],
		['IPv6', '2001:db8::5', '/address/2001%3Adb8%3A%3A5'],
	])('links a site with no name (%s) to its server, never to a domain page', async (_v, server, href) => {
		openUrl(`?server=${encodeURIComponent(server)}`);
		const noName = site({ id: `no-sni:${server}`, name: null, server, servers: [server] });
		stubDaemon({ '/api/certificates/overview': only([noName]), '/api/devices/registry': REGISTRY, '/api/network/lan': LAN_POLICY });
		render(CertificatesPage);
		const drawer = await screen.findByRole('complementary', { name: 'Certificate details' });
		expect(within(drawer).getByRole('link', { name: 'Open address page' })).toHaveAttribute('href', href);
		expect(within(drawer).queryByRole('link', { name: 'Open domain page' })).not.toBeInTheDocument();
		expect(overviewCalls()[0].searchParams.get('server')).toBe(server);
	});

	it('leaves the choice to you when the filter matches several sites', async () => {
		openUrl('?server=203.0.113.10');
		stubDaemon({ '/api/certificates/overview': only([OVERVIEW.sites[0], OVERVIEW.sites[1]]), '/api/devices/registry': REGISTRY, '/api/network/lan': LAN_POLICY });
		render(CertificatesPage);
		await screen.findByText(/Showing only certificates served by 203.0.113.10/);
		expect(screen.queryByRole('complementary', { name: 'Certificate details' })).not.toBeInTheDocument();
	});

	// NET-160 slice 2a: the device column was hard-wired to /devices/, so an internet server opened a device page that can't exist
	it("links a device's server where it drills down: an internet address to its address page", async () => {
		const [lan] = OVERVIEW.devices;
		const overview = { ...OVERVIEW, devices: [lan, { ...lan, id: 'internet', server: '203.0.113.10' }] };
		stubDaemon({ '/api/certificates/overview': overview, '/api/devices/registry': REGISTRY, '/api/network/lan': LAN_POLICY });
		const { container } = render(CertificatesPage);
		const table = await screen.findByRole('table', { name: "Your devices' certificates" });
		await vi.waitFor(() => expect(within(table).getByRole('link', { name: '203.0.113.10' })).toHaveAttribute('href', '/address/203.0.113.10'));
		expect(within(table).getByRole('link', { name: 'Office NAS' })).toHaveAttribute('href', '/devices/192.168.1.10');
		expectNoNestedInteractive(container);
	});

	it('ignores an unreadable window and keeps the 7-day default', async () => {
		openUrl('?site=www.example.com&from=yesterday&to=today');
		stubDaemon({ '/api/certificates/overview': OVERVIEW, '/api/devices/registry': REGISTRY, '/api/network/lan': LAN_POLICY });
		render(CertificatesPage);
		await vi.waitFor(() => expect(overviewCalls().length).toBe(1));
		const q = overviewCalls()[0].searchParams;
		expect(Date.parse(q.get('to')!) - Date.parse(q.get('from')!)).toBe(168 * 3_600_000);
		expect(screen.queryByRole('button', { name: 'Custom' })).not.toBeInTheDocument();
	});

	// NET-192 PR 4: the default is 7d, the fourth range, found by value
	it('opens an unknown ?range= on its own 7-day default', async () => {
		openUrl('?range=15m');
		stubDaemon({ '/api/certificates/overview': OVERVIEW, '/api/devices/registry': REGISTRY, '/api/network/lan': LAN_POLICY });
		render(CertificatesPage);
		await vi.waitFor(() => expect(overviewCalls().length).toBe(1));
		const q = overviewCalls()[0].searchParams;
		expect(Date.parse(q.get('to')!) - Date.parse(q.get('from')!)).toBe(168 * 3_600_000);
		expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
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
