import { describe, it, expect } from 'vitest';
import { EMPTY_DATA, POSTURE_SLUGS, isPostureSlug, legacyCounts, scoreCategories, type PostureInputs } from './score';

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

	it('scores Encryption and DNS from the daemon figures (G11: 15% and 29%)', () => {
		const c = bySlug(
			inputs({
				protocols: {
					from: '',
					to: '',
					protocols: [],
					services: [{ name: 'unknown', count: 10 }],
					encryption: { eligible: 1_036_286, encrypted: 155_334 },
					dns: { plain: 53_332, over_tls: 21_876 },
				},
			}),
		);
		expect(c['encryption'].score).toBe(15);
		expect(c['encryption'].status).toBe('Poor');
		expect(c['dns-security'].score).toBe(29);
	});

	it('takes 10 off segmentation per device without a score, and coverage is the share scored', () => {
		const c = bySlug(
			inputs({
				deviceCount: { from: '', to: '', count: 4 },
				riskScores: { scores: [{ ip: '192.168.1.2', score: 1, level: 'low', factors: [] }] },
			}),
		);
		expect(c['network-segmentation'].score).toBe(70);
		expect(c['monitoring-coverage'].score).toBe(25);
		expect(c['monitoring-coverage'].status).toBe('Poor');
	});

	it('scores Alert response 0 with alerts and no investigations, and needs the investigations then', () => {
		const c = bySlug(inputs({ alertCounts: { from: '', to: '', counts: { total: 757, high: 295, medium: 219, low: 243 } } }));
		expect(c['alert-response'].score).toBe(0);
		expect(c['alert-response'].needs).toEqual(['alerts', 'investigations']);
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
	it('counts labels as the score does, so a two-label connection counts once per label', () => {
		// "http" and "ssl,http" records both carry http; the service list counts each label
		const counts = legacyCounts([
			{ name: 'http', count: 30 },
			{ name: 'ssl', count: 50 },
			{ name: 'telnet', count: 2 },
			{ name: 'unknown', count: 18 },
		]);
		expect(counts).toEqual({ legacy: 32, total: 100, byName: { http: 30, ftp: 0, telnet: 2, pop3: 0, imap: 0 } });
	});

	it('is the Patch currency score\'s numerator and denominator', () => {
		const services = [
			{ name: 'http', count: 27_494 },
			{ name: 'unknown', count: 1_262_506 },
		];
		const patch = bySlug(inputs({ protocols: { from: '', to: '', protocols: [], services } }))['patch-currency'];
		const { legacy, total } = legacyCounts(services);
		expect(patch.score).toBe(Math.round(100 - (legacy / total) * 100));
		expect(patch.score).toBe(98);
	});
});

describe('isPostureSlug', () => {
	it('knows the six slugs only', () => {
		expect(POSTURE_SLUGS.every(isPostureSlug)).toBe(true);
		expect(isPostureSlug('Encryption')).toBe(false);
		expect(isPostureSlug('')).toBe(false);
	});
});
