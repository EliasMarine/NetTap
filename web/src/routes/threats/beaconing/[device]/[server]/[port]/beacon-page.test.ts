import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import type { BeaconPair } from '$lib/api/threats';
import type { GeoIPResult } from '$lib/api/geoip';
import { LAN_POLICY } from '../../../../../../../e2e/visual/fixtures/drilldown';
import { BEACON_PAIR, BEACON_PAIR_EMPTY } from '../../../../../../../e2e/visual/fixtures/threats';
import { expectNoNestedInteractive } from '../../../../../../tests/nested-interactive';

// One beaconing pair: the scan's own timing, in words that never clear it, with the network
// owner as context and the next step always "find the app"

const pageStore = vi.hoisted(() => ({ value: null as unknown as ReturnType<typeof writable> }));
vi.mock('$app/stores', async () => {
	const { writable: w } = await import('svelte/store');
	pageStore.value = w({ url: new URL('http://localhost/threats/beaconing/x/y/1'), params: { device: 'x', server: 'y', port: '1' } });
	return { page: pageStore.value };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const { default: Page } = await import('./+page.svelte');

const GEO: GeoIPResult = {
	ip: BEACON_PAIR.server,
	country: 'Netherlands',
	country_code: 'NL',
	city: null,
	latitude: null,
	longitude: null,
	asn: 64500,
	organization: 'Example Hosting',
	is_private: false,
	source: 'maxmind',
	seen_at: null,
	anycast: false,
};
const REGISTRY = { devices: [{ mac: 'aa', display_name: 'Office PC', ips: [BEACON_PAIR.device], last_seen: '2026-11-05T00:00:00Z' }], total: 1 };

const goTo = (port: string = String(BEACON_PAIR.port), query = '?range=24h') =>
	pageStore.value.set({
		url: new URL(`http://localhost/threats/beaconing/${BEACON_PAIR.device}/${BEACON_PAIR.server}/${port}${query}`),
		params: { device: BEACON_PAIR.device, server: BEACON_PAIR.server, port },
	});

let calls: URL[] = [];
function stubDaemon(pair: BeaconPair | undefined, reason = 'Working this out took too long. Try a shorter time range.') {
	calls = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: string) => {
			const url = new URL(input, 'http://localhost');
			calls.push(url);
			const body =
				url.pathname === '/api/network/lan'
					? LAN_POLICY
					: url.pathname === '/api/devices/registry'
						? REGISTRY
						: url.pathname.startsWith('/api/geoip/')
							? GEO
							: url.pathname === '/api/threats/beaconing/pair'
								? pair
								: undefined;
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 503, json: async () => ({ error: reason }) };
		}),
	);
}
const kpi = (label: string) => screen.getAllByText(label).map((e) => e.closest('.kpi')).find(Boolean) as HTMLElement;
const card = (title: string) => screen.getByRole('heading', { name: title }).closest('.card') as HTMLElement;
const pairCalls = () => calls.filter((u) => u.pathname === '/api/threats/beaconing/pair');

