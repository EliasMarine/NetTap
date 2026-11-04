import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import CertificatesPage from './+page.svelte';
import { refreshPage } from '$lib/stores/pageRefresh';

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
		// DataTable: the sort control is the header's button
		const source = [...container.querySelectorAll('th button')].find((b) => b.textContent?.trim().startsWith('Source'))!;

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

const CERT = {
	_id: 'c1', timestamp: '', domain: 'nas.example', server_name: '', subject: 'CN=nas', issuer: 'Home CA',
	not_before: '', not_after: '', tls_version: 'TLSv12', hash_sha256: 'abc', source_ip: '10.0.0.5', destination_ip: '',
	destination_port: 443, validation_status: 'ok', status: 'valid', days_until_expiry: null,
};
const CHANGES = { from: '', to: '', changes: [], count: 0 };
const STATS = { total_certs: 1, expiring_count: 0, expired_count: 0, self_signed_count: 0, issuer_changes_count: 0, from: '', to: '' };

// PLAN §5.5: the loader is the top bar's Refresh; it keeps the chosen filter and says what failed.
describe('Certificates page — refresh contract', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows the loading state, not zero counts, before the first answer', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(CertificatesPage);
		expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true');
		expect(screen.getByText('Total certificates').closest('.kpi')).toHaveTextContent('—');
	});

	it('reports ok, partial and failed to the top bar', async () => {
		const list = { from: '', to: '', certificates: [CERT], count: 1 };
		stubDaemon({ '/api/certificates': list, '/api/certificates/issuer-changes': CHANGES, '/api/certificates/stats': STATS });
		render(CertificatesPage);
		await screen.findByText('nas.example');
		expect(await refreshPage()).toBe('ok');

		stubDaemon({ '/api/certificates': list, '/api/certificates/issuer-changes': CHANGES });
		expect(await refreshPage()).toBe('partial');
		expect(screen.getByText('Counts unavailable')).toBeInTheDocument();

		stubDaemon({});
		expect(await refreshPage()).toBe('failed');
	});

	it('keeps the chosen status filter when the page is refreshed', async () => {
		stubDaemon({ '/api/certificates/expiring': { from: '', to: '', certificates: [], count: 0 }, '/api/certificates/issuer-changes': CHANGES });
		render(CertificatesPage);
		await fireEvent.click(screen.getByRole('button', { name: 'Expiring' }));
		await screen.findByText('No certificates found for the selected filter.');
		const calls = vi.mocked(fetch).mock.calls.length;

		await refreshPage();
		const urls = vi.mocked(fetch).mock.calls.slice(calls).map(([u]) => String(u).split('?')[0]);
		expect(urls).toContain('/api/certificates/expiring');
		expect(urls).not.toContain('/api/certificates');
		expect(screen.getByRole('button', { name: 'Expiring' })).toHaveAttribute('aria-pressed', 'true');
	});

	it('opens a certificate from its row and closes on Escape', async () => {
		stubDaemon({ '/api/certificates': { from: '', to: '', certificates: [CERT], count: 1 }, '/api/certificates/issuer-changes': CHANGES });
		render(CertificatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Open certificate for nas.example' }));
		expect(screen.getByRole('dialog', { name: 'Certificate details' })).toHaveTextContent('Home CA');
		await fireEvent.keyDown(window, { key: 'Escape' });
		expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
	});
});
