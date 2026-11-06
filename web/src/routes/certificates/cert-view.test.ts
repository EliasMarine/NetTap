import { describe, it, expect } from 'vitest';
import type { CertDevice, CertFinding, CertSite } from '$lib/api/certificates';
import {
	RANGES,
	deviceVerification,
	findingAdvice,
	findingEvidence,
	findingExplanation,
	findingTitle,
	runsOut,
	runsOutSentence,
	siteMatches,
	siteName,
	siteStatus,
	staleNotice,
	statusList,
	whoUsed,
} from './cert-view';

const NAMES = new Map([
	['192.168.1.42', 'Work laptop'],
	['192.168.1.10', 'Office NAS'],
]);

function finding(over: Partial<CertFinding>): CertFinding {
	return {
		id: 'x',
		kind: 'unverified',
		severity: 'medium',
		site_id: 'a.com',
		site: 'a.com',
		server: '203.0.113.10',
		servers: ['203.0.113.10'],
		fingerprint: 'A',
		sessions: 14,
		last_seen: '2026-11-05T10:00:00Z',
		clients: ['192.168.1.42'],
		clients_total: 1,
		failed: { 'unable to get local issuer certificate': 14 },
		...over,
	};
}

function site(over: Partial<CertSite>): CertSite {
	return {
		id: 'a.com',
		name: 'a.com',
		server: null,
		sessions: 1,
		first_seen: '',
		last_seen: '',
		statuses: { ok: 1 },
		verified: true,
		scope: 'public',
		certificates: ['A'],
		certificates_total: 1,
		clients: ['192.168.1.42'],
		clients_total: 1,
		servers: ['203.0.113.10'],
		servers_total: 1,
		authorities: ["Let's Encrypt"],
		worst: null,
		...over,
	};
}

describe('names', () => {
	it('uses the registry name, else the address, and counts the rest', () => {
		expect(whoUsed(['192.168.1.42', '192.168.1.9'], 3, NAMES)).toBe('Work laptop and 2 more');
		expect(whoUsed(['192.168.1.9'], 1, NAMES)).toBe('192.168.1.9');
		expect(whoUsed([], 0, NAMES)).toBe('');
		expect(siteName(null, '203.0.113.10')).toBe('203.0.113.10');
	});
});

describe('findings in plain English', () => {
	it('never claims a device accepted a certificate, only that it could not be verified', () => {
		const title = findingTitle(finding({}), NAMES);
		expect(title).toBe("Work laptop got a certificate for a.com that couldn't be verified");
		expect(title).not.toMatch(/accepted|trusted/);
	});

	it('names the other authority for the high finding, from the figures it carries', () => {
		const f = finding({ kind: 'unverified-alongside-verified', severity: 'high', authority: 'Proxy CA', other_authority: 'DigiCert' });
		expect(findingEvidence(f)).toBe('a.com · Proxy CA, others got DigiCert · unable to get local issuer certificate');
		expect(findingExplanation(f, undefined, NAMES)).toContain('got a certificate from DigiCert that verified every time');
		expect(findingAdvice(f)).toMatch(/inspects encrypted traffic/);
	});

	it('words weak keys and signatures with the right article', () => {
		const f = finding({ kind: 'weak', severity: 'low', weaknesses: ['MD5 signature', '1024-bit RSA key'] });
		expect(findingExplanation(f, undefined, NAMES)).toContain('uses an MD5 signature and a 1024-bit RSA key');
		expect(findingEvidence(f)).toBe('a.com · MD5 signature · 1024-bit RSA key');
	});

	it("names the device whose certificate runs out, and when", () => {
		const f = finding({ kind: 'device-expiry', severity: 'low', server: '192.168.1.10', port: 5001, days_left: 12, not_after: '2026-11-17T00:00:00Z' });
		expect(findingTitle(f, NAMES)).toBe("Office NAS's certificate for a.com runs out in 12 days");
		expect(findingEvidence(f)).toMatch(/^a\.com · 192\.168\.1\.10:5001 · runs out /);
		expect(findingTitle({ ...f, days_left: -2 }, NAMES)).toBe("Office NAS's certificate for a.com has already run out");
	});

	it('says an expired certificate was sent, never that the device used or accepted it', () => {
		const f = finding({ kind: 'expired-at-use', sessions: 3, not_after: '2026-11-01T00:00:00Z', failed: undefined });
		expect(findingTitle(f, NAMES)).toBe('Work laptop got the certificate for a.com after it had expired');
		expect(findingExplanation(f, undefined, NAMES)).toContain('the server still sent it in 3 sessions');
		expect(`${findingTitle(f, NAMES)} ${findingExplanation(f, undefined, NAMES)}`).not.toMatch(/\bused\b/);
	});

	it('words days left as the end of a sentence, including already run out', () => {
		expect([runsOutSentence(-3), runsOutSentence(0), runsOutSentence(12)]).toEqual([
			'has already run out',
			'runs out within a day',
			'runs out in 12 days',
		]);
	});

	it('says a chain-expired finding without details cannot tell which certificate ran out', () => {
		const f = finding({ kind: 'chain-expired', failed: { 'certificate has expired': 3 }, sessions: 3 });
		expect(findingExplanation(f, undefined, NAMES)).toContain("can't tell which certificate in the chain ran out");
	});

	it('falls back to "A device" when no device was recorded', () => {
		expect(findingTitle(finding({ clients: [], clients_total: 0 }), NAMES)).toMatch(/^A device got/);
	});
});

