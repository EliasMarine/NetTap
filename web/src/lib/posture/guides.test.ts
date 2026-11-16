import { describe, it, expect } from 'vitest';
import { GUIDES } from './guides';
import { POSTURE_SLUGS } from './score';

// Only sources the plan checked: government security agencies, EFF, MITRE and vendor documentation
const ALLOWED_HOSTS = ['cisa.gov', 'nist.gov', 'ncsc.gov.uk', 'eff.org', 'mitre.org', 'support.google.com', 'developers.cloudflare.com', 'docs.suricata.io'];
const allowed = (host: string) => ALLOWED_HOSTS.some((h) => host === h || host.endsWith(`.${h}`));

describe('posture guides', () => {
	it('has a full guide for every category', () => {
		for (const slug of POSTURE_SLUGS) {
			const g = GUIDES[slug];
			expect(g.summary.length, slug).toBeGreaterThan(0);
			expect(g.what.length, slug).toBeGreaterThan(0);
			expect(g.why.length, slug).toBeGreaterThan(0);
			expect(g.practices.length, slug).toBeGreaterThanOrEqual(4);
			expect(g.practices.length, slug).toBeLessThanOrEqual(6);
			expect(g.learnMore.length, slug).toBeGreaterThanOrEqual(3);
		}
	});

	it('links only to https pages on the allow-listed hosts, each once', () => {
		const urls = POSTURE_SLUGS.flatMap((slug) => GUIDES[slug].learnMore.map((l) => l.url));
		for (const url of urls) {
			const u = new URL(url);
			expect(u.protocol, url).toBe('https:');
			expect(allowed(u.hostname), url).toBe(true);
		}
		expect(new Set(urls).size).toBe(urls.length);
	});

	it('follows the voice rules: no three-dot ellipsis, no emoji, no US spellings we use elsewhere', () => {
		const text = JSON.stringify(GUIDES);
		expect(text).not.toContain('...');
		expect(text).not.toMatch(/\p{Extended_Pictographic}/u);
		expect(text).not.toMatch(/\b(behavior|organization|color|center)\b/i);
	});
});
