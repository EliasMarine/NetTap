/** Wording for the domain page (NET-160). */
import type { DomainSummary } from '$lib/api/drilldown';
import { fmt } from '$lib/utils/drilldown';

/**
 * How many alerts in the window could be matched to a name at all, always shown beside
 * "Alerts tagged with this name" so its count never reads as every alert tied to the domain.
 */
export function alertCoverage(a: DomainSummary['alerts']): string {
	if (a.alerts_in_window === 0) return 'No alerts in this window, so none carry a host name.';
	if (a.with_host_field === a.alerts_in_window) {
		return a.alerts_in_window === 1
			? 'The only alert in this window carries a host name.'
			: `All ${fmt(a.alerts_in_window)} alerts in this window carry a host name.`;
	}
	return `Only ${fmt(a.with_host_field)} of ${fmt(a.alerts_in_window)} ${a.alerts_in_window === 1 ? 'alert' : 'alerts'} in this window carry a host name.`;
}
