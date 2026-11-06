import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import { refreshPage } from '$lib/stores/pageRefresh';
import type { DomainSummary } from '$lib/api/drilldown';
import { DOMAIN, DOMAIN_EMPTY, DOMAIN_QUIET, LAN_POLICY } from '../../../../e2e/visual/fixtures/drilldown';
import { expectNoNestedInteractive } from '../../../tests/nested-interactive';

// NET-160: domain figures mean what DNS analytics means; lists too long to count withhold their
// KPI, and the alert count is labelled for what it is, with its coverage

const pageStore = vi.hoisted(() => ({ value: null as unknown as ReturnType<typeof writable> }));
vi.mock('$app/stores', async () => {
	const { writable: w } = await import('svelte/store');
	pageStore.value = w({ url: new URL('http://localhost/domain/stream.example.net'), params: { name: 'stream.example.net' } });
	return { page: pageStore.value };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const { default: Page } = await import('./+page.svelte');

const REGISTRY = {
	devices: [{ mac: 'aa', display_name: 'Living room TV', ips: ['192.168.1.22'], last_seen: '2026-11-05T00:00:00Z' }],
	total: 1,
};

let calls: URL[] = [];
function stubDaemon(summary: DomainSummary | undefined, reason = 'Name matching unavailable: zeek.dns.query is not a keyword field') {
	calls = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: string) => {
			const url = new URL(input, 'http://localhost');
			calls.push(url);
			const body =
				url.pathname === '/api/network/lan' ? LAN_POLICY : url.pathname === '/api/devices/registry' ? REGISTRY : url.pathname.startsWith('/api/domains/') ? summary : undefined;
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 502, json: async () => ({ error: reason }) };
		}),
	);
}

const kpi = (label: string) => screen.getAllByText(label).map((e) => e.closest('.kpi')).find(Boolean) as HTMLElement;
const card = (title: string) => screen.getByRole('heading', { name: title }).closest('.card') as HTMLElement;
const goTo = (name: string) => pageStore.value.set({ url: new URL(`http://localhost/domain/${name}`), params: { name } });

