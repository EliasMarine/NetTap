import { describe, it, expect } from 'vitest';

/**
 * Tests for SessionTimeline.svelte pure logic.
 * SVG rendering requires a real DOM; we test formatting and data derivation.
 */

// Reproduce constants and functions from the component

const PROTO_COLORS: Record<string, string> = {
	tcp: 'var(--cyan)',
	udp: 'var(--green)',
	tls: 'var(--purple)',
	dns: 'var(--amber)',
	icmp: 'var(--red)',
	http: 'var(--blue)',
};

const PROTO_ORDER = ['tcp', 'udp', 'tls', 'dns', 'icmp', 'http'];

interface TimelineBucket {
	timestamp: string;
	total: number;
	protocols: Record<string, number>;
}

function formatShortTimestamp(ts: string): string {
	if (!ts) return '';
	try {
		const d = new Date(ts);
		const h = d.getHours().toString().padStart(2, '0');
		const m = d.getMinutes().toString().padStart(2, '0');
		const mon = (d.getMonth() + 1).toString().padStart(2, '0');
		const day = d.getDate().toString().padStart(2, '0');
		return `${mon}/${day} ${h}:${m}`;
	} catch {
		return ts;
	}
}

function protoColor(proto: string): string {
	return PROTO_COLORS[proto.toLowerCase()] || 'var(--text-muted)';
}

function deriveActiveProtocols(buckets: TimelineBucket[]): string[] {
	const set = new Set<string>();
	for (const b of buckets) {
		for (const p of Object.keys(b.protocols)) {
			set.add(p);
		}
	}
	return PROTO_ORDER.filter((p) => set.has(p)).concat(
		[...set].filter((p) => !PROTO_ORDER.includes(p)).sort()
	);
}

describe('SessionTimeline logic', () => {
	describe('formatShortTimestamp', () => {
		it('formats ISO timestamp to short form with date and time', () => {
			const result = formatShortTimestamp('2026-03-17T14:30:00Z');
			// Result includes month/day and hour:minute (local time)
			expect(result).toMatch(/\d{2}\/\d{2} \d{2}:\d{2}/);
		});

		it('returns empty string for empty input', () => {
			expect(formatShortTimestamp('')).toBe('');
		});

		it('produces non-empty output for valid timestamp', () => {
			const result = formatShortTimestamp('2026-03-17T14:30:00Z');
			expect(result.length).toBeGreaterThan(0);
			expect(result).toContain('/');
			expect(result).toContain(':');
		});
	});

	describe('protoColor', () => {
		it('returns cyan for tcp', () => expect(protoColor('tcp')).toBe('var(--cyan)'));
		it('returns green for udp', () => expect(protoColor('udp')).toBe('var(--green)'));
		it('returns purple for TLS (case-insensitive)', () => expect(protoColor('TLS')).toBe('var(--purple)'));
		it('returns fallback for unknown protocol', () => expect(protoColor('sctp')).toBe('var(--text-muted)'));
	});

	describe('deriveActiveProtocols', () => {
		it('returns empty for empty buckets', () => {
			expect(deriveActiveProtocols([])).toEqual([]);
		});

		it('returns protocols in PROTO_ORDER', () => {
			const buckets: TimelineBucket[] = [
				{ timestamp: '', total: 100, protocols: { udp: 30, tcp: 70 } },
			];
			const result = deriveActiveProtocols(buckets);
			expect(result[0]).toBe('tcp');
			expect(result[1]).toBe('udp');
		});

		it('appends unknown protocols after known ones', () => {
			const buckets: TimelineBucket[] = [
				{ timestamp: '', total: 100, protocols: { sctp: 10, tcp: 90 } },
			];
			const result = deriveActiveProtocols(buckets);
			expect(result[0]).toBe('tcp');
			expect(result[result.length - 1]).toBe('sctp');
		});

		it('deduplicates protocols across buckets', () => {
			const buckets: TimelineBucket[] = [
				{ timestamp: '', total: 50, protocols: { tcp: 50 } },
				{ timestamp: '', total: 30, protocols: { tcp: 20, udp: 10 } },
			];
			const result = deriveActiveProtocols(buckets);
			expect(result.filter((p) => p === 'tcp')).toHaveLength(1);
		});
	});

	describe('maxTotal computation', () => {
		it('computes max from bucket totals', () => {
			const buckets: TimelineBucket[] = [
				{ timestamp: '', total: 100, protocols: {} },
				{ timestamp: '', total: 250, protocols: {} },
				{ timestamp: '', total: 150, protocols: {} },
			];
			const maxTotal = Math.max(1, ...buckets.map((b) => b.total));
			expect(maxTotal).toBe(250);
		});

		it('returns 1 for empty buckets', () => {
			const maxTotal = Math.max(1, ...[].map((b: TimelineBucket) => b.total));
			expect(maxTotal).toBe(1);
		});
	});

	describe('bar height calculation', () => {
		it('computes proportional bar height', () => {
			const maxTotal = 200;
			const chartH = 160;
			const count = 100;
			const h = (count / maxTotal) * chartH;
			expect(h).toBe(80);
		});

		it('handles zero count', () => {
			const maxTotal = 200;
			const chartH = 160;
			const h = (0 / maxTotal) * chartH;
			expect(h).toBe(0);
		});
	});
});
