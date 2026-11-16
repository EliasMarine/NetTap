import { describe, it, expect } from 'vitest';
import { EMPTY_DATA, POSTURE_SLUGS, scoreCategories, type PostureInputs } from './score';
import { buildReport, EXTRAS, listSource, pct, scoreKpi, truncationNote } from './report';
import { POSTURE_ENCRYPTION } from '../../../e2e/visual/fixtures/traffic';

const inputs = (over: Partial<PostureInputs> = {}): PostureInputs => ({ ...EMPTY_DATA, failed: [], health: { health: null, failed: false }, ...over });
const WIN = { from: '2026-11-15T06:00:00.000Z', to: '2026-11-16T06:00:00.000Z' };

describe('buildReport', () => {
	it('builds every category from empty inputs without throwing, each with a Score KPI and at most three KPIs', () => {
		for (const slug of POSTURE_SLUGS) {
			const i = inputs();
			const r = buildReport(slug, { window: WIN, inputs: i, category: scoreCategories(i).find((c) => c.slug === slug)!, extras: {}, failed: [...EXTRAS[slug]], names: new Map() });
			expect(r.kpis[0].key, slug).toBe('score');
			expect(r.kpis.length, slug).toBeLessThanOrEqual(3);
			expect(r.sources.length, slug).toBeGreaterThan(0);
		}
	});

	it('orders findings most severe first, then busiest, and steps by priority', () => {
		const i = inputs({ protocols: { ...EMPTY_DATA.protocols, encryption: { eligible: 21300, encrypted: 19800 } } });
		const r = buildReport('encryption', { window: WIN, inputs: i, category: scoreCategories(i)[0], extras: { encryption: POSTURE_ENCRYPTION }, failed: [], names: new Map() });
		const rank = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
		const order = r.findings.map((f) => rank[f.severity]);
		expect(order).toEqual([...order].sort((a, b) => a - b));
		expect(r.findings[0].title).toBe('Telnet remote login');
		expect(r.steps.map((s) => s.priority)).toEqual(['high', 'high', 'medium', 'low']);
	});
});

describe('report helpers', () => {
	it('pct is 0 for an empty whole', () => {
		expect(pct(1, 0)).toBe(0);
		expect(pct(1, 3)).toBe(33);
	});

	it('listSource: nothing seen, seen but tied to no device, measured (R1-9)', () => {
		const list = { lan: 0, other: 0, rows: [] };
		expect(listSource('k', 'L', { seen: false, total: 0, list, nothing: 'Nothing' }, inputs()).state).toBe('not-measured');
		expect(listSource('k', 'L', { seen: true, total: 5, list, nothing: 'Nothing' }, inputs()).state).toBe('unattributed');
		expect(listSource('k', 'L', { seen: true, total: 0, list, nothing: 'Nothing' }, inputs()).state).toBe('measured');
	});

	it('truncationNote only when devices past the ten made some, with the link when given', () => {
		expect(truncationNote({ lan: 5, other: 0, rows: [] })).toBeNull();
		expect(truncationNote({ lan: 5, other: 1234, rows: [] }, '/dns')).toEqual({ text: 'Showing the 10 busiest devices. Other devices on your network made 1,234 more of these connections.', href: '/dns' });
	});

	it('scoreKpi shows the status word, and no percent sign without a score', () => {
		const [enc] = scoreCategories(inputs());
		expect(scoreKpi(enc)).toMatchObject({ value: 'Not measured', unit: undefined, sub: 'Not measured' });
		const [failed] = scoreCategories(inputs({ failed: ['protocols'] }));
		expect(scoreKpi(failed)).toMatchObject({ value: '—', sub: "Couldn't compute" });
	});
});
