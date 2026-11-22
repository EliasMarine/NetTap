import { describe, it, expect } from 'vitest';
import { ROUTES } from './index.ts';
import { REPORT_ROUTES } from './reports.ts';

describe('fixture daemon routes', () => {
	// NET-340: a route file left out of the index answers 404, and the page under test shows its error state
	it('serves the weekly report routes', () => {
		for (const route of REPORT_ROUTES) expect(ROUTES).toContain(route);
	});

	it('answers each exact path once per method, so no route hides another', () => {
		const keys = ROUTES.filter((r) => typeof r.path === 'string').map((r) => `${r.method ?? '*'} ${String(r.path)}`);
		expect(keys.filter((k, i) => keys.indexOf(k) !== i)).toEqual([]);
	});
});
