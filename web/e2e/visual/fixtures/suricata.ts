/** Fixtures for /api/suricata/rules/* (daemon/api/suricata_rules.py), reached through explicit web routes and the catch-all. */
import type {
	CommercialConfig,
	LiveRuleStatus,
	RuleSourcesResponse,
	RuleStats,
	UpdateSchedule,
} from '../../../src/lib/api/suricata-rules.ts';
import { DAY, HOUR, iso, type FixtureRoute } from './types.ts';

// getCustomRules() reads only `content`; the daemon sends nothing else, and no exported type names it
interface CustomRulesContent {
	content: string;
}

const CATEGORY_PREFIXES = {
	'ET MALWARE': 'Malware',
	'ET TROJAN': 'Trojans',
	'ET SCAN': 'Scanning',
	'ET EXPLOIT': 'Exploits',
	'ET POLICY': 'Policy',
	'ET INFO': 'Informational',
	'ET DNS': 'DNS',
};

const SOURCES_EMPTY = { sources: [], count: 0, last_update: null } satisfies RuleSourcesResponse;
const SOURCES = {
	sources: [
		{ id: 'et/open', enabled: true, description: 'Example Emerging Threats open ruleset' },
		{ id: 'oisf/trafficid', enabled: true, description: 'Example traffic identification rules' },
		{ id: 'abuse.ch/sslbl-blacklist', enabled: false, description: 'Example SSL certificate blacklist' },
	],
	count: 3,
	last_update: iso(6 * HOUR),
} satisfies RuleSourcesResponse;

const STATS_EMPTY = { total_rules: 0, enabled_sources: 0, total_sources: 0, categories: {}, category_prefixes: CATEGORY_PREFIXES } satisfies RuleStats;
const STATS = {
	total_rules: 41250,
	enabled_sources: 2,
	total_sources: 3,
	categories: { Malware: 8120, Trojans: 6410, Scanning: 1180, Exploits: 3920, Policy: 940, Informational: 2210, DNS: 380 },
	category_prefixes: CATEGORY_PREFIXES,
} satisfies RuleStats;

const SCHEDULE = { interval: 'daily', enabled: true } satisfies UpdateSchedule;

// An empty shape that still loads: getLiveRuleStatus() throws unless `available` is true
const LIVE_EMPTY = { available: true, enabled_rules: 0, disabled_rules: 0, last_updated: null, sources: [], schedule: null, error: null } satisfies LiveRuleStatus;
const LIVE = {
	available: true,
	enabled_rules: 41250,
	disabled_rules: 312,
	last_updated: iso(6 * HOUR),
	sources: ['et/open', 'oisf/trafficid'],
	schedule: '0 3 * * *',
	error: null,
} satisfies LiveRuleStatus;

const CUSTOM_EMPTY = { content: '' } satisfies CustomRulesContent;
const CUSTOM = {
	content: 'alert tcp $HOME_NET any -> any 4444 (msg:"EXAMPLE Outbound connection to port 4444"; sid:9000001; rev:1;)\n',
} satisfies CustomRulesContent;

const COMMERCIAL_EMPTY = { configured: false } satisfies CommercialConfig;
const COMMERCIAL = { configured: true, source_type: 'etpro', license_key_masked: 'ABCD****WXYZ', configured_at: iso(30 * DAY) } satisfies CommercialConfig;

export const SURICATA_ROUTES: FixtureRoute[] = [
	{ path: '/api/suricata/rules/sources', empty: SOURCES_EMPTY, populated: SOURCES },
	{ path: '/api/suricata/rules/stats', empty: STATS_EMPTY, populated: STATS },
	{ path: '/api/suricata/rules/schedule', method: 'GET', empty: SCHEDULE },
	{ path: '/api/suricata/rules/live', empty: LIVE_EMPTY, populated: LIVE },
	{ path: '/api/suricata/rules/custom', method: 'GET', empty: CUSTOM_EMPTY, populated: CUSTOM },
	{ path: '/api/suricata/rules/commercial', method: 'GET', empty: COMMERCIAL_EMPTY, populated: COMMERCIAL },
];
