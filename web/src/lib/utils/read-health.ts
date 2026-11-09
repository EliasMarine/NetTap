import { getSystemHealth, type SystemHealth } from '$api/system';

/** NET-228: the system health a "nothing found" line reads (nothingFound in $api/system). */
export interface HealthCheck {
	/** null until it loads, or when it failed */
	health: SystemHealth | null;
	failed: boolean;
}

export const HEALTH_CHECKING: HealthCheck = { health: null, failed: false };

/**
 * One health check per page load. It never rejects: a failed check makes the "nothing found"
 * lines say "Couldn't check", and leaves the page's own load status to its own requests.
 */
export function readHealth(): Promise<HealthCheck> {
	return getSystemHealth().then(
		(health) => ({ health, failed: false }),
		() => ({ health: null, failed: true }),
	);
}
