import { describe, it, expect } from 'vitest';
import { match } from './posture';

describe('posture param matcher', () => {
	it('matches the six category slugs and nothing else', () => {
		for (const slug of ['encryption', 'dns-security', 'network-segmentation', 'patch-currency', 'alert-response', 'monitoring-coverage']) {
			expect(match(slug)).toBe(true);
		}
		for (const other of ['', 'Encryption', 'dns', 'encryption ', '..', '%3Cscript%3E']) {
			expect(match(other)).toBe(false);
		}
	});
});
