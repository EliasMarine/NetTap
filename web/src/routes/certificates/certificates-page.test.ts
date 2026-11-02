import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import CertificatesPage from './+page.svelte';

// #96: a failed request returned an empty list, so the page said "No certificates found"
// and left out the MITM warning as if no certificate issuer had changed.

function stubDaemon(replies: Record<string, unknown>): void {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const body = replies[url.split('?')[0]];
			return body
				? { ok: true, status: 200, json: async () => body }
				: { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

describe('Certificates page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says the certificates and issuer check failed instead of "none found"', async () => {
		stubDaemon({});
		render(CertificatesPage);
		await vi.waitFor(() => expect(screen.getByText("Couldn't load certificates: the request failed.")).toBeInTheDocument());
		expect(screen.queryByText('No certificates found for the selected filter.')).not.toBeInTheDocument();
		expect(screen.getByText(/Couldn't check for issuer changes/)).toBeInTheDocument();
	});

	it('still says none were found when the requests succeed with none', async () => {
		const empty = { from: '', to: '', certificates: [], count: 0 };
		stubDaemon({
			'/api/certificates': empty,
			'/api/certificates/issuer-changes': { from: '', to: '', changes: [], count: 0 },
		});
		render(CertificatesPage);
		await vi.waitFor(() => expect(screen.getByText('No certificates found for the selected filter.')).toBeInTheDocument());
		expect(screen.queryByText(/Couldn't/)).not.toBeInTheDocument();
	});
});
