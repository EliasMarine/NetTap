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
