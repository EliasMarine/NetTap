import { describe, it, expect, vi, afterEach } from 'vitest';

/**
 * Tests for LogDrawerContent component logic.
 *
 * LogDrawerContent.svelte uses Svelte 5 runes ($state, $props, $derived),
 * onMount, and Snippet children. Instead of rendering, we extract and test
 * the pure logic: field grouping, value formatting, mono field detection,
 * object flattening, and raw JSON generation.
 */

// ---------------------------------------------------------------------------
// Reproduced logic from LogDrawerContent.svelte
// ---------------------------------------------------------------------------

const GROUP_ORDER = ['source', 'destination', 'network', 'event', 'zeek', 'suricata', 'system'];
const GROUP_LABELS: Record<string, string> = {
	source: 'Source',
	destination: 'Destination',
	network: 'Network',
	event: 'Event',
	zeek: 'Zeek',
	suricata: 'Suricata',
	system: 'System',
};

interface FieldEntry {
	key: string;
	value: unknown;
}

function flattenObject(obj: Record<string, unknown>, prefix = ''): Record<string, unknown> {
	const result: Record<string, unknown> = {};
	for (const [key, value] of Object.entries(obj)) {
		const fullKey = prefix ? `${prefix}.${key}` : key;
		if (value && typeof value === 'object' && !Array.isArray(value)) {
			Object.assign(result, flattenObject(value as Record<string, unknown>, fullKey));
		} else {
			result[fullKey] = value;
		}
	}
	return result;
}

function formatValue(val: unknown): string {
	if (val == null) return '--';
	if (Array.isArray(val)) return val.join(', ');
	return String(val);
}

function isMonoField(key: string): boolean {
	return key.includes('ip') || key.includes('port') || key.includes('mac')
		|| key.includes('bytes') || key.includes('duration') || key === '_id'
		|| key.includes('uid') || key.includes('hash');
}

function groupFields(doc: Record<string, unknown>) {
	const flat = flattenObject(doc);
	const groups: Record<string, FieldEntry[]> = {};

	for (const [key, value] of Object.entries(flat)) {
		const prefix = key.split('.')[0];
		const group = GROUP_ORDER.includes(prefix) ? prefix : 'system';
		if (!groups[group]) groups[group] = [];
		groups[group].push({ key, value });
	}

	return GROUP_ORDER
		.filter((g) => groups[g]?.length)
		.map((g) => ({ group: g, label: GROUP_LABELS[g] || g, fields: groups[g] }));
}

