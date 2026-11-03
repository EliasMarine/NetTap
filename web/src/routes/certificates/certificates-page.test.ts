import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
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

	// sort sweep on the G11: ascending Source put the 19 certificates with no source IP first
	it('sorts Source by number with blanks last both ways', async () => {
		const cert = (id: string, source_ip: string) => ({
			_id: id, timestamp: '', domain: `${id}.example`, server_name: '', subject: '', issuer: 'CA',
			not_before: '', not_after: '', tls_version: '', hash_sha256: id, source_ip, destination_ip: '',
			destination_port: 443, validation_status: 'ok', status: 'valid', days_until_expiry: null,
		});
		stubDaemon({
			'/api/certificates': { from: '', to: '', count: 3, certificates: [cert('a', '10.0.0.26'), cert('b', ''), cert('c', '10.0.0.235')] },
			'/api/certificates/issuer-changes': { from: '', to: '', changes: [], count: 0 },
		});
		const { container } = render(CertificatesPage);
		await vi.waitFor(() => expect(screen.getByText('a.example')).toBeInTheDocument());
		const sources = () => [...container.querySelectorAll('tbody tr')].map((r) => r.querySelectorAll('td')[5]?.textContent?.trim());
		const source = [...container.querySelectorAll('th')].find((th) => th.textContent?.trim().startsWith('Source'))!;

		await fireEvent.click(source);
		const first = sources();
		await fireEvent.click(source);
		const second = sources();
		const asc = first[0] === '10.0.0.26' ? first : second;
		const desc = asc === first ? second : first;
		expect(asc).toEqual(['10.0.0.26', '10.0.0.235', '']);
		expect(desc).toEqual(['10.0.0.235', '10.0.0.26', '']);
	});
});
