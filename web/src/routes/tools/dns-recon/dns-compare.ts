/**
 * NET-262: the resolver compare's plain-English verdict, and the resolver list this browser keeps.
 * Agreement is judged only over usable replies (a status came back); answers compare as sets of
 * the daemon's canonical keys, so TTL and order never count.
 */
import type { DnsCompareReply, DnsScope } from '$api/tools';

export interface ResolverRow {
	ip: string;
	label: string;
}

/** ok: the usable replies agree on a clear answer; neutral: they agree on a failure (SERVFAIL…) */
export type VerdictTone = 'ok' | 'warn' | 'neutral';

export interface Verdict {
	tone: VerdictTone;
	lines: string[];
}

export const MAX_RESOLVERS = 6;
/** The daemon's MAX_COMPARE_ANSWERS: a reply with more says `truncated` */
export const MAX_ANSWERS = 100;
/** How an answer's scope reads in the table */
export const SCOPE_LABELS: Record<DnsScope, string> = {
	private: 'private',
	public: 'public',
	loopback: 'loopback',
	unspecified: 'no address (often a blocked name)',
};
const MAX_LISTED = 3; // values per resolver in the verdict line
const CLEAR_STATUSES = new Set(['NOERROR', 'NXDOMAIN']);
const STORAGE_KEY = 'nettap-dns-compare-resolvers';
const VPN_NOTE =
	'NetTap asks from its own network interface, so a resolver that only answers inside a VPN tunnel cannot be reached.';

export const emptyRows = (): ResolverRow[] => [
	{ ip: '', label: '' },
	{ ip: '', label: '' },
];

const isRow = (r: unknown): r is ResolverRow =>
	typeof r === 'object' && r !== null && typeof (r as ResolverRow).ip === 'string' && typeof (r as ResolverRow).label === 'string';

/** The last resolver list compared in this browser, else two empty rows. */
export function savedResolvers(): ResolverRow[] {
	try {
		const saved: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null');
		if (!Array.isArray(saved)) return emptyRows();
		const rows = (saved as unknown[])
			.filter(isRow)
			.slice(0, MAX_RESOLVERS)
			.map(({ ip, label }) => ({ ip, label }));
		return rows.length ? rows : emptyRows();
	} catch {
		return emptyRows(); // blocked or unreadable storage: start fresh
	}
}

export function saveResolvers(rows: ResolverRow[]): void {
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(rows.map((r) => ({ ip: r.ip.trim(), label: r.label }))));
	} catch {
		// blocked storage: the list lasts for this visit only
	}
}

/**
 * How each reply is named: its label, else its address.
 * shortcut: a label is matched by the address as typed (trimmed, lower case); an IPv6 address the
 * daemon rewrites (dropped zeros) shows without its label. Return the row index from the daemon if
 * that matters.
 */
export function labeller(rows: ResolverRow[]): (resolver: string) => string {
	const labels = new Map(rows.map((r) => [r.ip.trim().toLowerCase(), r.label.trim()]));
	return (resolver) => labels.get(resolver) || resolver;
}

const signature = (r: DnsCompareReply) => `${r.status}\n${[...new Set(r.answers.map((a) => a.key))].sort().join('\n')}`;

function describe(r: DnsCompareReply): string {
	if (r.status !== 'NOERROR') return String(r.status);
	if (r.answers.length === 0) return 'no records';
	// 0.0.0.0 gets its own note below, so only the other scopes are named here
	const shown = (a: DnsCompareReply['answers'][number]) => (a.scope && a.scope !== 'unspecified' ? `${a.value} (${a.scope})` : a.value);
	const values = [...new Set(r.answers.map(shown))];
	const listed = values.slice(0, MAX_LISTED).join(', ');
	return values.length > MAX_LISTED ? `${listed} and ${values.length - MAX_LISTED} more` : listed;
}

const hasScope = (r: DnsCompareReply, scope: DnsScope) => r.answers.some((a) => a.scope === scope);
const clearTone = (r: DnsCompareReply): VerdictTone => (CLEAR_STATUSES.has(String(r.status)) ? 'ok' : 'neutral');

function headline(results: DnsCompareReply[], usable: DnsCompareReply[], nameOf: (ip: string) => string): Verdict {
	if (usable.length === 0) return { tone: 'warn', lines: ['No resolver replied, so nothing can be compared.'] };
	if (usable.length === 1) {
		const name = nameOf(usable[0].resolver);
		return results.length === 1
			? { tone: clearTone(usable[0]), lines: [`${name} replied.`] }
			: { tone: 'warn', lines: [`Only ${name} replied.`] };
	}
	if (new Set(usable.map(signature)).size === 1) {
		const n = usable.length;
		return { tone: clearTone(usable[0]), lines: [n === 2 ? 'Both resolvers that replied agree.' : `All ${n} resolvers that replied agree.`] };
	}
	const parts = usable.map((r) => `${nameOf(r.resolver)} returns ${describe(r)}`);
	// only a real private address counts: 0.0.0.0 and loopback have their own scopes
	const privates = usable.filter((r) => hasScope(r, 'private'));
	const split = privates.length > 0 && usable.some((r) => !privates.includes(r) && (r.status === 'NXDOMAIN' || hasScope(r, 'public')));
	return { tone: 'warn', lines: [`Resolvers disagree: ${parts.join('; ')}.`, ...(split ? ['This looks like split DNS.'] : [])] };
}

/** The verdict line, then notes: blocked names, cut answers, and each resolver that did not reply. */
export function compareVerdict(results: DnsCompareReply[], nameOf: (resolver: string) => string): Verdict {
	const usable = results.filter((r) => r.status !== null);
	const verdict = headline(results, usable, nameOf);
	const notes = usable.flatMap((r) => {
		const blocked = r.answers.find((a) => a.scope === 'unspecified');
		return [
			...(blocked ? [`${nameOf(r.resolver)} returns ${blocked.value}, which usually means it blocks this name.`] : []),
			...(r.truncated ? [`${nameOf(r.resolver)} returned more than ${MAX_ANSWERS} records, so only ${MAX_ANSWERS} of them were compared.`] : []),
		];
	});
	const silent = results.filter((r) => r.status === null).map((r) => `${nameOf(r.resolver)} did not reply. ${VPN_NOTE}`);
	return { ...verdict, lines: [...verdict.lines, ...notes, ...silent] };
}
