import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getCertificates,
	getExpiringCerts,
	getSelfSignedCerts,
	getIssuerChanges,
	getCertStats,
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

		it('returns empty on HTTP error', async () => {
			mockFetchFailure();
			const result = await getCertificates();
			expect(result.certificates).toEqual([]);
		});

		it('returns empty on network error', async () => {
			mockFetchReject();
			const result = await getCertificates();
			expect(result.certificates).toEqual([]);
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

		it('returns empty on error', async () => {
			mockFetchFailure();
			const result = await getExpiringCerts();
			expect(result.certificates).toEqual([]);
		});

		it('returns empty on network error', async () => {
			mockFetchReject();
			const result = await getExpiringCerts();
			expect(result.certificates).toEqual([]);
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

		it('returns empty on error', async () => {
			mockFetchReject();
			const result = await getSelfSignedCerts();
			expect(result.certificates).toEqual([]);
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

		it('returns empty on error', async () => {
			mockFetchFailure();
			const result = await getIssuerChanges();
			expect(result.changes).toEqual([]);
		});
	});

	// -- getCertStats ---------------------------------------------------------

	describe('getCertStats', () => {
		it('returns stats on success', async () => {
			mockFetchSuccess({
				total_certs: 42,
				expiring_count: 3,
				self_signed_count: 1,
				issuer_changes_count: 0,
				from: '',
				to: '',
			});

			const stats = await getCertStats();
			expect(stats.total_certs).toBe(42);
			expect(stats.expiring_count).toBe(3);
		});

		it('returns zeros on HTTP error', async () => {
			mockFetchFailure();
			const stats = await getCertStats();
			expect(stats.total_certs).toBe(0);
		});

		it('returns zeros on network error', async () => {
			mockFetchReject();
			const stats = await getCertStats();
			expect(stats.total_certs).toBe(0);
		});
	});
});
