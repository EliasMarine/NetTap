import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import LocalServicesPage from './+page.svelte';
import { refreshPage } from '$lib/stores/pageRefresh';
import { LOCAL_SERVICES, LOCAL_SERVICES_EMPTY } from '../../../e2e/visual/fixtures/local-services';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

// NET-264: one request per load; a failure never reads as "no announcements"
type Reply = unknown | ((url: string) => unknown);

function stubDaemon(reply: Reply) {
	const fetchMock = vi.fn(async (url: string) => {
		const body = url.startsWith('/api/local-services') ? (typeof reply === 'function' ? reply(url) : reply) : null;
		return body
			? { ok: true, status: 200, json: async () => body }
			: { ok: false, status: 503, json: async () => ({ error: 'Working this out took too long. Try a shorter time range.' }) };
	});
	vi.stubGlobal('fetch', fetchMock);
	return fetchMock;
}

const serviceCalls = (f: ReturnType<typeof stubDaemon>) => f.mock.calls.map((c) => String(c[0])).filter((u) => u.startsWith('/api/local-services'));
const table = () => screen.getByRole('table', { name: 'Local service announcements' });
const bodyRows = () => within(table()).getAllByRole('row').slice(1);

describe('Local services page', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('shows loading before the first answer, never an empty list', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(LocalServicesPage);
		expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true');
		expect(screen.queryByText('No announcements seen')).not.toBeInTheDocument();
	});

	it("says the load failed, with the daemon's reason", async () => {
		stubDaemon(null);
		render(LocalServicesPage);
		await vi.waitFor(() => expect(screen.getByText("Couldn't load local services: the request failed.")).toBeInTheDocument());
		expect(screen.getByText('Working this out took too long. Try a shorter time range.')).toBeInTheDocument();
		expect(screen.queryByText('No announcements seen')).not.toBeInTheDocument();
	});

	it('explains an empty window: multicast stays inside its VLAN', async () => {
		stubDaemon(LOCAL_SERVICES_EMPTY);
		render(LocalServicesPage);
		await vi.waitFor(() => expect(screen.getByText('No announcements seen')).toBeInTheDocument());
		expect(screen.getByText(/NetTap only sees the VLANs the mirror carries/)).toBeInTheDocument();
	});

	it('lists one row per sender, with the plain name beside the raw type', async () => {
		const f = stubDaemon(LOCAL_SERVICES);
		const { container } = render(LocalServicesPage);
		await vi.waitFor(() => expect(bodyRows()).toHaveLength(LOCAL_SERVICES.rows.length));
		// the last 24 hours by default
		const q = new URL(serviceCalls(f)[0], 'http://x').searchParams;
		expect(Date.parse(q.get('to')!) - Date.parse(q.get('from')!)).toBe(24 * 3_600_000);
		const router = bodyRows().find((r) => r.textContent?.includes('10.10.0.1'))!;
		expect(router).toHaveTextContent('AirPlay receiver');
		expect(router).toHaveTextContent('_airplay._tcp');
		expect(router).toHaveTextContent('Router');
		expect(within(router).getAllByRole('cell')[4]).toHaveTextContent(/^2$/);
		// an unknown type is its raw name, once
		const quic = bodyRows().find((r) => r.textContent?.includes('studio mac'))!;
		expect(within(quic).getAllByText('_asquic._udp')).toHaveLength(1);
		expect(screen.getByText('not yet known')).toBeInTheDocument();
		expectNoNestedInteractive(container);
	});

	it('links an IPv4 sender and leaves a link-local one as text', async () => {
		stubDaemon(LOCAL_SERVICES);
		render(LocalServicesPage);
		await vi.waitFor(() => expect(bodyRows().length).toBeGreaterThan(0));
		expect(screen.getAllByRole('link', { name: '192.168.1.154' })[0]).toHaveAttribute('href', expect.stringContaining('192.168.1.154'));
		expect(screen.queryByRole('link', { name: 'fe80::200:5eff:fe10:12' })).not.toBeInTheDocument();
		expect(screen.getByText('fe80::200:5eff:fe10:12')).toBeInTheDocument();
	});

	it("sends an SSDP row to its sender's announcements over the last 30 minutes", async () => {
		stubDaemon(LOCAL_SERVICES);
		render(LocalServicesPage);
		const link = await vi.waitFor(() => screen.getByRole('link', { name: 'See its announcements' }));
		const url = new URL(link.getAttribute('href')!, 'http://x');
		expect(url.pathname).toBe('/packets');
		expect(url.searchParams.get('filter')).toBe('ssdp && ip.src == 192.168.1.44');
		expect(Number(url.searchParams.get('to')) - Number(url.searchParams.get('from'))).toBe(1800);
		expect(screen.getByText('UPnP device (SSDP)')).toBeInTheDocument();
	});

	it('filters every column from one search box', async () => {
		stubDaemon(LOCAL_SERVICES);
		render(LocalServicesPage);
		await vi.waitFor(() => expect(bodyRows()).toHaveLength(LOCAL_SERVICES.rows.length));
		const search = screen.getByRole('searchbox', { name: 'Search announcements' });
		await fireEvent.input(search, { target: { value: 'hue' } });
		expect(bodyRows()).toHaveLength(1);
		await fireEvent.input(search, { target: { value: '02:00:5e:10:00:01' } });
		expect(bodyRows()).toHaveLength(1);
		await fireEvent.input(search, { target: { value: 'not yet' } });
		expect(bodyRows()).toHaveLength(1);
		await fireEvent.input(search, { target: { value: 'nothing like this' } });
		expect(screen.getByText('No announcements match your search.')).toBeInTheDocument();
	});

	it('says when the list was cut short', async () => {
		stubDaemon({ ...LOCAL_SERVICES, truncated: true });
		render(LocalServicesPage);
		await vi.waitFor(() => expect(screen.getByText(/may not hold every announcement/)).toBeInTheDocument());
	});

	it('asks for the range picked, and offers no range past 7 days', async () => {
		const f = stubDaemon(LOCAL_SERVICES);
		render(LocalServicesPage);
		await vi.waitFor(() => expect(serviceCalls(f)).toHaveLength(1));
		expect(screen.queryByRole('button', { name: '30d' })).not.toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		await vi.waitFor(() => expect(serviceCalls(f)).toHaveLength(2));
		const q = new URL(serviceCalls(f)[1], 'http://x').searchParams;
		expect(Date.parse(q.get('to')!) - Date.parse(q.get('from')!)).toBe(168 * 3_600_000);
	});

	it('keeps the rows on a failed refresh and says so', async () => {
		let up = true;
		stubDaemon(() => (up ? LOCAL_SERVICES : null));
		render(LocalServicesPage);
		await vi.waitFor(() => expect(bodyRows()).toHaveLength(LOCAL_SERVICES.rows.length));
		up = false;
		await refreshPage();
		await vi.waitFor(() => expect(screen.getByText("Couldn't refresh local services; showing the last figures loaded.")).toBeInTheDocument());
		expect(bodyRows()).toHaveLength(LOCAL_SERVICES.rows.length);
	});
});
