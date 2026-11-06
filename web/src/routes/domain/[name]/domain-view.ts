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

/**
 * "Alerts tagged with this name" as the card shows it (NET-178). A host field that can't be
 * matched to a whole name makes the count a lower bound ("At least 3"), or no count at all when
 * no field can be matched. No alert carrying a host name stays "Not recorded".
 */
export function taggedFigure(a: DomainSummary['alerts']): string {
	if (a.tagged_partial) return a.tagged === null ? "Can't be counted on this NetTap" : `At least ${fmt(a.tagged)}`;
	return a.tagged === null ? 'Not recorded' : fmt(a.tagged);
}

const HOST_FIELD_WORDS: Record<string, string> = {
	'related.hosts': 'related hosts',
	'dns.question.name': 'DNS questions',
	'tls.client.server_name': 'TLS names',
	'url.domain': 'URL domains',
};

/** Which host fields the tagged count can't search, in words; null when it searched them all. */
export function unmatchedNote(a: DomainSummary['alerts']): string | null {
	const words = a.tagged_partial ? (a.unmatched_fields ?? []).map((f) => HOST_FIELD_WORDS[f] ?? f) : [];
	if (words.length === 0) return null;
	const list = words.length === 1 ? words[0] : `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}`;
	// OLD CODE: one ending for both cases ("…only there aren't counted"), beside "Can't be counted on this NetTap" when nothing matched
	const ending = a.tagged === null ? 'the alerts that name this domain can\'t be counted.' : 'alerts that name this domain only there aren\'t counted.';
	return `${list.charAt(0).toUpperCase()}${list.slice(1)} are stored on this NetTap in a way that can't be matched exactly, so ${ending}`;
}
