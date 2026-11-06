import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import DnsPage from './+page.svelte';
import { refreshPage } from '$lib/stores/pageRefresh';

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/dns') }),
}));

// #96: a failed suspicious-DNS check read as "No suspicious DNS patterns detected", and a
// complete detection list (hundreds of entries on a busy network) rendered in full.

function stubDaemon(suspicious: unknown | null): void {
	// jsdom has no ResizeObserver; the page's charts need one to mount
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			if (url.startsWith('/api/dns/suspicious') && suspicious !== null) {
				return { ok: true, status: 200, json: async () => ({ from: '', to: '', suspicious }) };
			}
			return { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

function entry(i: number) {
	return { type: 'long_domain', domain: `d${i}.example.com`, count: 1, severity: 'low', description: 'Long domain' };
}

describe('DNS page suspicious patterns', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says the check failed instead of "none detected" when the request fails', async () => {
		stubDaemon(null);
		render(DnsPage);
		await vi.waitFor(() => expect(screen.getByText(/Couldn't check for suspicious DNS patterns/)).toBeInTheDocument());
		expect(screen.queryByText('No suspicious DNS patterns detected.')).not.toBeInTheDocument();
	});

	it('still says none were detected when the check succeeds with none', async () => {
		stubDaemon([]);
		render(DnsPage);
		await vi.waitFor(() => expect(screen.getByText('No suspicious DNS patterns detected.')).toBeInTheDocument());
	});

	// #96: the other DNS sections read "No NXDOMAIN errors detected. That's a good sign." and 0 queries
	it('says the other sections failed instead of "none" or 0', async () => {
		stubDaemon(null);
		render(DnsPage);
		await vi.waitFor(() => expect(screen.getByText("Couldn't load NXDOMAIN errors: the request failed.")).toBeInTheDocument());
		expect(screen.queryByText(/No NXDOMAIN errors detected/)).not.toBeInTheDocument();
		expect(screen.getByText("Couldn't load top domains: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText(/No domains recorded/)).not.toBeInTheDocument();
		expect(screen.getByText("Couldn't load DNS totals: the request failed.")).toBeInTheDocument();
		// KpiCard: the label sits in the card's .kpi root
		expect(screen.getByText('Total queries').closest('.kpi')).not.toHaveTextContent('0');
		expect(screen.getByText("Couldn't load the query timeline: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load query types: the request failed.")).toBeInTheDocument();
	});

	it('says a failed device lookup failed instead of "No DNS records"', async () => {
		stubDaemon([]);
		render(DnsPage);
		await fireEvent.input(screen.getByPlaceholderText(/192\.168/), { target: { value: '192.168.1.20' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Lookup' }));
		await vi.waitFor(() =>
			expect(screen.getByText("Couldn't load DNS records for 192.168.1.20: the request failed.")).toBeInTheDocument(),
		);
		expect(screen.queryByText(/No DNS records for/)).not.toBeInTheDocument();
	});

	it('still says no NXDOMAIN errors when the request succeeds with none', async () => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) =>
				url.startsWith('/api/dns/nxdomain')
					? { ok: true, status: 200, json: async () => ({ from: '', to: '', nxdomains: [] }) }
					: { ok: false, status: 503, json: async () => ({}) },
			),
		);
		render(DnsPage);
		await vi.waitFor(() => expect(screen.getByText(/No NXDOMAIN errors detected/)).toBeInTheDocument());
	});

	it('shows the first 50 of a long list with the true total, and all on request', async () => {
		stubDaemon(Array.from({ length: 60 }, (_, i) => entry(i)));
		render(DnsPage);
		await vi.waitFor(() => expect(screen.getByText('Showing 50 of 60')).toBeInTheDocument());
		expect(screen.getByText('d49.example.com')).toBeInTheDocument();
		expect(screen.queryByText('d50.example.com')).not.toBeInTheDocument();
		await fireEvent.click(screen.getByText('Show all 60'));
		expect(screen.getByText('d59.example.com')).toBeInTheDocument();
		expect(screen.getByText('Showing 60 of 60')).toBeInTheDocument();
	});
});

/** A full, successful set of DNS answers; `domain` names the one top domain. */
function replies(domain: string): Record<string, unknown> {
	return {
		'/api/dns/stats': { total_queries: 1200, unique_domains: 40, nxdomain_count: 3, avg_resolution_ms: 4.2 },
		'/api/dns/top-domains': { domains: [{ domain, count: 900, unique_clients: 2 }] },
		'/api/dns/nxdomain': { nxdomains: [] },
		'/api/dns/types': { types: [{ type: 'A', count: 900 }] },
		'/api/dns/timeline': { series: [{ timestamp: '2026-11-03T10:00:00Z', count: 900 }] },
		'/api/dns/suspicious': { suspicious: [] },
	};
}

const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const fail = { ok: false, status: 503, json: async () => ({}) };

// PLAN §5.5: the loader is the top bar's Refresh; it reports what loaded, and an older range never wins.
describe('DNS page — refresh contract', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	function stub(answer: (path: string, url: string) => unknown | Promise<unknown>) {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		vi.stubGlobal('fetch', vi.fn(async (url: string) => answer(url.split('?')[0], url)));
	}

	it('shows each card loading until its answer arrives', () => {
		stub(() => new Promise(() => {}));
		render(DnsPage);
		expect(screen.getByText('Loading the query timeline')).toBeInTheDocument();
		expect(screen.getByText('Loading top domains')).toBeInTheDocument();
		expect(screen.getByText('Loading query types')).toBeInTheDocument();
		expect(screen.getByText('Loading NXDOMAIN errors')).toBeInTheDocument();
		expect(screen.getByText('Total queries').closest('.kpi')).toHaveTextContent('—');
	});

	it('reports ok, partial and failed, and keeps the last figures when a refresh fails', async () => {
		let mode: 'ok' | 'some' | 'none' = 'ok';
		stub((path) => {
			const body = replies('api.example.org')[path];
			if (mode === 'none' || (mode === 'some' && path === '/api/dns/top-domains')) return fail;
			return body ? reply(body) : fail;
		});
		render(DnsPage);
		await screen.findAllByText('api.example.org');
		expect(await refreshPage()).toBe('ok');

		mode = 'some';
		expect(await refreshPage()).toBe('partial');
		expect(screen.getByText("Couldn't refresh top domains; showing the last figures loaded.")).toBeInTheDocument();
		expect(screen.getAllByText('api.example.org').length).toBeGreaterThan(0);

		mode = 'none';
		expect(await refreshPage()).toBe('failed');
	});

	it("drops an older range's slower answers", async () => {
		const held: Array<() => void> = [];
		stub((path, url) => {
			const hours = (Date.parse(new URL(url, 'http://x').searchParams.get('to') ?? '') - Date.parse(new URL(url, 'http://x').searchParams.get('from') ?? '')) / 3_600_000;
			const body = replies(hours > 2 ? 'old-range.example' : 'new-range.example')[path];
			if (hours <= 2) return body ? reply(body) : fail;
			return new Promise((resolve) => held.push(() => resolve(body ? reply(body) : fail)));
		});
		render(DnsPage);
		await vi.waitFor(() => expect(held.length).toBe(6));
		await fireEvent.click(screen.getByRole('button', { name: '1h' }));
		await screen.findAllByText('new-range.example');

		held.forEach((release) => release());
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.queryByText('old-range.example')).not.toBeInTheDocument();
		expect(screen.getAllByText('new-range.example').length).toBeGreaterThan(0);
		expect(screen.getByRole('button', { name: '1h' })).toHaveAttribute('aria-pressed', 'true');
	});
});

// I13 (accuracy audit 2026-11-06)
describe('DNS page — DNS by device', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	const domains = (n: number, prefix: string) => Array.from({ length: n }, (_, i) => ({ domain: `${prefix}${i}.example`, count: n - i, query_types: [] }));

	function stubDevice(answer: (hours: number) => unknown) {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (!url.startsWith('/api/dns/device/')) return fail;
				const q = new URL(url, 'http://x').searchParams;
				const hours = (Date.parse(q.get('to') ?? '') - Date.parse(q.get('from') ?? '')) / 3_600_000;
				return reply({ device_ip: '192.168.1.20', from: '', to: '', domains: answer(hours) });
			}),
		);
	}

	async function lookUp() {
		await fireEvent.input(screen.getByPlaceholderText(/192\.168/), { target: { value: '192.168.1.20' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Lookup' }));
	}

	it("reloads the device for a new range instead of keeping the last range's domains", async () => {
		stubDevice((hours) => domains(1, hours > 2 ? 'day' : 'hour'));
		render(DnsPage);
		await lookUp();
		expect(await screen.findByText('day0.example')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: '1h' }));
		expect(await screen.findByText('hour0.example')).toBeInTheDocument();
		expect(screen.queryByText('day0.example')).not.toBeInTheDocument();
	});

	it("names no total when the daemon's 200-domain cap is reached", async () => {
		stubDevice(() => domains(200, 'd'));
		render(DnsPage);
		await lookUp();
		expect(await screen.findByText('Showing 50 of the 200 most looked-up domains')).toBeInTheDocument();
		expect(screen.queryByText('Showing 50 of 200 domains')).not.toBeInTheDocument();
	});

	it('gives the exact total under the cap', async () => {
		stubDevice(() => domains(60, 'd'));
		render(DnsPage);
		await lookUp();
		expect(await screen.findByText('Showing 50 of 60 domains')).toBeInTheDocument();
	});
});
