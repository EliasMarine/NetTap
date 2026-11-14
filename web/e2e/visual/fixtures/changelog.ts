/** Fixtures for /api/changelog (daemon/api/changelog.py), reached through the web catch-all. */
import type { ChangelogResponse, EventTypesResponse } from '../../../src/lib/api/changelog.ts';
import { DAY, HOUR, iso, MIN, type FixtureRoute } from './types.ts';

const EVENT_TYPES = ['alert_triggered', 'capture_started', 'config_changed', 'device_joined', 'device_left', 'rule_updated', 'storage_pruned'];

const CHANGELOG_EMPTY = { events: [], count: 0 } satisfies ChangelogResponse;
const CHANGELOG = {
	events: [
		{ _id: 'fx-event-001', '@timestamp': iso(6 * MIN), event_type: 'alert_triggered', title: 'Critical alert on 192.168.1.42', description: 'ET MALWARE Example Agent.Gen CnC Checkin fired 142 times in the last 22 hours.', metadata: { source_ip: '192.168.1.42', severity: 1 } },
		{ _id: 'fx-event-002', '@timestamp': iso(2 * HOUR), event_type: 'device_joined', title: 'New device 192.168.1.80', description: 'A device with MAC 02:00:5e:10:00:80 appeared on the network.', metadata: { ip: '192.168.1.80', mac: '02:00:5e:10:00:80' } },
		// NET-272: camera-01 joined 6 hours ago (net-world.ts), so the populated page shows a device the list has figures for
		{ _id: 'fx-event-006', '@timestamp': iso(6 * HOUR), event_type: 'device_joined', title: 'New device 02:00:5e:10:00:50', description: 'First seen at 192.168.1.50 (source: dhcp)', metadata: { mac: '02:00:5e:10:00:50', ip: '192.168.1.50', source: 'dhcp' } },
		{ _id: 'fx-event-003', '@timestamp': iso(6 * HOUR), event_type: 'rule_updated', title: 'Suricata rules updated', description: 'The daily update loaded 41,250 rules.', metadata: { rules: 41250 } },
		{ _id: 'fx-event-004', '@timestamp': iso(1 * DAY), event_type: 'config_changed', title: 'Notification channel added', description: 'The Home alerts channel was added.', metadata: {} },
		{ _id: 'fx-event-005', '@timestamp': iso(3 * DAY), event_type: 'storage_pruned', title: 'Old indices pruned', description: 'Disk use passed 80 percent, so the oldest indices were removed.', metadata: { freed_gb: 24 } },
	],
	// OLD CODE: count: 5, (NET-272: camera-01 joined)
	count: 6,
} satisfies ChangelogResponse;

const TYPES_EMPTY = { event_types: [] } satisfies EventTypesResponse;
const TYPES = { event_types: EVENT_TYPES } satisfies EventTypesResponse;

export const CHANGELOG_ROUTES: FixtureRoute[] = [
	{ path: '/api/changelog', empty: CHANGELOG_EMPTY, populated: CHANGELOG },
	{ path: '/api/changelog/types', empty: TYPES_EMPTY, populated: TYPES },
];
