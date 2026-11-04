import type { SystemHealth } from '../../../src/lib/api/system.ts';
import type {
	ComponentVersion,
	UpdateResult,
	UpdateStatus,
	getAvailableUpdates,
} from '../../../src/lib/api/updates.ts';
import { DAY, MIN, iso, type FixtureRoute } from './types.ts';
import {
	SMART_HEALTH_EMPTY,
	SMART_HEALTH_POPULATED,
	STORAGE_STATUS_EMPTY,
	STORAGE_STATUS_POPULATED,
} from './storage.ts';

/** GET /api/health: the daemon's liveness check. The top bar reads `status === 'ok'`. */
interface DaemonLiveness {
	status: 'ok';
	uptime: number;
}

/** The daemon sends `versions` as a list (the client types it as a record, but only Object.values and find read it). */
interface VersionsResponse {
	versions: ComponentVersion[];
	last_scan: string;
	count: number;
}

/** GET /api/system/updates/history, which the client unwraps to `history`. */
interface UpdateHistoryResponse {
	history: UpdateResult[];
	count: number;
}

type AvailableUpdatesResponse = Awaited<ReturnType<typeof getAvailableUpdates>>;

const SECONDS_PER_DAY = 86_400;

function health(uptimeSeconds: number, populated: boolean) {
	return {
		uptime: uptimeSeconds,
		timestamp: iso(0),
		storage: populated ? STORAGE_STATUS_POPULATED : STORAGE_STATUS_EMPTY,
		smart: populated ? SMART_HEALTH_POPULATED : SMART_HEALTH_EMPTY,
		opensearch_reachable: true,
		healthy: true,
	} satisfies SystemHealth;
}

function version(
	name: string,
	category: ComponentVersion['category'],
	currentVersion: string,
	installType: string,
	details: Record<string, unknown> = {},
): ComponentVersion {
	return {
		name,
		category,
		current_version: currentVersion,
		install_type: installType,
		last_checked: iso(5 * MIN),
		status: 'ok',
		details,
	};
}

const VERSIONS_POPULATED = {
	versions: [
		version('nettap-daemon', 'core', '0.4.0', 'pip', { source: 'module_constant' }),
		version('nettap-web', 'core', '0.4.0', 'npm'),
		version('nettap-config', 'core', '20261101', 'builtin'),
		version('malcolm', 'docker', '26.10.0', 'docker', {
			containers: ['nettap-opensearch', 'nettap-logstash', 'nettap-zeek-live', 'nettap-suricata-live'],
		}),
		version('zeek', 'system', '6.2.1', 'docker'),
		version('suricata', 'system', '7.0.7', 'docker'),
		version('tshark', 'system', '4.2.5', 'docker'),
		version('docker', 'system', '27.3.1', 'apt'),
		version('docker-compose', 'system', '2.29.7', 'apt'),
		version('suricata-rules', 'database', '2026-11-02', 'builtin'),
		version('geoip-db', 'database', '2026-10-28', 'builtin'),
		version('opensearch', 'database', '2.17.1', 'docker', {
			cluster_name: 'nettap-opensearch',
			distribution: 'opensearch',
		}),
		version('os', 'os', '24.04', 'builtin', { pretty_name: 'Ubuntu 24.04 LTS' }),
		version('kernel', 'os', '6.8.0-48-generic', 'builtin'),
	],
	last_scan: iso(5 * MIN),
	count: 14,
} satisfies VersionsResponse;

const VERSIONS_EMPTY = { versions: [], last_scan: '', count: 0 } satisfies VersionsResponse;

const AVAILABLE_POPULATED = {
	updates: [
		{
			component: 'nettap-daemon',
			current_version: '0.4.0',
			latest_version: '0.4.1',
			update_type: 'patch',
			release_url: 'https://example.com/nettap/releases/v0.4.1',
			release_date: iso(2 * DAY),
			changelog: 'Fixes the capture health check on mirror ports.',
			size_mb: 48.2,
			requires_restart: true,
			applies_with: null,
		},
		{
			component: 'zeek',
			current_version: '6.2.1',
			latest_version: '6.2.2',
			update_type: 'patch',
			release_url: 'https://example.com/zeek/releases/v6.2.2',
			release_date: iso(6 * DAY),
			changelog: 'Security and stability fixes.',
			size_mb: null,
			requires_restart: true,
			applies_with: 'It arrives with the next Malcolm release.',
		},
	],
	last_check: iso(40 * MIN),
	failed_checks: [],
	checked: ['nettap-daemon', 'zeek', 'suricata', 'suricata-rules', 'geoip-db', 'opensearch'],
} satisfies AvailableUpdatesResponse;

const AVAILABLE_EMPTY = {
	updates: [],
	last_check: '',
	failed_checks: [],
	checked: [],
} satisfies AvailableUpdatesResponse;

const HISTORY_POPULATED = {
	history: [
		{
			component: 'suricata-rules',
			success: true,
			old_version: '2026-10-30',
			new_version: '2026-11-02',
			started_at: iso(1 * DAY + 2 * MIN),
			completed_at: iso(1 * DAY),
			error: null,
			rollback_available: true,
		},
		{
			component: 'geoip-db',
			success: false,
			old_version: '2026-10-21',
			new_version: '2026-10-21',
			started_at: iso(9 * DAY + 3 * MIN),
			completed_at: iso(9 * DAY),
			error: 'The download server did not answer.',
			rollback_available: false,
		},
	],
	count: 2,
} satisfies UpdateHistoryResponse;

const HISTORY_EMPTY = { history: [], count: 0 } satisfies UpdateHistoryResponse;

const UPDATE_STATUS_IDLE = {
	state: 'idle',
	components: [],
	current_component: null,
	current_step: null,
	progress_percent: 0,
	started_at: null,
	completed_at: null,
	results: [],
} satisfies UpdateStatus;

export const SYSTEM_ROUTES: FixtureRoute[] = [
	{
		path: '/api/health',
		empty: { status: 'ok', uptime: 95.2 } satisfies DaemonLiveness,
		populated: { status: 'ok', uptime: 3 * SECONDS_PER_DAY + 4 * 3600 + 0.4 } satisfies DaemonLiveness,
	},
	{
		path: '/api/system/health',
		empty: health(2 * 3600, false),
		populated: health(12 * SECONDS_PER_DAY + 3 * 3600, true),
	},
	{ path: '/api/system/versions', empty: VERSIONS_EMPTY, populated: VERSIONS_POPULATED },
	{ path: '/api/system/updates/available', empty: AVAILABLE_EMPTY, populated: AVAILABLE_POPULATED },
	{ path: '/api/system/updates/history', empty: HISTORY_EMPTY, populated: HISTORY_POPULATED },
	// Idle in every mode, so the Updates page never opens on a running update.
	{ path: '/api/system/updates/status', empty: UPDATE_STATUS_IDLE },
];