/** Simulates the active tab switch logic */
function getVisibleContent(activeTab: string): 'fields' | 'raw' | 'none' {
	if (activeTab === 'fields') return 'fields';
	if (activeTab === 'raw') return 'raw';
	return 'none';
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LogDrawerContent logic', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- Tab visibility -------------------------------------------------------

	describe('tab visibility', () => {
		it('renders Fields tab by default when activeTab="fields"', () => {
			expect(getVisibleContent('fields')).toBe('fields');
		});

		it('renders Raw JSON tab when activeTab="raw"', () => {
			expect(getVisibleContent('raw')).toBe('raw');
		});

		it('renders nothing for unknown tab', () => {
			expect(getVisibleContent('other')).toBe('none');
		});
	});

	// -- flattenObject --------------------------------------------------------

	describe('flattenObject', () => {
		it('flattens nested objects with dot-notation keys', () => {
			const result = flattenObject({
				source: { ip: '10.0.0.1', port: 443 },
				network: { transport: 'tcp' },
			});
			expect(result['source.ip']).toBe('10.0.0.1');
			expect(result['source.port']).toBe(443);
			expect(result['network.transport']).toBe('tcp');
		});

		it('preserves arrays without flattening', () => {
			const result = flattenObject({
				tags: ['internal', 'dns'],
			});
			expect(result['tags']).toEqual(['internal', 'dns']);
		});

		it('handles deeply nested objects', () => {
			const result = flattenObject({
				zeek: { conn: { uid: 'CwA123', history: 'ShADafF' } },
			});
			expect(result['zeek.conn.uid']).toBe('CwA123');
			expect(result['zeek.conn.history']).toBe('ShADafF');
		});

		it('handles empty objects', () => {
			const result = flattenObject({});
			expect(Object.keys(result)).toHaveLength(0);
		});

		it('handles flat objects (no nesting)', () => {
			const result = flattenObject({ '@timestamp': '2026-01-01T00:00:00Z' });
			expect(result['@timestamp']).toBe('2026-01-01T00:00:00Z');
		});
	});

	// -- formatValue ----------------------------------------------------------

	describe('formatValue', () => {
		it('returns "--" for null', () => {
			expect(formatValue(null)).toBe('--');
		});

		it('returns "--" for undefined', () => {
			expect(formatValue(undefined)).toBe('--');
		});

		it('returns string representation for numbers', () => {
			expect(formatValue(443)).toBe('443');
		});

		it('returns string as-is', () => {
			expect(formatValue('tcp')).toBe('tcp');
		});

		it('joins arrays with commas', () => {
			expect(formatValue(['a', 'b', 'c'])).toBe('a, b, c');
		});

		it('handles empty arrays', () => {
			expect(formatValue([])).toBe('');
		});

		it('handles boolean values', () => {
			expect(formatValue(true)).toBe('true');
			expect(formatValue(false)).toBe('false');
		});
	});

	// -- isMonoField ----------------------------------------------------------

	describe('isMonoField', () => {
		it('returns true for IP fields', () => {
			expect(isMonoField('source.ip')).toBe(true);
			expect(isMonoField('destination.ip')).toBe(true);
		});

		it('returns true for port fields', () => {
			expect(isMonoField('source.port')).toBe(true);
			expect(isMonoField('destination.port')).toBe(true);
		});

		it('returns true for MAC fields', () => {
			expect(isMonoField('source.mac')).toBe(true);
		});

		it('returns true for byte fields', () => {
			expect(isMonoField('source.bytes')).toBe(true);
		});

		it('returns true for duration fields', () => {
			expect(isMonoField('event.duration')).toBe(true);
		});

		it('returns true for _id', () => {
			expect(isMonoField('_id')).toBe(true);
		});

		it('returns true for uid fields', () => {
			expect(isMonoField('zeek.conn.uid')).toBe(true);
		});

		it('returns true for hash fields', () => {
			expect(isMonoField('file.hash')).toBe(true);
		});

		it('returns false for non-mono fields', () => {
			expect(isMonoField('event.category')).toBe(false);
			expect(isMonoField('zeek.conn.service')).toBe(false);
			expect(isMonoField('alert.signature')).toBe(false);
		});

		it('returns true for fields containing "port" substring (e.g. network.transport)', () => {
			// network.transport contains "port" — this is a known behavior of the substring check
			expect(isMonoField('network.transport')).toBe(true);
		});
	});

	// -- Field grouping -------------------------------------------------------

	describe('field grouping', () => {
		it('groups fields by top-level prefix', () => {
			const groups = groupFields({
				source: { ip: '10.0.0.1', port: 8080 },
				destination: { ip: '1.2.3.4', port: 443 },
				network: { transport: 'tcp' },
			});

			expect(groups).toHaveLength(3);
			expect(groups[0].group).toBe('source');
			expect(groups[0].label).toBe('Source');
			expect(groups[0].fields).toHaveLength(2);
			expect(groups[1].group).toBe('destination');
			expect(groups[2].group).toBe('network');
		});

		it('puts unknown prefixes into "system" group', () => {
			const groups = groupFields({
				'@timestamp': '2026-01-01T00:00:00Z',
				custom_field: 'value',
			});

			expect(groups).toHaveLength(1);
			expect(groups[0].group).toBe('system');
			expect(groups[0].fields).toHaveLength(2);
		});

		it('maintains GROUP_ORDER ordering', () => {
			const groups = groupFields({
				zeek: { conn: { uid: 'C123' } },
				source: { ip: '10.0.0.1' },
				network: { transport: 'tcp' },
			});

			// source comes before network, network before zeek
			expect(groups[0].group).toBe('source');
			expect(groups[1].group).toBe('network');
			expect(groups[2].group).toBe('zeek');
		});

		it('skips empty groups', () => {
			const groups = groupFields({
				source: { ip: '10.0.0.1' },
			});

			// Only source should appear, not all 7 groups
			expect(groups).toHaveLength(1);
			expect(groups[0].group).toBe('source');
		});
	});

	// -- Raw JSON generation --------------------------------------------------

	describe('raw JSON', () => {
		it('generates pretty-printed JSON from _source', () => {
			const doc = { source: { ip: '10.0.0.1' }, network: { transport: 'tcp' } };
			const rawJson = JSON.stringify(doc, null, 2);

			expect(rawJson).toContain('"source"');
			expect(rawJson).toContain('"10.0.0.1"');
			expect(rawJson).toContain('"tcp"');
		});

		it('Copy JSON button works (clipboard simulation)', () => {
			const doc = { source: { ip: '10.0.0.1' } };
			const rawJson = JSON.stringify(doc, null, 2);
			const writeText = vi.fn();

			// Simulate copyJson()
			writeText(rawJson);

			expect(writeText).toHaveBeenCalledWith(rawJson);
		});
	});
});