describe('Beaconing pair page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		goTo();
	});

	it('shows loading, not zeros, before the first answer', () => {
		goTo();
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		expect(kpi('Calls')).toHaveTextContent('—');
		expect(screen.getAllByRole('status').some((s) => s.getAttribute('aria-busy') === 'true')).toBe(true);
	});

	it("asks for the pair over the range and shows the scan's own timing", async () => {
		goTo();
		stubDaemon(BEACON_PAIR);
		const { container } = render(Page);
		await vi.waitFor(() => expect(kpi('Calls')).toHaveTextContent('142'));
		const call = pairCalls()[0];
		expect([call.searchParams.get('device'), call.searchParams.get('server'), call.searchParams.get('port'), call.searchParams.get('interval')]).toEqual([
			'192.168.1.42',
			'203.0.113.45',
			'8080',
			'5m',
		]);
		expect(screen.getByRole('heading', { level: 1, name: 'Beaconing to 203.0.113.45:8080' })).toBeInTheDocument();
		expect(kpi('Interval')).toHaveTextContent('5 minutes');
		expect(kpi('Jitter')).toHaveTextContent('4.0%');
		expect(kpi('Confidence')).toHaveTextContent('100');
		expect(within(kpi('Confidence')).getByText("How it's scored")).toBeInTheDocument();
		await vi.waitFor(() => expect(container.querySelector('.page-head .page-sub')).toHaveTextContent('From Office PC (192.168.1.42) · last 24 hours'));
		expect(within(container.querySelector('.page-head') as HTMLElement).getByRole('link', { name: 'Office PC (192.168.1.42)' })).toBeInTheDocument();
		expectNoNestedInteractive(container);
	});

	it('explains with the reply, the owner as context only, and always says to find the app', async () => {
		goTo();
		stubDaemon(BEACON_PAIR);
		render(Page);
		const means = await vi.waitFor(() => card('What this means'));
		await vi.waitFor(() => expect(means).toHaveTextContent('The network belongs to Example Hosting (AS64500). That says whose network it is, not which app or customer uses it.'));
		expect(means).toHaveTextContent('Office PC (192.168.1.42) contacted 203.0.113.45:8080 about every 5 minutes, 142 times in the last 24 hours');
		expect(means).toHaveTextContent('updates.example.com');
		expect(within(means).getByText('What to do').closest('.todo')).toHaveTextContent('Find the app on Office PC (192.168.1.42) that makes these calls');
		expect(means).toHaveTextContent('disconnect the device from the network');
		const logs = within(means).getByRole('link', { name: 'These calls in Log Explorer' }).getAttribute('href')!;
		const q = new URL(logs, 'http://x').searchParams;
		expect(q.get('query')).toBe('source.ip:"192.168.1.42" AND destination.ip:"203.0.113.45" AND destination.port:8080');
		expect(q.get('type')).toBe('zeek.conn');
		expect(q.get('from')).toBe(BEACON_PAIR.from);
		expect(within(means).getByRole('link', { name: "All of this device's connections" })).toHaveAttribute('href', '/connections?ip=192.168.1.42');
		const server = card('Who the server is');
		expect(server).toHaveTextContent('Example Hosting (AS64500)');
		expect(server).toHaveTextContent('On a threat list: Suricata blocklist rules');
		expect(server).toHaveTextContent('A Suricata blocklist rule named it in this window');
	});

	it('says when the device is excluded in Settings and when the calls are too many to time', async () => {
		goTo();
		stubDaemon({ ...BEACON_PAIR, device_excluded: true, timing: { ...BEACON_PAIR.timing, status: 'capped', beacon: null, mean_gap_seconds: null, jitter: null, gaps: [] } });
		render(Page);
		await vi.waitFor(() => expect(screen.getByText(/This device is excluded in Settings/)).toBeInTheDocument());
		expect(within(card('Gaps between calls')).getByText('Too many calls to time')).toBeInTheDocument();
		expect(kpi('Interval')).toHaveTextContent('—');
		expect(kpi('Interval')).toHaveTextContent("couldn't be timed");
		expect(kpi('Confidence')).toHaveTextContent('only for a steady schedule');
	});

	it('shows an empty window as empty, never as a schedule', async () => {
		goTo();
		stubDaemon(BEACON_PAIR_EMPTY);
		render(Page);
		await vi.waitFor(() => expect(kpi('Calls')).toHaveTextContent('0'));
		expect(within(card('Calls over time')).getByText('No calls from 192.168.1.42 to 203.0.113.45:8080 in the last 24 hours')).toBeInTheDocument();
		expect(card('What this means')).toHaveTextContent('NetTap needs at least 10 calls to judge a schedule');
	});

	it("shows the daemon's reason with a retry when the pair fails", async () => {
		goTo();
		stubDaemon(undefined);
		render(Page);
		await vi.waitFor(() => expect(screen.getAllByText('Working this out took too long. Try a shorter time range.').length).toBeGreaterThan(0));
		expect(screen.getAllByRole('button', { name: /Try again/ }).length).toBeGreaterThan(0);
	});

	it('sends no request for a port that is not one', async () => {
		goTo('80x');
		stubDaemon(BEACON_PAIR);
		render(Page);
		await vi.waitFor(() => expect(screen.getAllByText("That isn't a port number.").length).toBeGreaterThan(0));
		expect(pairCalls()).toHaveLength(0);
	});

	it('opens on the range the link carries', async () => {
		goTo(String(BEACON_PAIR.port), '?range=7d');
		stubDaemon(BEACON_PAIR);
		render(Page);
		await vi.waitFor(() => expect(pairCalls()).toHaveLength(1));
		const call = pairCalls()[0];
		expect(Date.parse(call.searchParams.get('to')!) - Date.parse(call.searchParams.get('from')!)).toBe(168 * 3_600_000);
		expect(call.searchParams.get('interval')).toBe('1h');
	});
});
