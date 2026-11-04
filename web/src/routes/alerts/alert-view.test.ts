import { describe, it, expect } from 'vitest';
import type { Alert } from '$api/alerts';
import { alertAdvice, alertLevel, alertTitle, groupAlerts, logExplorerHref, shortSeen } from './alert-view';

const alert = (id: string, over: { sev?: number; sig?: string; sid?: number; cat?: string; src?: string; ts?: string } = {}): Alert => ({
	_id: id,
	_index: 'x',
	timestamp: over.ts ?? '2026-11-03T10:00:00Z',
	alert: { signature: over.sig ?? `Sig ${id}`, signature_id: over.sid ?? 1, severity: over.sev ?? 2, category: over.cat ?? 'Misc' },
	src_ip: over.src ?? '10.0.0.1',
	acknowledged: false,
});

describe('alertLevel', () => {
	it('maps Suricata 1–3 and treats anything else as info', () => {
		expect([1, 2, 3, 4, undefined].map(alertLevel)).toEqual(['high', 'medium', 'low', 'info', 'info']);
	});
});

describe('alertTitle and alertAdvice', () => {
	it('uses the enrichment, then the category, and never invents advice', () => {
		expect(alertTitle({ ...alert('a'), plain_description: 'Plain words.' })).toBe('Plain words.');
		expect(alertTitle(alert('a', { cat: 'Potentially Bad Traffic' }))).toBe('Potentially Bad Traffic');
		expect(alertTitle({ ...alert('a'), alert: {} })).toBe('Uncategorised alert');
		expect(alertAdvice({ ...alert('a'), recommendation: 'Patch it.' })).toBe('Patch it.');
		expect(alertAdvice({ ...alert('a'), recommendation: '  ' })).toBe('No specific advice for this alert yet.');
	});
});

describe('logExplorerHref', () => {
	it('queries both ends, or only the end that exists', () => {
		const only = { ...alert('a'), dest_ip: undefined };
		expect(decodeURIComponent(logExplorerHref(only))).toBe('/logs?query=(source.ip:"10.0.0.1" OR destination.ip:"10.0.0.1")');
	});
});

describe('groupAlerts', () => {
	it('merges a signature from one source into one line with the count and the newest event', () => {
		const [group] = groupAlerts([
			alert('old', { ts: '2026-11-03T08:00:00Z' }),
			alert('new', { ts: '2026-11-03T09:00:00Z' }),
			alert('other-source', { src: '10.0.0.2' }),
		]);
		expect(group.count).toBe(3);
		const merged = group.lines.find((l) => l.count === 2)!;
		expect(merged.alert._id).toBe('new');
		expect(merged.lastSeen).toBe('2026-11-03T09:00:00Z');
		expect(group.lines).toHaveLength(2);
	});

	it('sorts lines by severity then count, and groups by their worst line then their count', () => {
		const groups = groupAlerts([
			alert('l1', { cat: 'Busy low', sev: 3, sid: 1 }),
			alert('l2', { cat: 'Busy low', sev: 3, sid: 1 }),
			alert('l3', { cat: 'Busy low', sev: 3, sid: 2 }),
			alert('m1', { cat: 'Medium', sev: 2, sid: 3 }),
			alert('h1', { cat: 'Has high', sev: 3, sid: 4 }),
			alert('h2', { cat: 'Has high', sev: 1, sid: 5 }),
		]);
		expect(groups.map((g) => g.title)).toEqual(['Has high', 'Medium', 'Busy low']);
		expect(groups[0].lines.map((l) => l.level)).toEqual(['high', 'low']);
		expect(groups[2].lines.map((l) => l.count)).toEqual([2, 1]);
	});

	it('puts alerts without a category under Uncategorised, and returns nothing for no alerts', () => {
		expect(groupAlerts([{ ...alert('a'), alert: { severity: 1 } }])[0].title).toBe('Uncategorised');
		expect(groupAlerts([])).toEqual([]);
	});
});

describe('shortSeen', () => {
	it('shows the time today and the date before today', () => {
		const now = new Date(2026, 10, 3, 22, 0);
		expect(shortSeen(new Date(2026, 10, 3, 21, 5).toISOString(), now)).toBe('21:05');
		expect(shortSeen(new Date(2026, 10, 2, 23, 59).toISOString(), now)).toBe('2 Nov');
		expect(shortSeen('not a time', now)).toBe('not a time');
	});
});
