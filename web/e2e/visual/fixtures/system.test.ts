import { describe, it, expect } from 'vitest';
import type { SystemHealth } from '../../../src/lib/api/system.ts';
import { SYSTEM_ROUTES } from './system.ts';

const health = SYSTEM_ROUTES.find((r) => r.path === '/api/system/health')!;

describe('system fixtures', () => {
	// The daemon's healthy is the aggregate status as a tri-state (S5); a fixture where they
	// disagree would test a response the daemon can't send
	it('keeps the aggregate status and healthy in step', () => {
		for (const body of [health.empty, health.populated] as SystemHealth[]) {
			expect(body.healthy).toBe({ healthy: true, problem: false, incomplete: null }[body.status]);
		}
	});
});
