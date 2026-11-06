import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getCertificates,
	getExpiringCerts,
	getSelfSignedCerts,
	getIssuerChanges,
	getCertStats,
	getCertificateOverview,
} from './certificates';

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

function mockFetchSuccess(body: unknown, status = 200): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: status >= 200 && status < 300,
			status,
			json: () => Promise.resolve(body),
		}),
	);
}

function mockFetchFailure(status = 500): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: false,
			status,
			json: () => Promise.reject(new Error('no body')),
		}),
	);
}

function mockFetchReject(): void {
	vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network error')));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('certificates API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getCertificates ------------------------------------------------------

	describe('getCertificates', () => {
		it('returns certificates on success', async () => {
			mockFetchSuccess({
				from: '2026-03-01',
				to: '2026-03-08',
				certificates: [{ domain: 'example.com', issuer: 'CA', status: 'valid' }],
				count: 1,
			});

			const result = await getCertificates();
			expect(result.count).toBe(1);
			expect(result.certificates[0].domain).toBe('example.com');
		});

		// #96: an empty list read as "No certificates found"
		it('throws on HTTP error', async () => {
			mockFetchFailure();
			await expect(getCertificates()).rejects.toThrow('HTTP 500');
		});

		it('throws on network error', async () => {
			mockFetchReject();
			await expect(getCertificates()).rejects.toThrow('network error');
		});
	});

	// -- getExpiringCerts -----------------------------------------------------

	describe('getExpiringCerts', () => {
		it('returns expiring certs on success', async () => {
			mockFetchSuccess({
				from: '',
				to: '',
				certificates: [{ domain: 'old.com', status: 'expiring', days_until_expiry: 10 }],
				count: 1,
			});

			const result = await getExpiringCerts(30);
			expect(result.count).toBe(1);
			expect(result.certificates[0].status).toBe('expiring');
		});

		it('throws on HTTP error', async () => {
			mockFetchFailure();
			await expect(getExpiringCerts()).rejects.toThrow('HTTP 500');
		});

		it('throws on network error', async () => {
			mockFetchReject();
			await expect(getExpiringCerts()).rejects.toThrow('network error');
		});
	});

	// -- getSelfSignedCerts ---------------------------------------------------

	describe('getSelfSignedCerts', () => {
		it('returns self-signed certs on success', async () => {
			mockFetchSuccess({
				from: '',
				to: '',
				certificates: [{ domain: 'self.local', status: 'self-signed' }],
				count: 1,
			});

			const result = await getSelfSignedCerts();
			expect(result.count).toBe(1);
		});

		it('throws on error', async () => {
			mockFetchReject();
			await expect(getSelfSignedCerts()).rejects.toThrow('network error');
		});
	});

	// -- getIssuerChanges -----------------------------------------------------

	describe('getIssuerChanges', () => {
		it('returns changes on success', async () => {
			mockFetchSuccess({
				from: '',
				to: '',
				changes: [{ domain: 'bank.com', issuer_count: 2, issuers: ['CA1', 'CA2'] }],
				count: 1,
			});

			const result = await getIssuerChanges();
			expect(result.count).toBe(1);
			expect(result.changes[0].issuer_count).toBe(2);
		});

		// #96: an empty list hid the MITM warning as if no issuer had changed
		it('throws on error', async () => {
			mockFetchFailure();
			await expect(getIssuerChanges()).rejects.toThrow('HTTP 500');
		});
	});

	// -- getCertStats ---------------------------------------------------------

	describe('getCertStats', () => {
		it('returns stats on success', async () => {
			mockFetchSuccess({
				total_certs: 42,
				expiring_count: 3,
				expired_count: 2,
				self_signed_count: 1,
				issuer_changes_count: 0,
				from: '',
				to: '',
			});

			const stats = await getCertStats();
			expect(stats?.total_certs).toBe(42);
			expect(stats?.expiring_count).toBe(3);
			expect(stats?.expired_count).toBe(2);
		});

		// A failed query must not read as "0 certificates" (G11, 2026-11-02)
		it('returns null on HTTP error', async () => {
			mockFetchFailure();
			expect(await getCertStats()).toBeNull();
		});

		it('returns null on network error', async () => {
			mockFetchReject();
			expect(await getCertStats()).toBeNull();
		});
	});

	// -- getCertificateOverview (NET-154) ------------------------------------

	describe('getCertificateOverview', () => {
		const overview = { from: 'a', to: 'b', summary: { certificates: 3 }, sites: [], findings: [], devices: [], certificates: [], details: {} };

		it('asks for the window and returns the overview', async () => {
			mockFetchSuccess(overview);
			const result = await getCertificateOverview('2026-11-05T00:00:00Z', '2026-11-05T12:00:00Z');
			expect(result.summary.certificates).toBe(3);
			const url = vi.mocked(fetch).mock.calls[0][0] as string;
			expect(url).toBe('/api/certificates/overview?from=2026-11-05T00%3A00%3A00Z&to=2026-11-05T12%3A00%3A00Z');
		});

		it("throws with the daemon's reason, so the page can say why", async () => {
			mockFetchSuccess({ error: 'Working out certificate data for this window took too long. Try a shorter window.' }, 503);
			await expect(getCertificateOverview('a', 'b')).rejects.toThrow('took too long');
		});

		it('throws on an HTTP error without a body, and on a network error', async () => {
			mockFetchFailure(502);
			await expect(getCertificateOverview('a', 'b')).rejects.toThrow('HTTP 502');
			mockFetchReject();
			await expect(getCertificateOverview('a', 'b')).rejects.toThrow('network error');
		});

		it('throws on a malformed reply instead of showing an empty overview', async () => {
			mockFetchSuccess({ from: 'a' });
			await expect(getCertificateOverview('a', 'b')).rejects.toThrow('malformed');
		});
	});
});
