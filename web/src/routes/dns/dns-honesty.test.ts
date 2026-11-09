import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import DnsPage from './+page.svelte';
import { refreshPage } from '$lib/stores/pageRefresh';
import { ENCRYPTED_DNS_NOTE } from '$lib/api/dns';

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/dns') }),
}));

// NET-225 (DNS-1, DNS-3). Its own file: the capture-mode store is a module singleton, and the
// recovery test needs it fresh.
// - DoH and DoT lookups never reach Zeek's dns.log, yet a device with none read "made no DNS queries".
// - Inline bridge mode sits after the router's address translation: every IPv4 lookup is the router's.
// - The KPI showed the mean (G11, 24 h: mean 19.6 ms, median 6.3 ms) and 0.0 ms with nothing answered.

const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const fail = { ok: false, status: 503, json: async () => ({}) };

/** Replies by path; any path not listed answers 503. */
function stubDaemon(replies: Record<string, unknown>): void {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const body = replies[url.split('?')[0]];
			return body !== undefined ? reply(body) : fail;
		}),
	);
}

const kpi = (label: string) => screen.getByText(label, { selector: '.kpi-top span' }).closest('.kpi') as HTMLElement;
const STATS = { total_queries: 1200, unique_domains: 40, nxdomain_count: 3 };

describe('DNS page — what NetTap can and cannot see', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('shows the median lookup time, with the mean beside it', async () => {
		stubDaemon({ '/api/dns/stats': { ...STATS, avg_resolution_ms: 19.64, median_resolution_ms: 6.28 } });
		render(DnsPage);
		await vi.waitFor(() => expect(kpi('Median resolution').querySelector('.kpi-num')).toHaveTextContent('6.3ms'));
		expect(kpi('Median resolution')).toHaveTextContent('Mean 19.6 ms');
		expect(screen.queryByText('Average resolution')).not.toBeInTheDocument();
	});

	it('reads "—", never 0.0 ms, when no lookup was answered', async () => {
		stubDaemon({ '/api/dns/stats': { ...STATS, avg_resolution_ms: null, median_resolution_ms: null } });
		render(DnsPage);
		await vi.waitFor(() => expect(kpi('Median resolution')).toHaveTextContent('No answered lookups to time'));
		expect(kpi('Median resolution').querySelector('.kpi-num')).toHaveTextContent('—');
		expect(kpi('Median resolution')).not.toHaveTextContent('0.0');
	});

	it('says encrypted lookups are invisible, and an empty device is not "no DNS queries"', async () => {
		stubDaemon({ '/api/dns/device/192.168.1.20': { device_ip: '192.168.1.20', from: '', to: '', domains: [] }, '/api/dns/nxdomain': { nxdomains: [] } });
		render(DnsPage);
		expect(screen.getByRole('note')).toHaveTextContent(ENCRYPTED_DNS_NOTE);
		await vi.waitFor(() => expect(screen.getByText('Only plain DNS lookups are checked.')).toBeInTheDocument());
		expect(screen.queryByText("That's a good sign.")).not.toBeInTheDocument();

		await fireEvent.input(screen.getByPlaceholderText(/192\.168/), { target: { value: '192.168.1.20' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Lookup' }));
		expect(await screen.findByText('No DNS records for 192.168.1.20')).toBeInTheDocument();
		expect(screen.getByText(/NetTap saw no plain DNS lookups from this address/)).toHaveTextContent(/Lookups over DoH or DoT are encrypted/);
		expect(screen.queryByText(/made no DNS queries/)).not.toBeInTheDocument();
		expect(screen.queryByText(/inline bridge mode/)).not.toBeInTheDocument();
	});

	// Codex review: a mode request that failed at startup must not hide the bridge wording all session
	it('picks up bridge mode on a refresh after the first mode request failed', async () => {
		stubDaemon({});
		render(DnsPage);
		await vi.waitFor(() => expect(screen.getByText("Couldn't load DNS totals: the request failed.")).toBeInTheDocument());
		expect(screen.getByRole('note')).not.toHaveTextContent(/inline bridge mode/);

		stubDaemon({ '/api/capture/mode': { mode: 'bridge', interface: 'br0' } });
		await refreshPage();
		await vi.waitFor(() =>
			expect(screen.getByRole('note')).toHaveTextContent(/In inline bridge mode, lookups over IPv4 carry your router's address/),
		);
		expect(screen.getByRole('note')).toHaveTextContent(ENCRYPTED_DNS_NOTE);
	});
});
