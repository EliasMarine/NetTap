import { describe, it, expect } from 'vitest';
import * as module from './+server.js';

describe('Smart Alerts Summary Proxy (+server.ts)', () => {
	it('exports a GET handler', () => {
		expect(module).toHaveProperty('GET');
		expect(typeof module.GET).toBe('function');
	});
});
