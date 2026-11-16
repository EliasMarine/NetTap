import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { EMPTY_DATA, LEGACY_PROTOCOLS, POSTURE_SLUGS, isPostureSlug, legacyCounts, scoreCategories, type PostureInputs } from './score';

// The overview's scoring, moved here so the category pages score exactly as the overview does

const inputs = (over: Partial<PostureInputs> = {}): PostureInputs => ({
	...EMPTY_DATA,
	failed: [],
	health: { health: null, failed: false },
	...over,
});
const bySlug = (i: PostureInputs) => Object.fromEntries(scoreCategories(i).map((c) => [c.slug, c]));

describe('scoreCategories', () => {
	it('returns the six categories in the overview order, one per slug', () => {
		expect(scoreCategories(inputs()).map((c) => c.slug)).toEqual([...POSTURE_SLUGS]);
	});

	// OLD CODE START — NET-308: every eligible connection and every lookup (G11: 15% and 29%)
	// it('scores Encryption and DNS from the daemon figures (G11: 15% and 29%)', () => { … });
	// it('takes 10 off segmentation per device without a score, and coverage is the share scored', () => { … });
	// it('scores Alert response 0 with alerts and no investigations, and needs the investigations then', () => { … });
	// OLD CODE END
	it('scores Encryption and DNS from the daemon figures (G11 2026-11-16: 74% and 52%)', () => {
		const c = bySlug(
			inputs({
				protocols: {
					from: '',
					to: '',
					protocols: [],
					services: [{ name: 'unknown', count: 10 }],
					encryption: { eligible: 177_870, encrypted: 131_356, one_way: 907_976 },
					dns: { plain: 23_317, over_tls: 24_903, local: { plain: 27_896, over_tls: 0 } },
				},
			}),
		);
		expect(c['encryption'].score).toBe(74);
		expect(c['encryption'].findings).toContain('131,356 of 177,870 connections with data both ways encrypted (74%)');
		expect(c['dns-security'].score).toBe(52);
		expect(c['dns-security'].findings).toContain('27,896 lookups to your own resolvers, judged by what they send out');
	});

	it('leaves Encryption Not measured when nothing carried data both ways, and says why', () => {
		const enc = bySlug(
			inputs({ protocols: { from: '', to: '', protocols: [], services: [{ name: 'unknown', count: 5 }], encryption: { eligible: 0, encrypted: 0, one_way: 5 } } }),
		)['encryption'];
		expect(enc.status).toBe('Not measured');
		expect(enc.findings[0]).toMatch(/^No connection carried data both ways; 5 carried data one way or none/);
	});

	it("reads DNS Not measured when only your own resolvers' lookups were seen", () => {
		const dns = bySlug(
			inputs({ protocols: { from: '', to: '', protocols: [], services: [], dns: { plain: 0, over_tls: 0, local: { plain: 40, over_tls: 25 } } } }),
		)['dns-security'];
		expect(dns.empty).toBe(true);
		expect(dns.findings).toContain("Your resolvers' own lookups out aren't visible to NetTap, so there is nothing to score");
	});

	it('scores segmentation from IoT isolation, and coverage is still the share scored', () => {
		const c = bySlug(
			inputs({
				deviceCount: { from: '', to: '', count: 4 },
				riskScores: { scores: [{ ip: '192.168.1.2', score: 1, level: 'low', factors: [] }] },
				isolation: { segmentation_score: 75, segmentation_grade: 'C', pairs: [], recommendation: 'Consider a VLAN.' },
			}),
		);
		expect(c['network-segmentation'].score).toBe(75);
		expect(c['network-segmentation'].needs).toEqual(['isolation']);
		expect(c['network-segmentation'].findings).toContain('Consider a VLAN.');
		expect(c['monitoring-coverage'].score).toBe(25);
		expect(c['monitoring-coverage'].status).toBe('Poor');
	});

	it('reads segmentation Not measured with no smart devices, and Couldn\'t compute when isolation failed', () => {
		expect(bySlug(inputs())['network-segmentation'].status).toBe('Not measured');
		expect(bySlug(inputs())['network-segmentation'].findings).toEqual(['No smart (IoT) devices detected yet']);
		const failed = bySlug(inputs({ failed: ['isolation'], isolation: { ...EMPTY_DATA.isolation, segmentation_score: 100 } }))['network-segmentation'];
		expect(failed.status).toBe("Couldn't compute");
		expect(failed.findings[0]).toBe("Couldn't load smart-device isolation: the request failed.");
		// risk scores no longer feed it
		expect(bySlug(inputs({ failed: ['risk'] }))['network-segmentation'].status).toBe('Not measured');
	});

	const response = (needing: number, investigated: number) => ({ ...EMPTY_DATA.alertResponse, needing, investigated });

	it('scores Alert response as the share of high-severity rules with an investigation (G11: 0 of 13)', () => {
		const alerts = { from: '', to: '', counts: { total: 853, high: 315, medium: 219, low: 319 } };
		const g11 = bySlug(inputs({ alertCounts: alerts, alertResponse: response(13, 0) }))['alert-response'];
		expect(g11.score).toBe(0);
		// OLD CODE: expect(g11.needs).toEqual(['alerts', 'response']); (NET-308 review: it reads the follow-up only)
		expect(g11.needs).toEqual(['response']);
		// a failed alert count leaves the score standing
		expect(bySlug(inputs({ alertResponse: response(13, 4), failed: ['alerts'] }))['alert-response'].score).toBe(31);
		expect(g11.findings[0]).toBe('13 high-severity rule(s) needed a response; 0 have an investigation open in the last 24 hours');
		expect(bySlug(inputs({ alertCounts: alerts, alertResponse: response(13, 4) }))['alert-response'].score).toBe(31);
	});

	it('reads a reply from a daemon before NET-308 (no one_way, no local) without throwing (review M1)', () => {
		const old = { ...EMPTY_DATA.protocols, encryption: { eligible: 200, encrypted: 120 }, dns: { plain: 90, over_tls: 10 } };
		const c = bySlug(inputs({ protocols: old }));
		expect([c.encryption.score, c['dns-security'].score]).toEqual([60, 10]);
	});

	it('reads Alert response Not measured when nothing needed a response, whatever the alert count', () => {
		const alerts = { from: '', to: '', counts: { total: 757, high: 0, medium: 219, low: 538 } };
		const c = bySlug(inputs({ alertCounts: alerts }))['alert-response'];
		expect(c.status).toBe('Not measured');
		// the pipeline state is still being checked, so the zero isn't trusted yet
		expect(c.findings[0]).toBe("Can't tell if anything needed a response, so there is nothing to score · Data pipeline now: Checking…");
		const fresh = { health: { pipeline: { state: 'fresh' } } as unknown as NonNullable<PostureInputs['health']['health']>, failed: false };
		expect(bySlug(inputs({ health: fresh }))['alert-response'].findings[0]).toMatch(/^Nothing needed a response in the last 24 hours, so there is nothing to score · /);
		expect(bySlug(inputs({ failed: ['response'] }))['alert-response'].findings[0]).toBe("Couldn't load alert follow-up: the request failed.");
	});

	it('scores Patch currency per connection, so a two-label connection counts once (G11: 98)', () => {
		const services = [
			{ name: 'http', count: 30 },
			{ name: 'ssl', count: 30 },
		];
		// 30 connections labelled ssl and http: the labels say 50%, the connections 0 of 30 left
		const two = bySlug(inputs({ protocols: { from: '', to: '', protocols: [], services, patch: { legacy: 30, connections: 30 } } }))['patch-currency'];
		expect(two.score).toBe(0);
		const g11 = bySlug(inputs({ protocols: { from: '', to: '', protocols: [], services, patch: { legacy: 28_460, connections: 1_340_157 } } }))['patch-currency'];
		expect(g11.score).toBe(98);
		expect(bySlug(inputs())['patch-currency'].status).toBe('Not measured');
	});

	it('marks a category with nothing to score Not measured, and one whose input failed Couldn\'t compute', () => {
		const c = bySlug(inputs({ failed: ['risk'] }));
		expect(c['encryption'].status).toBe('Not measured');
		expect(c['encryption'].empty).toBe(true);
		expect(c['monitoring-coverage'].score).toBeNull();
		expect(c['monitoring-coverage'].status).toBe("Couldn't compute");
		expect(c['monitoring-coverage'].findings[0]).toBe("Couldn't load risk scores: the request failed.");
	});
});