describe('Domain page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		goTo('stream.example.net');
	});

	it('shows loading, not zeros, before the first answer', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		expect(kpi('Lookups')).toHaveTextContent('—');
		expect(screen.getAllByRole('status').some((s) => s.getAttribute('aria-busy') === 'true')).toBe(true);
	});

	it('asks for the name as the daemon matches it and shows its figures', async () => {
		goTo('Stream.Example.NET.');
		stubDaemon(DOMAIN);
		const { container } = render(Page);
		await vi.waitFor(() => expect(kpi('Lookups')).toHaveTextContent('420'));
		expect(calls.some((u) => u.pathname === '/api/domains/stream.example.net')).toBe(true);
		expect(screen.getByRole('heading', { level: 1, name: 'stream.example.net' })).toBeInTheDocument();
		expect(screen.getByText(/Matches the name exactly, ignoring case/)).toBeInTheDocument();
		expect(kpi('Devices that looked it up')).toHaveTextContent('3');
		expect(kpi('Addresses it resolved to')).toHaveTextContent('2');
		expect(kpi('TLS sessions')).toHaveTextContent('1,600');
		expect(screen.getByText('DNS lookups per hour · last 24 hours')).toBeInTheDocument();
		// every TLS session counts here; Certificates counts only those that sent one
		expect(screen.getByText(/so its figures can be lower/)).toBeInTheDocument();
		// the TLS lists include excluded devices, unlike the DNS figures
		expect(screen.getByText(/the TLS sessions and devices here include\s+them/)).toBeInTheDocument();
		// links to pages with their own window carry this one
		expect(within(card('Alerts tagged with this name')).getByRole('link', { name: /Open alerts/ })).toHaveAttribute('href', '/alerts?range=24h');
		expect(new URL(screen.getByRole('link', { name: /Search Log Explorer for/ }).getAttribute('href')!, 'http://x').searchParams.get('range')).toBe('24h');
		const alerts = card('Alerts tagged with this name');
		expect(alerts).toHaveTextContent('1');
		expect(alerts).toHaveTextContent('Only 12 of 57 alerts in this window carry a host name.');
		expectNoNestedInteractive(container);
	});

	it('links answers by kind: addresses, names, and other records as text', async () => {
		stubDaemon(DOMAIN);
		render(Page);
		await vi.waitFor(() => expect(kpi('Lookups')).toHaveTextContent('420'));
		const answers = card('What it resolved to');
		expect(within(answers).getByRole('link', { name: '198.51.100.10' })).toHaveAttribute('href', '/address/198.51.100.10');
		expect(within(answers).getByRole('link', { name: '2001:db8::10' })).toHaveAttribute('href', '/address/2001%3Adb8%3A%3A10');
		expect(within(answers).getByRole('link', { name: 'edge.example.net' })).toHaveAttribute('href', '/domain/edge.example.net');
		const askers = card('Devices that looked it up');
		await vi.waitFor(() => expect(within(askers).getByRole('link', { name: 'Living room TV' })).toHaveAttribute('href', '/devices/192.168.1.22'));
		const tls = card('TLS');
		const certs = new URL(within(tls).getByRole('link', { name: /Certificates seen for this name/ }).getAttribute('href')!, 'http://x');
		const req = calls.find((u) => u.pathname.startsWith('/api/domains/'))!;
		expect(Object.fromEntries(certs.searchParams)).toEqual({ site: 'stream.example.net', from: req.searchParams.get('from'), to: req.searchParams.get('to') });
		expect(screen.getByRole('link', { name: /DNS records/ })).toHaveAttribute('href', '/tools/dns-recon?domain=stream.example.net');
		// Log Explorer matches the exact spelling, unlike the count: the link says so
		expect(screen.getByRole('link', { name: /Search Log Explorer for/ })).toHaveAttribute('href', expect.stringContaining('zeek.http.host'));
		expect(screen.getByText(/matches this exact spelling/)).toBeInTheDocument();
		expect(screen.getByText('No response code')).toBeInTheDocument();
	});

	it('withholds counts it could not complete and says Not recorded for untagged alerts', async () => {
		goTo('quiet.example.org');
		stubDaemon(DOMAIN_QUIET);
		const { container } = render(Page);
		await vi.waitFor(() => expect(kpi('Lookups')).toHaveTextContent('90'));
		expect(kpi('Devices that looked it up')).toHaveTextContent('—');
		expect(kpi('Devices that looked it up')).toHaveTextContent('too many to count');
		expect(kpi('Addresses it resolved to')).toHaveTextContent('—');
		expect(kpi('Addresses it resolved to')).toHaveTextContent('too many to count');
		const alerts = card('Alerts tagged with this name');
		expect(alerts).toHaveTextContent('Not recorded');
		expect(alerts).toHaveTextContent('Only 0 of 57 alerts in this window carry a host name.');
		// a TXT answer is text, never a link
		expect(screen.getByText('v=spf1 -all').closest('a')).toBeNull();
		// a list cut at its cap says so in its subtitle too
		expect(card('Devices that looked it up')).toHaveTextContent("First 1 device · lookups per device");
		expect(screen.getByText(/Too many devices to list them all/)).toBeInTheDocument();
		expect(screen.getByText(/Too many answers to list them all/)).toBeInTheDocument();
		expectNoNestedInteractive(container);
	});

	it('lists the same answer twice without crashing the table', async () => {
		const twice = DOMAIN.dns.answers[0];
		stubDaemon({ ...DOMAIN, dns: { ...DOMAIN.dns, answers: [twice, { ...twice }] } });
		render(Page);
		await vi.waitFor(() => expect(kpi('Lookups')).toHaveTextContent('420'));
		expect(within(card('What it resolved to')).getAllByRole('link', { name: twice.value })).toHaveLength(2);
	});

	it('shows empty states when nothing was looked up', async () => {
		stubDaemon(DOMAIN_EMPTY);
		render(Page);
		await screen.findAllByText('No lookups in the last 24 hours');
		expect(kpi('Lookups')).toHaveTextContent('0');
		expect(screen.getByText('No TLS sessions for this name in the last 24 hours')).toBeInTheDocument();
		expect(card('Alerts tagged with this name')).toHaveTextContent('No alerts in this window, so none carry a host name.');
	});

	it("shows the daemon's reason when the summary fails, never zeros", async () => {
		stubDaemon(undefined);
		render(Page);
		await screen.findByText("Couldn't load lookups over time: the request failed.");
		expect(screen.getAllByText('Name matching unavailable: zeek.dns.query is not a keyword field').length).toBeGreaterThan(0);
		expect(kpi('Lookups')).toHaveTextContent('—');
		expect(kpi('TLS sessions')).toHaveTextContent('—');
	});

	it('reports ok and failed to the top bar, keeping the last figures', async () => {
		stubDaemon(DOMAIN);
		render(Page);
		await vi.waitFor(() => expect(kpi('Lookups')).toHaveTextContent('420'));
		expect(await refreshPage()).toBe('ok');
		stubDaemon(undefined);
		expect(await refreshPage()).toBe('failed');
		expect(screen.getByText(/Couldn't refresh this domain; showing the last figures loaded/)).toBeInTheDocument();
		expect(kpi('Lookups')).toHaveTextContent('420');
	});
});

// NET-160 slice 2a: a count's links carry the window it was counted in, not a newer refresh's
describe('Domain page — exact windows', () => {
	beforeEach(() => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-11-06T12:00:00Z'));
	});
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	it("opens Log Explorer and Certificates on the figures' own window while a refresh is in flight", async () => {
		stubDaemon(DOMAIN);
		render(Page);
		await vi.waitFor(() => expect(kpi('Lookups')).toHaveTextContent('420'));
		const sent = calls.find((u) => u.pathname === '/api/domains/stream.example.net')!;
		const win = [sent.searchParams.get('from'), sent.searchParams.get('to')];

		vi.setSystemTime(new Date('2026-11-06T12:10:00Z'));
		stubDaemon(new Promise(() => {}) as never);
		void refreshPage();
		await vi.waitFor(() => expect(calls.some((u) => u.pathname === '/api/domains/stream.example.net')).toBe(true));

		const logs = new URL(screen.getByRole('link', { name: /Search Log Explorer for/ }).getAttribute('href')!, 'http://x');
		expect(['query', 'from', 'to', 'range'].map((k) => logs.searchParams.get(k))).toEqual(['zeek.http.host:"stream.example.net"', ...win, '24h']);
		const certs = new URL(screen.getByRole('link', { name: /Certificates seen for this name/ }).getAttribute('href')!, 'http://x');
		expect(['from', 'to'].map((k) => certs.searchParams.get(k))).toEqual(win);
	});
});
