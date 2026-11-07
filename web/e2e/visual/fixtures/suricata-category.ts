/**
 * Fixtures for GET /api/alerts/suricata/{name} (daemon/api/suricata_categories.py, NET-160 slice
 * 2b-2), through the web catch-all. Figures add up the way the daemon's do: the severities and the
 * timeline make the total, and each address list plus its missing count makes it too.
 *
 * One category shows every state the page words: a null, an empty and a literal "Unknown" rule
 * name, sources with a missing count, targets the snapshot couldn't read in full, and two tactics
 * Malcolm tagged beside it.
 */
import type { SuricataCategoryFigures } from '../../../src/lib/api/drilldown.ts';
import { hourly } from './drilldown.ts';
import { HOUR, iso, MIN, type FixtureRoute } from './types.ts';
import { WINDOW } from './net-world.ts';

export const SURICATA_CATEGORY: SuricataCategoryFigures = {
	name: 'Misc activity',
	...WINDOW,
	total: 1240,
	severity: { high: 40, medium: 300, low: 880, info: 20 },
	timeline: hourly(1240),
	rules: {
		rows: [
			{ rule_name: 'ET INFO Observed DNS Query to .cloud TLD', count: 700, last_seen: iso(2 * MIN) },
			{ rule_name: 'ET POLICY GNU/Linux APT User-Agent Outbound', count: 500, last_seen: iso(3 * HOUR) },
			{ rule_name: null, count: 30, last_seen: iso(5 * HOUR) },
			{ rule_name: '', count: 6, last_seen: iso(6 * HOUR) },
			{ rule_name: 'Unknown', count: 4, last_seen: null },
		],
		distinct: 5,
		examined: 5,
		complete: true,
	},
	sources: {
		rows: [
			{ ip: '192.168.1.20', count: 800 },
			{ ip: '192.168.1.22', count: 300 },
			{ ip: '2001:db8::5', count: 120 },
		],
		distinct: 3,
		examined: 3,
		complete: true,
		missing: 20,
	},
	targets: {
		rows: [
			{ ip: '198.51.100.10', count: 600 },
			{ ip: '203.0.113.5', count: 400 },
		],
		distinct: null,
		examined: 5000,
		complete: false,
		missing: 0,
	},
	also_tagged: {
		rows: [
			{ category: 'Command_And_Control', count: 30 },
			{ category: 'Discovery', count: 12 },
		],
		distinct: 2,
		examined: 2,
		complete: true,
	},
};

export const SURICATA_CATEGORY_EMPTY: SuricataCategoryFigures = {
	name: 'Misc activity',
	...WINDOW,
	total: 0,
	severity: { high: 0, medium: 0, low: 0, info: 0 },
	timeline: [],
	rules: { rows: [], distinct: 0, examined: 0, complete: true },
	sources: { rows: [], distinct: 0, examined: 0, complete: true, missing: 0 },
	targets: { rows: [], distinct: 0, examined: 0, complete: true, missing: 0 },
	also_tagged: { rows: [], distinct: 0, examined: 0, complete: true },
};

export const SURICATA_CATEGORY_ROUTES: FixtureRoute[] = [
	// any name: the daemon receives it percent-encoded, "/" included
	{ path: /^\/api\/alerts\/suricata\/.+$/, empty: SURICATA_CATEGORY_EMPTY, populated: SURICATA_CATEGORY },
];
