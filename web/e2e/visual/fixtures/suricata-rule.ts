/**
 * Fixtures for GET /api/alerts/rule/{name} (daemon/api/suricata_rule.py, the rule page), through
 * the web catch-all. Figures add up the way the daemon's do: the severities and the timeline make
 * the total, and the SIDs' alerts plus the alerts without a SID make it too.
 *
 * One long ET name shows every state the page words: two SIDs whose facts differ (CVE, KEV and
 * ATT&CK on one, nothing on the other), devices as source, target and both, a remote list the
 * discovery cut short, an IPv6 address whose locality is unknown, and verified links.
 */
import type { SuricataRuleFigures } from '../../../src/lib/api/drilldown.ts';
import { hourly } from './drilldown.ts';
import { HOUR, iso, MIN, type FixtureRoute } from './types.ts';
import { WINDOW } from './net-world.ts';

export const RULE_NAME = 'ET EXPLOIT Apache HTTP Server 2.4.49 - Path Traversal Attempt (CVE-2021-41773) M2 / outbound & encoded 50%';

const SURICATA_DOCS = { label: 'How Suricata rules work', url: 'https://docs.suricata.io/en/latest/rules/intro.html', source: 'Suricata' };
const T1190 = { label: 'MITRE ATT&CK T1190: Exploit Public-Facing Application', url: 'https://attack.mitre.org/techniques/T1190/', source: 'MITRE ATT&CK' };

export const SURICATA_RULE: SuricataRuleFigures = {
	name: RULE_NAME,
	...WINDOW,
	interval: '1h',
	activity: false,
	total: 180,
	counted_total: 180,
	activity_total: 12,
	severity: { high: 150, medium: 30, low: 0, info: 0 },
	timeline: hourly(180),
	first_seen: iso(23 * HOUR),
	last_seen: iso(4 * MIN),
	rules: [
		{
			sid: '2034125',
			alerts: 120,
			categories: ['Attempted Administrator Privilege Gain'],
			et_ratings: ['Major'],
			techniques: [{ id: 'T1190', name: 'Exploit Public-Facing Application' }],
			tactics: [{ id: 'TA0001', name: 'Initial Access' }],
			cves: ['CVE-2021-41773'],
			cisa_kev: true,
			dbl_lists: [],
			credential: false,
			advice: null,
			learn_more: [
				{ label: 'CVE-2021-41773 in the National Vulnerability Database', url: 'https://nvd.nist.gov/vuln/detail/CVE-2021-41773', source: 'NIST NVD' },
				{ label: "CISA's catalogue of known exploited vulnerabilities", url: 'https://www.cisa.gov/known-exploited-vulnerabilities-catalog', source: 'CISA' },
				T1190,
				{ label: 'MITRE ATT&CK tactic TA0001: Initial Access', url: 'https://attack.mitre.org/tactics/TA0001/', source: 'MITRE ATT&CK' },
			],
		},
		{
			sid: '2034126',
			alerts: 60,
			categories: [],
			et_ratings: [],
			techniques: [],
			tactics: [],
			cves: [],
			cisa_kev: false,
			dbl_lists: [],
			credential: false,
			advice: null,
			learn_more: [],
		},
	],
	rules_complete: true,
	no_sid: 0,
	explanation: {
		family: 'exploit',
		what: 'This rule matches traffic shaped like an attempt to exploit a known software flaw.',
		risk: 'Attempts like this are common on the internet and usually fail against up-to-date software. It matters most when the target runs the affected software and can be reached from the internet.',
		todo: 'Make sure the targeted device runs up-to-date software, and check whether it should be reachable from the internet at all.',
	},
	learn_more: [T1190, SURICATA_DOCS],
	devices: {
		rows: [
			{ ip: '192.168.1.20', as_source: 0, as_target: 110, alerts: 110, first_seen: iso(23 * HOUR), last_seen: iso(4 * MIN) },
			{ ip: '192.168.1.22', as_source: 4, as_target: 40, alerts: 40, first_seen: iso(9 * HOUR), last_seen: iso(2 * HOUR) },
			{ ip: '192.168.1.30', as_source: 6, as_target: 0, alerts: 6, first_seen: iso(5 * HOUR), last_seen: iso(5 * HOUR) },
		],
		distinct: 3,
		examined: 3,
		complete: true,
		picked_by: 'source_plus_destination',
	},
	remotes: {
		rows: [
			{ ip: '198.51.100.10', as_source: 90, as_target: 0, alerts: 90, first_seen: iso(23 * HOUR), last_seen: iso(4 * MIN) },
			{ ip: '203.0.113.5', as_source: 50, as_target: 4, alerts: 54, first_seen: iso(12 * HOUR), last_seen: iso(1 * HOUR) },
		],
		distinct: null,
		examined: 5000,
		complete: false,
		picked_by: 'source_plus_destination',
	},
	unplaced: {
		rows: [{ ip: '2001:db8::5', as_source: 20, as_target: 0, alerts: 20, first_seen: iso(6 * HOUR), last_seen: iso(3 * HOUR) }],
		distinct: 1,
		examined: 1,
		complete: true,
		picked_by: 'source_plus_destination',
	},
	missing_address: 0,
};

export const SURICATA_RULE_EMPTY: SuricataRuleFigures = {
	name: RULE_NAME,
	...WINDOW,
	interval: '1h',
	activity: false,
	total: 0,
	counted_total: 0,
	activity_total: 0,
	severity: { high: 0, medium: 0, low: 0, info: 0 },
	timeline: [],
	first_seen: null,
	last_seen: null,
	rules: [],
	rules_complete: true,
	no_sid: 0,
	explanation: SURICATA_RULE.explanation,
	learn_more: SURICATA_RULE.learn_more,
	devices: { rows: [], distinct: 0, examined: 0, complete: true, picked_by: 'source_plus_destination' },
	remotes: { rows: [], distinct: 0, examined: 0, complete: true, picked_by: 'source_plus_destination' },
	unplaced: { rows: [], distinct: 0, examined: 0, complete: true, picked_by: 'source_plus_destination' },
	missing_address: 0,
};

export const SURICATA_RULE_ROUTES: FixtureRoute[] = [
	// any name: the daemon receives it percent-encoded, "/" included
	{ path: /^\/api\/alerts\/rule\/.+$/, empty: SURICATA_RULE_EMPTY, populated: SURICATA_RULE },
];
