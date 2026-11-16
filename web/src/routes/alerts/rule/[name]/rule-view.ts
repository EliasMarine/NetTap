/**
 * Wording for the rule page: the severity most of its alerts carry, how much of an address
 * group is on screen (a bounded selection, never a "top" list), and each address's role.
 */
import type { RuleAddresses, RuleAddressRow, SuricataRuleFigures } from '$lib/api/drilldown';
import { fmt } from '$lib/utils/drilldown';

export type Level = 'high' | 'medium' | 'low' | 'info';
const LEVELS: readonly Level[] = ['high', 'medium', 'low', 'info'];

/** The severity most of these alerts carry (the higher on a tie), or null when there are none. */
export function dominantLevel(severity: SuricataRuleFigures['severity']): Level | null {
	let best: Level | null = null;
	for (const level of LEVELS) {
		if (severity[level] > 0 && (best === null || severity[level] > severity[best])) best = level;
	}
	return best;
}

/** How much of a group the table shows, and whether discovery stopped short (a warning). */
export function addressScope(group: RuleAddresses): { text: string; partial: boolean } {
	if (!group.complete || group.distinct === null) {
		return {
			text: 'Showing a selection of the addresses read; discovery stopped at its limit. Rows were picked by source and destination appearances.',
			partial: true,
		};
	}
	if (group.rows.length < group.distinct) {
		return { text: `${fmt(group.rows.length)} of ${fmt(group.distinct)} addresses, picked by how often each is a source or destination`, partial: false };
	}
	return { text: `${fmt(group.distinct)} ${group.distinct === 1 ? 'address' : 'addresses'}`, partial: false };
}

/** A group's size for a KPI: exact, or "at least" what discovery read when it stopped short. */
export function groupCount(group: RuleAddresses): string {
	return group.distinct === null ? `${fmt(group.examined)}+` : fmt(group.distinct);
}

/** Which end of these alerts an address was: the source, the destination, or both. */
export function roleOf(row: RuleAddressRow): 'Sent it' | 'Received it' | 'Both' {
	if (row.as_source > 0 && row.as_target > 0) return 'Both';
	return row.as_source > 0 ? 'Sent it' : 'Received it';
}

/** ET's own ratings for a SID, in words. */
export function ratingWords(ratings: readonly string[]): string {
	return ratings.length ? ratings.join(', ') : 'Not recorded';
}
