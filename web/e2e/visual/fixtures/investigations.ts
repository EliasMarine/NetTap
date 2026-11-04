/** Fixtures for /api/investigations (daemon/api/investigations.py), reached through web routes. */
import type { Investigation, InvestigationStats } from '../../../src/lib/api/investigations.ts';
import { DAY, HOUR, iso, type FixtureRoute } from './types.ts';

const INVESTIGATIONS: Investigation[] = [
	{
		id: 'fx-inv-001',
		title: 'Suspicious callbacks from 192.168.1.42',
		description: 'A laptop contacts 203.0.113.45 every five minutes. Checking whether it is infected.',
		status: 'open',
		severity: 'critical',
		created_at: iso(5 * HOUR),
		updated_at: iso(1 * HOUR),
		alert_ids: ['fx-alert-001', 'fx-alert-002'],
		device_ips: ['192.168.1.42'],
		notes: [{ id: 'fx-note-001', content: 'Laptop isolated from the guest network; scan pending.', created_at: iso(1 * HOUR), updated_at: iso(1 * HOUR) }],
		tags: ['malware', 'beaconing'],
	},
	{
		id: 'fx-inv-002',
		title: 'Port sweep from the living-room TV',
		description: 'The TV probed 192.0.2.88 on port 22. Likely a firmware bug.',
		status: 'in_progress',
		severity: 'medium',
		created_at: iso(2 * DAY),
		updated_at: iso(1 * DAY),
		alert_ids: ['fx-alert-003'],
		device_ips: ['192.168.1.57'],
		notes: [],
		tags: ['iot'],
	},
	{
		id: 'fx-inv-003',
		title: 'Cleartext password over HTTP',
		description: 'A local service sent a password without encryption; the service now uses HTTPS.',
		status: 'resolved',
		severity: 'low',
		created_at: iso(6 * DAY),
		updated_at: iso(4 * DAY),
		alert_ids: ['fx-alert-005'],
		device_ips: ['192.168.1.23'],
		notes: [],
		tags: [],
	},
];

const STATS_EMPTY = { total: 0, by_status: { open: 0, in_progress: 0, resolved: 0, closed: 0 }, by_severity: { low: 0, medium: 0, high: 0, critical: 0 } } satisfies InvestigationStats;
const STATS = { total: 3, by_status: { open: 1, in_progress: 1, resolved: 1, closed: 0 }, by_severity: { low: 1, medium: 1, high: 0, critical: 1 } } satisfies InvestigationStats;

export const INVESTIGATION_ROUTES: FixtureRoute[] = [
	{ path: '/api/investigations', method: 'GET', empty: { investigations: [] }, populated: { investigations: INVESTIGATIONS } satisfies { investigations: Investigation[] } },
	{ path: '/api/investigations/stats', empty: STATS_EMPTY, populated: STATS },
];
