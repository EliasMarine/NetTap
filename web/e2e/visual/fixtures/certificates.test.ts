import { describe, it, expect } from 'vitest';
import type { CertStats, CertificatesResponse, IssuerChangesResponse } from '../../../src/lib/api/certificates.ts';
import { CERTIFICATE_ROUTES, OVERVIEW, OVERVIEW_EMPTY } from './certificates.ts';

const populated = <T>(path: string) => CERTIFICATE_ROUTES.find((r) => r.path === path)!.populated as T;

describe('certificate fixtures', () => {
	// The page shows these side by side, so a mismatch would be a fixture bug, not an app bug
	it('the stats count the certificates the list holds', () => {
		const { certificates } = populated<CertificatesResponse>('/api/certificates');
		expect(populated<CertStats>('/api/certificates/stats').total_certs).toBe(certificates.length);
	});

	it('every issuer change is for a site in the certificate list', () => {
		const sites = new Set(populated<CertificatesResponse>('/api/certificates').certificates.map((c) => c.domain));
		for (const change of populated<IssuerChangesResponse>('/api/certificates/issuer-changes').changes) {
			expect(sites).toContain(change.domain);
			expect(change.issuer_count).toBe(new Set(change.certificates.map((c) => c.issuer_org)).size);
		}
	});
});

// NET-154: the overview's figures must add up the way the daemon's do, or the page tests and
// visual baselines would show numbers the real page never could
describe('certificate overview fixture', () => {
	const sessions = (rows: { sessions: number }[]) => rows.reduce((n, r) => n + r.sessions, 0);

	it('counts every certificate, site and session once', () => {
		const { summary } = OVERVIEW;
		// Every certificate is referenced by a site here, so `details` holds them all
		const certificates = Object.values(OVERVIEW.details);
		expect(summary.certificates).toBe(certificates.length);
		expect(summary.sites).toBe(OVERVIEW.sites.length);
		expect(summary.sessions).toBe(sessions(certificates));
		expect(summary.sessions).toBe(sessions(OVERVIEW.sites));
		expect(summary.sessions_with_details + summary.sessions_without_details).toBe(summary.sessions);
		expect(summary.certificates_without_details).toBe(certificates.filter((c) => !c.details_available).length);
	});

	it('counts findings by severity and gives every referenced certificate its details', () => {
		const { findings } = OVERVIEW.summary;
		for (const level of ['high', 'medium', 'low'] as const) {
			expect(findings[level]).toBe(OVERVIEW.findings.filter((f) => f.severity === level).length);
		}
		expect(findings.total).toBe(OVERVIEW.findings.length);
		const referenced = [
			...OVERVIEW.sites.flatMap((s) => s.certificates),
			...OVERVIEW.findings.map((f) => f.fingerprint),
			...OVERVIEW.devices.map((d) => d.fingerprint),
		];
		for (const fp of referenced) expect(OVERVIEW.details).toHaveProperty(fp);
	});

	it("counts your devices' certificates from the device rows, and has one finding of each kind", () => {
		expect(OVERVIEW.summary.local_endpoints).toBe(OVERVIEW.devices.length);
		expect(OVERVIEW.summary.local_certificates).toBe(new Set(OVERVIEW.devices.map((d) => d.fingerprint)).size);
		expect(new Set(OVERVIEW.findings.map((f) => f.kind)).size).toBe(OVERVIEW.findings.length);
		expect(OVERVIEW.sites.every((s) => s.worst === (OVERVIEW.findings.find((f) => f.site_id === s.id)?.severity ?? null))).toBe(true);
	});

	it('answers an empty overview with zero counts, not a missing summary', () => {
		expect(OVERVIEW_EMPTY.summary.certificates).toBe(0);
		expect(OVERVIEW_EMPTY.sites).toEqual([]);
	});
});
