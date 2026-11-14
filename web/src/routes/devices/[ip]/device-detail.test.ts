import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import { getSmartAlerts, suppressAlert } from '$api/alerts';
import { getDeviceDetail } from '$api/devices';
import { ENCRYPTED_DNS_NOTE } from '$lib/api/dns';
import { captureMode } from '$lib/stores/captureMode';
import { getSystemHealth } from '$api/system';
import { refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';
import { expectNoNestedInteractive } from '../../../tests/nested-interactive';

const { IP } = vi.hoisted(() => ({ IP: '192.168.1.10' }));

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL(`http://localhost/devices/${IP}`), params: { ip: IP } }),
}));
// NET-225: the page asks the shared store at load; these tests set the mode on it directly
vi.mock('$lib/stores/captureMode', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/stores/captureMode')>()),
	initCaptureMode: vi.fn(async () => {}),
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$api/devices', () => ({
	getDeviceDetail: vi.fn(async () => ({
		device: {
			ip: IP,
			hostname: 'laptop',
			connection_count: 3,
			alert_count: 1,
			first_seen: '2026-10-29T00:00:00Z',
			last_seen: '2026-10-29T01:00:00Z',
			top_destinations: [{ ip: '203.0.113.9', bytes: 2048, connections: 2 }],
			dns_queries: [{ domain: 'Example.COM', count: 4 }],
			bandwidth_series: [],
			protocols: [],
		},
	})),
	getDeviceCategories: vi.fn(async () => ({ categories: [] })),
	getDevicePorts: vi.fn(async () => ({ ports: [] })),
	getDeviceRiskScore: vi.fn(async () => ({ score: 0, level: 'low', factors: [] })),
	getDeviceConnections: vi.fn(async () => ({ connections: [], page: 1, total_pages: 0, total: 0 })),
}));
// NET-228: the Smart alerts empty state reads the pipeline's state; fresh unless a test says not
vi.mock('$api/system', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/system')>()),
	getSystemHealth: vi.fn(async () => ({
		uptime: 1, timestamp: '', storage: null, smart: null, opensearch_reachable: true, status: 'healthy', healthy: true,
		pipeline: { state: 'fresh', newest_record_at: '', age_seconds: 40, threshold_seconds: 900, sensors: {}, checked_at: '' },
	})),
}));
vi.mock('$api/alerts', () => ({
	getSmartAlerts: vi.fn(),
	suppressAlert: vi.fn(),
}));
// NET-205: the live bandwidth card polls its own endpoint; here it stays loading, and the tests read its key
const { getLiveBandwidth } = vi.hoisted(() => ({
	getLiveBandwidth: vi.fn((_key: { mac: string } | { ip: string }, _signal?: AbortSignal) => new Promise<never>(() => {})),
}));
vi.mock('$api/live-bandwidth', async (importOriginal) => ({ ...(await importOriginal<typeof import('$api/live-bandwidth')>()), getLiveBandwidth }));

const ALERT = {
	signature_id: 2010935,
	signature: 'ET SCAN Suspicious inbound to MSSQL port 1433',
	severity: 2,
	severity_label: 'High',
	category_label: 'Scan',
	count: 4,
	trend: 'stable',
	source_ip: IP,
	destination_ip: '10.0.0.5',
	destination_port: 1433,
	assessment: 'Someone probed a database port.',
	// the bucket's own values, which the exact link uses (NET-160 slice 2b-1)
	key: { rule_name: 'ET SCAN Suspicious inbound to MSSQL port 1433', source_ip: IP, destination_ip: '10.0.0.5' },
};

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

