import { describe, it, expect } from 'vitest';
import { params } from './params';

// OLD CODE START — the test of src/params/posture.ts, before kit 3 moved matchers to src/params.ts (NET-315)
// import { match } from './posture';
// 		expect(match(slug)).toBe(true);
// 		expect(match(other)).toBe(false);
// OLD CODE END

/** What the router sees: the matched value, or undefined when the matcher refuses the param. */
function match(param: string): unknown {
	const result = params.posture['~standard'].validate(param);
	if (result instanceof Promise) throw new Error('posture matcher must be synchronous');
	return result.issues ? undefined : result.value;
}

describe('posture param matcher', () => {
	it('matches the six category slugs and nothing else', () => {
		for (const slug of ['encryption', 'dns-security', 'network-segmentation', 'patch-currency', 'alert-response', 'monitoring-coverage']) {
			expect(match(slug)).toBe(slug);
		}
		for (const other of ['', 'Encryption', 'dns', 'encryption ', '..', '%3Cscript%3E']) {
			expect(match(other)).toBeUndefined();
		}
	});
});