describe('statuses and days', () => {
	it('lists statuses busiest first, in words, with session counts', () => {
		expect(statusList({ unchecked: 2, ok: 40, 'certificate has expired': 2 })).toBe(
			'verified (40); certificate has expired (2); not checked (2)',
		);
	});

	it('words days left the way the daemon counts them', () => {
		expect([runsOut(null), runsOut(-1), runsOut(0), runsOut(1), runsOut(1200)]).toEqual([
			'Unknown',
			'Already ran out',
			'Within a day',
			'1 day',
			'1,200 days',
		]);
	});

	it('shows a device row as verified, self-signed, its failure, or not checked', () => {
		const base = { verified: false, self_signed: false, statuses: {} } as unknown as CertDevice;
		expect(deviceVerification({ ...base, verified: true })).toBe('Verified');
		expect(deviceVerification({ ...base, self_signed: true })).toBe('Self-signed');
		expect(deviceVerification({ ...base, statuses: { 'self signed certificate': 2, ok: 1 } })).toBe('Self signed certificate');
		expect(deviceVerification({ ...base, statuses: { unchecked: 3 } })).toBe('Not checked');
		expect(deviceVerification({ ...base, statuses: { ok: 40, unchecked: 2 } })).toBe('Partly checked');
	});
});

describe('site status', () => {
	it('is the most serious finding, else what verification showed', () => {
		expect(siteStatus(site({ worst: 'high' }), 'unverified-alongside-verified')).toEqual({ label: 'Unexpected authority', tone: 'is-bad' });
		expect(siteStatus(site({ worst: 'low' }), 'weak')).toEqual({ label: 'Weak', tone: 'is-warn' });
		expect(siteStatus(site({}), undefined)).toEqual({ label: 'Verified', tone: 'is-ok' });
		expect(siteStatus(site({ verified: false, statuses: { unchecked: 2 } }), undefined).label).toBe('Not checked');
		// most sessions verified and the rest unchecked is not "Not checked"
		expect(siteStatus(site({ verified: false, statuses: { ok: 40, unchecked: 2 } }), undefined).label).toBe('Partly checked');
		expect(siteStatus(site({ verified: false, scope: 'local', statuses: { 'self signed certificate': 2 } }), undefined).label).toBe(
			'Not verified, your network',
		);
	});

	it('matches a search on site, authority or device name', () => {
		expect(siteMatches(site({}), 'work lap', NAMES)).toBe(true);
		expect(siteMatches(site({}), "let's", NAMES)).toBe(true);
		expect(siteMatches(site({}), 'nope', NAMES)).toBe(false);
		expect(siteMatches(site({}), '  ', NAMES)).toBe(true);
	});
});

describe('window notices', () => {
	const at = new Date(2026, 10, 5, 10, 2);
	const [day, week, month] = RANGES;

	it('names both windows when a different window failed, so the figures are never misread', () => {
		expect(staleNotice(month, day, at, 'It took too long.')).toBe(
			"Couldn't load the last 30 days; showing the last 24 hours loaded at 10:02. It took too long.",
		);
	});

	it('uses the shared stale wording when the same window failed to refresh', () => {
		expect(staleNotice(week, week, at, '')).toBe("Couldn't refresh certificate data; showing the last figures loaded.");
	});
});