describe('Device detail — suppress smart alert', () => {
	beforeEach(() => {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [ALERT], total: 1 } as never);
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	async function clickSuppress() {
		render(Page);
		await flush();
		await fireEvent.click(await screen.findByRole('button', { name: 'Suppress' }));
		await flush();
	}

	it('keeps the alert and shows an error when the suppress fails', async () => {
		vi.mocked(suppressAlert).mockRejectedValue(new Error('HTTP 500'));
		await clickSuppress();

		expect(suppressAlert).toHaveBeenCalledWith(ALERT.signature_id, IP);
		expect(screen.getByText(ALERT.signature)).toBeInTheDocument();
		expect(screen.getByText('Suppress failed. Try again.')).toBeInTheDocument();
	});

	it('removes the alert once the daemon confirms the suppress', async () => {
		vi.mocked(suppressAlert).mockResolvedValue({ status: 'ok' } as never);
		await clickSuppress();

		expect(screen.queryByText(ALERT.signature)).not.toBeInTheDocument();
		expect(screen.queryByText('Suppress failed. Try again.')).not.toBeInTheDocument();
		// NET-228: the rule still matched; only the group to review is gone
		expect(screen.getByText('No alert groups to review for this device in this period')).toBeInTheDocument();
	});

	// NET-228: compute_trend is a rate with no comparison window, so no rising or falling arrow
	it('shows no rising or falling arrow', async () => {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [{ ...ALERT, trend: 'increasing' }], total: 1 } as never);
		render(Page);
		await flush();
		await screen.findByText(ALERT.signature);
		expect(screen.queryByLabelText('Rising')).not.toBeInTheDocument();
		expect(screen.queryByLabelText('Falling')).not.toBeInTheDocument();
	});
});

// NET-160: a looked-up domain opens its domain page, a destination its address page, nothing nested
describe('Device detail — drill-down links', () => {
	beforeEach(() => {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
	});

	it('links the DNS domain and the destination address', async () => {
		const { container } = render(Page);
		await flush();
		expect(await screen.findByRole('link', { name: 'Example.COM' })).toHaveAttribute('href', '/domain/example.com');
		expect(screen.getByRole('link', { name: '203.0.113.9' })).toHaveAttribute('href', '/address/203.0.113.9');
		expectNoNestedInteractive(container);
	});
});

