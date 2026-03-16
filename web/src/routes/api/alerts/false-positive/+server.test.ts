import { describe, it, expect } from 'vitest';
import * as module from './+server.js';

describe('False Positive Proxy (+server.ts)', () => {
	it('exports a POST handler', () => {
		expect(module).toHaveProperty('POST');
		expect(typeof module.POST).toBe('function');
	});
});
