/**
 * NET-262: the resolver compare's plain-English verdict, and the resolver list this browser keeps.
 * Agreement is judged only over usable replies (a status came back); answers compare as sets of
 * the daemon's canonical keys, so TTL and order never count.
 */
import type { DnsCompareReply } from '$api/tools';

export interface ResolverRow {
	ip: string;
	label: string;
}

export interface Verdict {
	/** No usable replies disagree: the notice reads as good news */
	agree: boolean;
	lines: string[];
}

export const MAX_RESOLVERS = 6;
const STORAGE_KEY = 'nettap-dns-compare-resolvers';
const VPN_NOTE =
	'NetTap asks from its own network interface, so a resolver that only answers inside a VPN tunnel cannot be reached.';

const emptyRows = (): ResolverRow[] => [
	{ ip: '', label: '' },
	{ ip: '', label: '' },
];

/** The last resolver list compared in this browser, else two empty rows. */
export function savedResolvers(): ResolverRow[] {
	try {
		const saved: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null');
		if (!Array.isArray(saved)) return emptyRows();
		const rows = saved
			.filter((r) => typeof r?.ip === 'string' && typeof r?.label === 'string')
			.slice(0, MAX_RESOLVERS)
			.map((r) => ({ ip: r.ip, label: r.label }));
		return rows.length ? rows : emptyRows();
	} catch {
		return emptyRows(); // blocked or unreadable storage: start fresh
	}
}

export function saveResolvers(rows: ResolverRow[]): void {
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(rows));
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
	return [...new Set(r.answers.map((a) => (a.scope ? `${a.value} (${a.scope})` : a.value)))].join(', ');
}

const hasScope = (r: DnsCompareReply, scope: 'private' | 'public') => r.answers.some((a) => a.scope === scope);

function headline(results: DnsCompareReply[], usable: DnsCompareReply[], nameOf: (ip: string) => string): Verdict {
	if (usable.length === 0) return { agree: false, lines: ['No resolver replied, so nothing can be compared.'] };
	if (usable.length === 1) {
		const name = nameOf(usable[0].resolver);
		return results.length === 1
			? { agree: true, lines: [`${name} replied.`] }
			: { agree: false, lines: [`Only ${name} replied.`] };
	}
	if (new Set(usable.map(signature)).size === 1) {
		const n = usable.length;
		return { agree: true, lines: [n === 2 ? 'Both resolvers that replied agree.' : `All ${n} resolvers that replied agree.`] };
	}
	const parts = usable.map((r) => `${nameOf(r.resolver)} returns ${describe(r)}`);
	const privates = usable.filter((r) => hasScope(r, 'private'));
	const split = privates.length > 0 && usable.some((r) => !privates.includes(r) && (r.status === 'NXDOMAIN' || hasScope(r, 'public')));
	return { agree: false, lines: [`Resolvers disagree: ${parts.join('; ')}.`, ...(split ? ['This looks like split DNS.'] : [])] };
}

/** The verdict line, then one note per resolver that did not reply. */
export function compareVerdict(results: DnsCompareReply[], nameOf: (resolver: string) => string): Verdict {
	const usable = results.filter((r) => r.status !== null);
	const verdict = headline(results, usable, nameOf);
	const silent = results.filter((r) => r.status === null).map((r) => `${nameOf(r.resolver)} did not reply. ${VPN_NOTE}`);
	return { ...verdict, lines: [...verdict.lines, ...silent] };
}