describe('Device detail — time range (#87)', () => {
	beforeEach(() => {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	const HOUR = 3_600_000;
	function spanHours(opts: { from?: string; to?: string }): number {
		return (Date.parse(opts.to ?? '') - Date.parse(opts.from ?? '')) / HOUR;
	}

	it('asks for the last 24 h by default and 7 days after clicking 7d, on every request', async () => {
		const devices = await import('$api/devices');
		render(Page);
		await flush();
		expect(spanHours(vi.mocked(devices.getDeviceDetail).mock.calls[0][1] as never)).toBe(24);

		vi.clearAllMocks();
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		await flush();

		expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
		for (const fn of [
			devices.getDeviceDetail,
			devices.getDeviceCategories,
			devices.getDevicePorts,
			devices.getDeviceRiskScore,
			devices.getDeviceConnections,
		]) {
			expect(vi.mocked(fn)).toHaveBeenCalledTimes(1);
			expect(spanHours(vi.mocked(fn).mock.calls[0][1] as never)).toBe(168);
		}
		expect(spanHours(vi.mocked(getSmartAlerts).mock.calls[0][0] as never)).toBe(168);
		// Connection pages reuse the fetch's window instead of sliding with the clock
		const detailOpts = vi.mocked(devices.getDeviceDetail).mock.calls[0][1] as { from: string };
		const connOpts = vi.mocked(devices.getDeviceConnections).mock.calls[0][1] as { from: string };
		expect(connOpts.from).toBe(detailOpts.from);
	});
});

// #96: getSmartAlerts turned an HTTP error into an empty list, so the card said "No actionable
// alerts for this device" when the request had failed.
describe('Device detail — smart alerts request fails', () => {
	afterEach(() => {
		vi.clearAllMocks();
	});

	it('says the alerts could not be loaded and keeps the rest of the page', async () => {
		vi.mocked(getSmartAlerts).mockRejectedValue(new Error('Smart alerts failed: HTTP 502'));
		render(Page);
		await flush();

		expect(screen.getByText("Couldn't load alerts for this device: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No actionable alerts for this device.')).not.toBeInTheDocument();
		expect(screen.getByText('check failed')).toBeInTheDocument();
		expect(screen.getAllByText('laptop').length).toBeGreaterThan(0);
	});

	// OLD CODE: expect(screen.getByText('No actionable alerts for this device.')) (NET-228: + the pipeline's state)
	it('still says there are none when the request succeeds empty, beside how fresh the data is', async () => {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
		render(Page);
		await flush();

		expect(screen.getByText('No alert groups to review for this device in this period')).toBeInTheDocument();
		expect(screen.getByText('Data pipeline now: Newest record 40 s ago.')).toBeInTheDocument();
	});

	// NET-228: with Suricata stopped an empty list proves nothing
	it("can't tell when the pipeline isn't fresh", async () => {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
		vi.mocked(getSystemHealth).mockResolvedValueOnce({
			uptime: 1, timestamp: '', storage: null, smart: null, opensearch_reachable: true, status: 'healthy', healthy: true,
			pipeline: { state: 'sensor_stopped', newest_record_at: '', age_seconds: 40, threshold_seconds: 900, sensors: { 'nettap-suricata-live': 'exited' }, checked_at: '' },
		});
		render(Page);
		await flush();

		expect(screen.getByText("Can't tell if this device has any alert to review")).toBeInTheDocument();
		expect(screen.getByText('Data pipeline now: Suricata stopped.')).toBeInTheDocument();
		expect(screen.queryByText('No alert groups to review for this device in this period')).not.toBeInTheDocument();
	});
});

// NET-158: Recent connections go both ways; the protocol filter and the upload share label
describe('Device detail — connection direction, protocol filter and upload share', () => {
	beforeEach(() => {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
	});
	afterEach(() => vi.clearAllMocks());

	const row = (id: string, direction: 'in' | 'out', src: string, dst: string, srcBytes: number, dstBytes: number) => ({
		_id: id, _index: 'i', direction, '@timestamp': '2026-10-29T00:30:00Z', network: { transport: 'tcp' },
		source: { ip: src, port: 50000, bytes: srcBytes }, destination: { ip: dst, port: 443, bytes: dstBytes },
	});

	it("shows DL and UL from the device's side on sessions it answered", async () => {
		const devices = await import('$api/devices');
		vi.mocked(devices.getDeviceConnections).mockResolvedValue({
			from: '', to: '', ip: IP, page: 1, size: 25, total: 2, total_pages: 1,
			connections: [
				// decimal units (NET-166): 1,000 bytes is 1.0 KB
				row('a', 'out', IP, '8.8.8.8', 1000, 4000),
				row('b', 'in', '192.168.1.7', IP, 2000, 512),
			],
		});
		render(Page);
		await flush();

		// OLD CODE: expect(screen.getByText(/Sessions to or from this device/)).toBeInTheDocument(); (NET-226: the list is this address's sessions; the device's IPv6 is counted by MAC)
		expect(screen.getByText(/Sessions to or from this address/)).toBeInTheDocument();
		const table = screen.getByRole('table', { name: 'Recent connections' });
		const [, out, inbound] = Array.from(table.querySelectorAll('tr'));
		// Time, Direction, Destination, Proto, Service, Duration, DL, UL
		const cells = (tr: Element) => Array.from(tr.querySelectorAll('td'), (td) => td.textContent?.trim());
		expect(cells(out)[1]).toBe('Out');
		expect(cells(out).slice(-2)).toEqual(['4.0 KB', '1.0 KB']);
		expect(cells(inbound)[1]).toBe('In');
		// the other end sent 2 KB to the device (its download) and got 512 B back (its upload)
		expect(cells(inbound).slice(-2)).toEqual(['2.0 KB', '512 B']);
	});

	it('asks the daemon for one protocol from page 1, so the total and pager match the rows', async () => {
		const devices = await import('$api/devices');
		render(Page);
		await flush();
		vi.mocked(devices.getDeviceConnections).mockClear();

		await fireEvent.click(screen.getByRole('button', { name: 'UDP' }));
		await flush();

		expect(devices.getDeviceConnections).toHaveBeenCalledTimes(1);
		expect(vi.mocked(devices.getDeviceConnections).mock.calls[0][1]).toMatchObject({ proto: 'udp', page: 1 });
	});

	// OLD CODE: it('labels a 35% upload share as the risk factor does: elevated, not normal', … (NET-209: the share no longer scores, so it gets no risk word)
	it('describes a 35% upload share as balanced, with no risk word', async () => {
		const devices = await import('$api/devices');
		const { device } = await vi.mocked(devices.getDeviceDetail)(IP, {});
		vi.mocked(devices.getDeviceDetail).mockResolvedValueOnce({
			// OLD CODE: device: { ...device, total_bytes: 100_000, orig_bytes: 35_000, resp_bytes: 65_000 }, (NET-226: what the device sent, both sides)
			device: { ...device, total_bytes: 100_000, upload_bytes: 35_000, download_bytes: 65_000 },
		} as never);
		render(Page);
		await flush();

		const kpi = screen.getAllByText('Upload share').map((el) => el.closest('.kpi')).find(Boolean) as HTMLElement;
		// OLD CODE START — NET-209: risk words
		// expect(kpi).toHaveTextContent('Elevated');
		// expect(kpi).not.toHaveTextContent('Normal');
		// OLD CODE END
		expect(kpi).toHaveTextContent('Balanced');
		expect(kpi).not.toHaveTextContent('Elevated');
	});
});

// NET-226: upload is what the device sent on both sides, IPv6 is counted by MAC, guesses say so
describe('Device detail — both sides, IPv6 and guesses (NET-226)', () => {
	beforeEach(() => {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
	});
	afterEach(() => vi.clearAllMocks());

	async function renderWith(extra: Record<string, unknown>) {
		const devices = await import('$api/devices');
		const { device } = await vi.mocked(devices.getDeviceDetail)(IP, {});
		vi.mocked(devices.getDeviceDetail).mockResolvedValue({ device: { ...device, ...extra } } as never);
		render(Page);
		await flush();
	}

	it('takes the upload share and the traffic sub from upload_bytes, not the originator bytes', async () => {
		// the device answered most of its sessions, so what it started (orig) is not what it sent
		await renderWith({ total_bytes: 100_000, orig_bytes: 10_000, resp_bytes: 90_000, upload_bytes: 60_000, download_bytes: 40_000 });

		const share = screen.getAllByText('Upload share').map((el) => el.closest('.kpi')).find(Boolean) as HTMLElement;
		expect(share).toHaveTextContent('60%');
		const traffic = screen.getAllByText('Traffic').map((el) => el.closest('.kpi')).find(Boolean) as HTMLElement;
		expect(traffic).toHaveTextContent('↓ 40.0 KB down · ↑ 60.0 KB up');
	});

	it('says how many of its connections were over IPv6', async () => {
		await renderWith({ connection_count: 12, ipv6_connections: 5, unique_destinations: 3 });
		const kpi = screen.getAllByText('Connections').map((el) => el.closest('.kpi')).find(Boolean) as HTMLElement;
		expect(kpi).toHaveTextContent('of which 5 over IPv6 · 3 unique destinations');
	});

	it.each([
		['no_gateway', "IPv6 traffic other than link-local isn't counted for this period: no internet traffic showed which device is the router."],
		['router', "This device forwards other devices' traffic (it's the router), so only its link-local IPv6 is counted."],
	])('says what IPv6 it left out when the reason is %s', async (reason, text) => {
		await renderWith({ ipv6_left_out: 7, ipv6_left_out_reason: reason });
		expect(screen.getByRole('note')).toHaveTextContent(text);
	});

	// OLD CODE START — review L10: the note showed under every chart, and "count twice … counts once" read as a contradiction
	// it('NET-226 follow-up: says under the chart that traffic routed between VLANs counts its bytes twice', async () => {
	// 	await renderWith({ bandwidth_series: [{ timestamp: '2026-10-29T00:00:00Z', bytes: 100, download_bytes: 60, upload_bytes: 40 }] });
	// 	expect(
	// 		screen.getByText(
	// 			'Traffic your router routes between two of your VLANs can be seen on both, so its bytes count twice here; each connection counts once.',
	// 		),
	// 	).toBeInTheDocument();
	// });
	// OLD CODE END
	const SERIES = [{ timestamp: '2026-10-29T00:00:00Z', bytes: 100, download_bytes: 60, upload_bytes: 40 }];
	const VLAN_NOTE = /bytes count twice/;

	it('says its bytes may count twice only when it had connections with another of your subnets', async () => {
		await renderWith({ bandwidth_series: SERIES, inter_vlan_connections: 12 });
		expect(screen.getByText(VLAN_NOTE)).toHaveTextContent(
			'12 of its connections were with another of your subnets. If your router carries that traffic over the link NetTap watches, NetTap sees both legs of each one, so their bytes count twice in these figures.',
		);
	});

	it('says nothing about subnets when it had no such connections', async () => {
		await renderWith({ bandwidth_series: SERIES, inter_vlan_connections: 0 });
		expect(screen.queryByText(VLAN_NOTE)).not.toBeInTheDocument();
	});

	// NET-260 review: the daemon zero-fills every slot, and an all-zero series picked slot 0 as busiest
	it('shows the empty state for an all-zero series, not a flat chart', async () => {
		await renderWith({ bandwidth_series: SERIES.map((p) => ({ ...p, bytes: 0, download_bytes: 0, upload_bytes: 0 })) });
		expect(screen.getByText('No traffic in this range')).toBeInTheDocument();
		expect(screen.queryByLabelText(/^Busiest at /)).not.toBeInTheDocument();
	});

	it('shows no IPv6 notice when nothing was left out', async () => {
		await renderWith({ ipv6_left_out: 0, ipv6_left_out_reason: null });
		expect(screen.queryByText(/link-local IPv6/)).not.toBeInTheDocument();
	});

	it('shows the type and OS as guesses, with what they came from', async () => {
		await renderWith({ category: 'computer', category_basis: 'os', os_hint: 'Windows', os_basis: 'web traffic' });
		expect(screen.getByText('Likely computer · from its OS')).toBeInTheDocument();
		expect(screen.getByText('Likely Windows · from web traffic')).toBeInTheDocument();
	});
});

// NET-160 slice 2a: a count links to a list over the window it was counted in, even while a
// later refresh is still in flight
describe('Device detail — port, signature and connection links', () => {
	beforeEach(() => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-11-06T12:00:00Z'));
	});
	afterEach(() => {
		vi.useRealTimers();
		vi.clearAllMocks();
	});

	it("links each port and signature over its count's own window, not a newer refresh's", async () => {
		const devices = await import('$api/devices');
		vi.mocked(devices.getDevicePorts).mockResolvedValueOnce({ ports: [{ port: 443, service: 'https', connections: 12, suspicious: false }] } as never);
		vi.mocked(getSmartAlerts).mockResolvedValueOnce({ alerts: [ALERT], total: 1 } as never);
		render(Page);
		await flush();
		const portsSent = vi.mocked(devices.getDevicePorts).mock.calls[0][1] as { from: string; to: string };
		const alertsSent = vi.mocked(getSmartAlerts).mock.calls[0][0] as { from: string; to: string };

		// ten minutes on, a refresh that hasn't answered yet must not move the links
		vi.setSystemTime(new Date('2026-11-06T12:10:00Z'));
		vi.mocked(devices.getDevicePorts).mockReturnValueOnce(new Promise(() => {}) as never);
		vi.mocked(getSmartAlerts).mockReturnValueOnce(new Promise(() => {}) as never);
		void refreshPage();
		await flush();
		expect(vi.mocked(devices.getDevicePorts)).toHaveBeenCalledTimes(2);

		const port = new URL(screen.getByRole('link', { name: '443' }).getAttribute('href')!, 'http://x');
		expect(port.pathname).toBe('/logs');
		expect(port.searchParams.get('query')).toBe(`event.provider:zeek AND event.dataset:conn AND source.ip:"${IP}" AND destination.port:443`);
		expect(['from', 'to', 'range'].map((k) => port.searchParams.get(k))).toEqual([portsSent.from, portsSent.to, '24h']);
		// NET-160 section D: the link carries the port's connection count, the figure clicked
		expect(port.searchParams.get('count')).toBe('12');

		const sig = new URL(screen.getByRole('link', { name: ALERT.signature }).getAttribute('href')!, 'http://x');
		expect(sig.pathname).toBe('/alerts');
		// OLD CODE: …map over ['signature', 'from', 'to', 'range'] (the count is this device's, so the list is too)
		// OLD CODE: …map over ['signature', 'ip', 'from', 'to', 'range'] (slice 2b-1: the group's pair too)
		expect(['signature', 'ip', 'src', 'dst', 'from', 'to', 'range'].map((k) => sig.searchParams.get(k))).toEqual([
			ALERT.signature, IP, IP, '10.0.0.5', alertsSent.from, alertsSent.to, '24h',
		]);
		expect(sig.searchParams.get('count')).toBe(String(ALERT.count));
	});

	it("links a connection's destination address beside the row's button", async () => {
		const devices = await import('$api/devices');
		vi.mocked(getSmartAlerts).mockResolvedValueOnce({ alerts: [], total: 0 } as never);
		vi.mocked(devices.getDeviceConnections).mockResolvedValueOnce({
			from: '', to: '', ip: IP, page: 1, size: 25, total: 1, total_pages: 1,
			connections: [{ _id: 'a', _index: 'i', direction: 'out', '@timestamp': '2026-11-06T11:30:00Z', network: { transport: 'tcp' }, source: { ip: IP, port: 50000 }, destination: { ip: '8.8.8.8', port: 443 } }],
		} as never);
		const { container } = render(Page);
		await flush();
		const table = screen.getByRole('table', { name: 'Recent connections' });
		const link = within(table).getByRole('link', { name: '8.8.8.8' });
		expect(link).toHaveAttribute('href', '/address/8.8.8.8');
		expect(link.closest('td')).toHaveTextContent(':443');
		expectNoNestedInteractive(container);
	});
});

// NET-160 slice 2b-1: a smart alert's ×N opens exactly the alerts it counts: its bucket's rule
// name, source and destination, for this device, over the window it was counted in
describe('Device detail — smart alert ×N links', () => {
	afterEach(() => vi.clearAllMocks());

	const countLink = (n: number, signature: string) => screen.getByRole('link', { name: `×${n} alerts: ${signature}` });
	const params = (a: HTMLElement) => Object.fromEntries(new URL(a.getAttribute('href')!, 'http://x').searchParams);

	it('the ×N is a link to the exact list, the same one the signature opens', async () => {
		vi.mocked(getSmartAlerts).mockResolvedValueOnce({ alerts: [ALERT], total: 1 } as never);
		const { container } = render(Page);
		await flush();
		const sent = vi.mocked(getSmartAlerts).mock.calls[0][0] as { from: string; to: string };
		const count = countLink(4, ALERT.signature);
		expect(count).toHaveTextContent('×4');
		// OLD CODE: expect(params(count)).toEqual({ signature: ALERT.key.rule_name, ip: IP, src: IP, dst: '10.0.0.5', from: sent.from, to: sent.to, range: '24h' }); (section D: the link carries the ×N)
		expect(params(count)).toEqual({ signature: ALERT.key.rule_name, ip: IP, src: IP, dst: '10.0.0.5', from: sent.from, to: sent.to, range: '24h', count: '4' });
		expect(screen.getByRole('link', { name: ALERT.signature })).toHaveAttribute('href', count.getAttribute('href'));
		expectNoNestedInteractive(container);
	});

	it('links by the bucket key when the shown signature differs from it', async () => {
		const shown = { ...ALERT, signature: 'A friendlier shown name', key: { ...ALERT.key, rule_name: 'ET SCAN The raw rule' } };
		vi.mocked(getSmartAlerts).mockResolvedValueOnce({ alerts: [shown], total: 1 } as never);
		render(Page);
		await flush();
		expect(params(countLink(4, 'A friendlier shown name')).signature).toBe('ET SCAN The raw rule');
		expect(params(screen.getByRole('link', { name: 'A friendlier shown name' })).signature).toBe('ET SCAN The raw rule');
	});

	it('an activity group links to the activity list (NET-191)', async () => {
		const activity = { ...ALERT, signature: 'ET INFO STUN binding request', severity: 5, activity: true };
		vi.mocked(getSmartAlerts).mockResolvedValueOnce({ alerts: [activity], total: 1 } as never);
		render(Page);
		await flush();
		expect(params(countLink(4, activity.signature))).toMatchObject({ ip: IP, activity: 'true', count: '4' });
	});

	it('a group with a missing or empty key part has no link, and says why', async () => {
		const groups = [
			{ ...ALERT, signature: 'No destination', key: { ...ALERT.key, destination_ip: null } },
			{ ...ALERT, signature: 'Empty rule', key: { ...ALERT.key, rule_name: '' } },
		];
		vi.mocked(getSmartAlerts).mockResolvedValueOnce({ alerts: groups, total: 2 } as never);
		render(Page);
		await flush();
		for (const name of ['No destination', 'Empty rule']) {
			expect(screen.queryByRole('link', { name })).not.toBeInTheDocument();
			expect(screen.queryByRole('link', { name: `×4 alerts: ${name}` })).not.toBeInTheDocument();
			const item = screen.getByText(name).closest('li')!;
			expect(within(item).getByText('×4')).toHaveAttribute('title', "This group has no signature, source or destination recorded, so it can't be listed exactly");
		}
	});
});

describe('Device detail — DHCP history (NET-263)', () => {
	beforeEach(() => {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
	});
	afterEach(() => vi.clearAllMocks());

	it('links the DHCP timeline by MAC, and only when the device has one', async () => {
		const withMac = (mac?: string) =>
			({
				device: {
					ip: IP, mac, hostname: 'laptop', connection_count: 3, alert_count: 0,
					first_seen: '2026-10-29T00:00:00Z', last_seen: '2026-10-29T01:00:00Z',
					top_destinations: [], dns_queries: [], bandwidth_series: [], protocols: [],
				},
			}) as never;
		vi.mocked(getDeviceDetail).mockImplementationOnce(async () => withMac('AA:BB:CC:DD:EE:FF'));
		const first = render(Page);
		expect(await screen.findByRole('link', { name: 'DHCP history' })).toHaveAttribute('href', '/tools/dhcp-timeline?mac=aa%3Abb%3Acc%3Add%3Aee%3Aff');
		first.unmount();

		render(Page);
		await screen.findByText('192.168.1.10', { selector: 'dd' });
		expect(screen.queryByRole('link', { name: 'DHCP history' })).not.toBeInTheDocument();
	});
});

describe('Device detail — live bandwidth (NET-205)', () => {
	afterEach(() => vi.clearAllMocks());

	it('measures by the page’s IP only, never the MAC the address had', async () => {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
		vi.mocked(getDeviceDetail).mockImplementationOnce(
			async () =>
				({
					device: {
						ip: IP, mac: 'aa:bb:cc:dd:ee:ff', hostname: 'laptop', connection_count: 3, alert_count: 0,
						first_seen: '2026-10-29T00:00:00Z', last_seen: '2026-10-29T01:00:00Z',
						top_destinations: [], dns_queries: [], bandwidth_series: [], protocols: [],
					},
				}) as never,
		);
		render(Page);
		expect(await screen.findByRole('heading', { name: 'Live bandwidth' })).toBeInTheDocument();
		expect(getLiveBandwidth).toHaveBeenCalledWith({ ip: IP }, expect.any(AbortSignal));
		expect(getLiveBandwidth.mock.calls.every(([key]) => !('mac' in key))).toBe(true);
	});
});

// NET-225 (DNS-1): an empty DNS card said "No DNS data." though DoH and DoT lookups never show
describe('Device detail — DNS activity', () => {
	afterEach(() => vi.clearAllMocks());

	it('says only plain DNS shows when the device has no lookups', async () => {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
		vi.mocked(getDeviceDetail).mockImplementationOnce(
			async () =>
				({
					device: {
						ip: IP, mac: null, hostname: 'laptop', connection_count: 3, alert_count: 0,
						first_seen: '2026-10-29T00:00:00Z', last_seen: '2026-10-29T01:00:00Z',
						top_destinations: [], dns_queries: [], bandwidth_series: [], protocols: [],
					},
				}) as never,
		);
		render(Page);
		expect(await screen.findByText('No plain DNS lookups seen.')).toBeInTheDocument();
		expect(screen.getByText(ENCRYPTED_DNS_NOTE)).toBeInTheDocument();
		expect(screen.queryByText('No DNS data.')).not.toBeInTheDocument();
	});
});

// NET-225: post-NAT, one address can carry several devices' traffic; the card must not read as one device's
describe('Device detail — risk score in inline bridge mode', () => {
	afterEach(() => {
		captureMode.set(null);
		vi.clearAllMocks();
	});

	async function renderRisk(): Promise<void> {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
		render(Page);
		await screen.findByRole('img', { name: /^Risk score \d+ of 100/ });
	}

	it('labels the score as this address\'s and says it can\'t stand for one device', async () => {
		captureMode.set('bridge');
		await renderRisk();
		expect(screen.getByRole('heading', { name: 'Risk score for this address' })).toBeInTheDocument();
		expect(screen.getByText(/one address can carry several devices' traffic, so it can't stand for a single device's risk/)).toBeInTheDocument();
	});

	it('keeps "Risk score" in mirror mode', async () => {
		captureMode.set('mirror');
		await renderRisk();
		expect(screen.getByRole('heading', { name: 'Risk score' })).toBeInTheDocument();
		expect(screen.queryByText(/can't stand for a single device's risk/)).not.toBeInTheDocument();
	});
});