describe('legacyCounts', () => {
	// OLD CODE: it('counts labels as the score does, so a two-label connection counts once per label', …) (NET-308: the score counts connections)
	it('counts each legacy label, for the findings and bars', () => {
		// "http" and "ssl,http" records both carry http; the service list counts each label
		const counts = legacyCounts([
			{ name: 'http', count: 30 },
			{ name: 'ssl', count: 50 },
			{ name: 'telnet', count: 2 },
			{ name: 'unknown', count: 18 },
		]);
		expect(counts).toEqual({ http: 30, ftp: 0, telnet: 2, pop3: 0, imap: 0 });
	});
});

// The Patch page's device lists (daemon) must count the same protocols as the score (here)
describe('LEGACY_PROTOCOLS', () => {
	// OLD CODE: it("matches daemon/api/posture.py's list", …) (NET-308: it moved to daemon/api/traffic.py)
	it("matches daemon/api/traffic.py's list", () => {
		const source = readFileSync(resolve(__dirname, '../../../../daemon/api/traffic.py'), 'utf-8');
		const daemon = JSON.parse(source.match(/^LEGACY_PROTOCOLS = (\[.*\])$/m)![1]);
		expect([...LEGACY_PROTOCOLS]).toEqual(daemon);
	});
});

describe('isPostureSlug', () => {
	it('knows the six slugs only', () => {
		expect(POSTURE_SLUGS.every(isPostureSlug)).toBe(true);
		expect(isPostureSlug('Encryption')).toBe(false);
		expect(isPostureSlug('')).toBe(false);
	});
});
