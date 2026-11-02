import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import DnsPage from './+page.svelte';

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
		expect(screen.getByText('Total Queries').closest('.stat-card')).not.toHaveTextContent('0');
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
