import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import LocalServicesPage from './+page.svelte';
import { refreshPage } from '$lib/stores/pageRefresh';
import { LOCAL_SERVICES, LOCAL_SERVICES_EMPTY } from '../../../e2e/visual/fixtures/local-services';
import { DISPLAY_SETTINGS_KEY } from '$lib/utils/drilldown';
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

/** Fails every request, or with `hang` leaves the local services one unanswered. */
function flakyDaemon() {
	const state = { hang: false };
	vi.stubGlobal(
		'fetch',
		vi.fn((url: string) =>
			state.hang && url.startsWith('/api/local-services')
				? new Promise(() => {})
				: Promise.resolve({ ok: false, status: 503, json: async () => ({ error: 'Working this out took too long. Try a shorter time range.' }) }),
		),
	);
	return state;
}

const FAILED = "Couldn't load local services: the request failed.";
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
		// the reason is text a screen reader reads, not only a hover title
		const unknown = bodyRows().find((r) => r.textContent?.includes('not yet known'))!;
		expect(within(unknown).getAllByRole('cell')[4]).toHaveTextContent("not yet known: Its connection record isn't written yet");
		expectNoNestedInteractive(container);
	});

	it('links an IPv4 or a global IPv6 sender and leaves a link-local one as text', async () => {
		const hue = LOCAL_SERVICES.rows[3];
		stubDaemon({ ...LOCAL_SERVICES, rows: [...LOCAL_SERVICES.rows, { ...hue, id: 'v6', sender: { ...hue.sender, ip: '2001:db8::54' } }] });
		render(LocalServicesPage);
		await vi.waitFor(() => expect(bodyRows().length).toBeGreaterThan(0));
		expect(screen.getAllByRole('link', { name: '192.168.1.154' })[0]).toHaveAttribute('href', expect.stringContaining('192.168.1.154'));
		expect(screen.getByRole('link', { name: '2001:db8::54' })).toHaveAttribute('href', expect.stringContaining('2001'));
		expect(screen.queryByRole('link', { name: 'fe80::200:5eff:fe10:12' })).not.toBeInTheDocument();
		expect(screen.getByText('fe80::200:5eff:fe10:12')).toBeInTheDocument();
	});

	it("sends an SSDP row to its sender's announcements around its last one", async () => {
		stubDaemon(LOCAL_SERVICES);
		render(LocalServicesPage);
		// the sender is in the link's name, so a list of links tells them apart
		const link = await vi.waitFor(() => screen.getByRole('link', { name: 'See its announcements from 192.168.1.44' }));
		const url = new URL(link.getAttribute('href')!, 'http://x');
		expect(url.pathname).toBe('/packets');
		expect(url.searchParams.get('filter')).toBe('ssdp && ip.src == 192.168.1.44');
		const seen = Date.parse(LOCAL_SERVICES.rows.find((r) => r.protocol === 'ssdp')!.last_seen) / 1000;
		expect([Number(url.searchParams.get('from')), Number(url.searchParams.get('to'))]).toEqual([seen - 60, seen + 300]);
		expect(screen.getByText('Around its last one, if the capture still holds it')).toBeInTheDocument();
		expect(screen.getByText('UPnP device (SSDP)')).toBeInTheDocument();
	});

	it('sorts newest first', async () => {
		stubDaemon({ ...LOCAL_SERVICES, rows: [...LOCAL_SERVICES.rows].reverse() });
		render(LocalServicesPage);
		await vi.waitFor(() => expect(bodyRows()).toHaveLength(LOCAL_SERVICES.rows.length));
		expect(bodyRows()[0]).toHaveTextContent('not yet known');
		expect(bodyRows().at(-1)).toHaveTextContent('UPnP device (SSDP)');
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

	it('shows two rows that read the same, told apart by their ids', async () => {
		// two flows from one address, not yet matched to a conn record, can match on every field
		const twin = LOCAL_SERVICES.rows[0];
		stubDaemon({ ...LOCAL_SERVICES, rows: [twin, { ...twin, id: 'twin' }] });
		render(LocalServicesPage);
		await vi.waitFor(() => expect(bodyRows()).toHaveLength(2));
		expect(bodyRows()[0].textContent).toBe(bodyRows()[1].textContent);
	});

	it('says when the list was cut short', async () => {
		stubDaemon({ ...LOCAL_SERVICES, truncated: true });
		render(LocalServicesPage);
		const note = await vi.waitFor(() => screen.getByText(/may not hold every announcement/));
		// it names the limits, so the owner knows which one a shorter range avoids
		// a cut list is no exact total
		expect(screen.getByText(`At least ${LOCAL_SERVICES.rows.length} seen · last 24 hours`)).toBeInTheDocument();
		expect(note).toHaveTextContent('5,000 rows, 20,000 connections matched one by one, 1,000 names from one sender, 50 from one connection, or 100,000 names in all');
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

	it('turns the range pills off while a load runs', async () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(LocalServicesPage);
		expect(screen.getByRole('button', { name: '7d' })).toBeDisabled();
		expect(screen.getByRole('button', { name: '24h' })).toBeDisabled();
	});

	it('never lets a slow older load overwrite a newer one', async () => {
		// the pills are off while a load runs, so the newer load here is the top bar's refresh
		const older = { ...LOCAL_SERVICES, rows: [LOCAL_SERVICES.rows[3]] };
		let release: (body: unknown) => void = () => {};
		let calls = 0;
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (!url.startsWith('/api/local-services')) return { ok: false, status: 503, json: async () => ({}) };
				calls += 1;
				const body = calls === 1 ? await new Promise((resolve) => (release = resolve)) : LOCAL_SERVICES;
				return { ok: true, status: 200, json: async () => body };
			}),
		);
		render(LocalServicesPage);
		await vi.waitFor(() => expect(calls).toBe(1));
		await refreshPage();
		await vi.waitFor(() => expect(bodyRows()).toHaveLength(LOCAL_SERVICES.rows.length));
		release(older);
		await new Promise((resolve) => setTimeout(resolve, 0));
		expect(bodyRows()).toHaveLength(LOCAL_SERVICES.rows.length);
	});

	it("shows a new range loading, not the last range's error", async () => {
		const daemon = flakyDaemon();
		render(LocalServicesPage);
		await vi.waitFor(() => expect(screen.getByText(FAILED)).toBeInTheDocument());
		daemon.hang = true;
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		await vi.waitFor(() => expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true'));
		expect(screen.queryByText(FAILED)).not.toBeInTheDocument();
	});

	it('shows Try again working at once', async () => {
		const daemon = flakyDaemon();
		render(LocalServicesPage);
		await vi.waitFor(() => expect(screen.getByText(FAILED)).toBeInTheDocument());
		daemon.hang = true;
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		await vi.waitFor(() => expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true'));
		expect(screen.queryByText(FAILED)).not.toBeInTheDocument();
	});

	it.each([
		['7d', 168],
		// a default this page doesn't offer opens on its own
		['30d', 24],
	])("opens on Settings › Display's default range (%s) when it offers it", async (saved, hours) => {
		localStorage.setItem(DISPLAY_SETTINGS_KEY, JSON.stringify({ defaultRange: saved }));
		try {
			const f = stubDaemon(LOCAL_SERVICES);
			render(LocalServicesPage);
			await vi.waitFor(() => expect(serviceCalls(f)).toHaveLength(1));
			const q = new URL(serviceCalls(f)[0], 'http://x').searchParams;
			expect(Date.parse(q.get('to')!) - Date.parse(q.get('from')!)).toBe(hours * 3_600_000);
			await vi.waitFor(() => expect(screen.getByRole('button', { name: hours === 168 ? '7d' : '24h' })).toHaveAttribute('aria-pressed', 'true'));
		} finally {
			localStorage.removeItem(DISPLAY_SETTINGS_KEY);
		}
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
