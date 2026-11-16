/**
 * The DNS drill-downs' words: why the Threats page's DNS check listed a name or a device.
 * Text only, over the daemon's own evidence (threat_detection.dns_name_evidence and the
 * failed-lookups reply); the rules themselves stay in the daemon. Context is never a clearance.
 */
import type { DomainFinding, DomainSummary } from '$lib/api/drilldown';
import type { FailedLookups, FailedNameKind } from '$lib/api/threats';
import { domainHref } from '$lib/stores/lan';
import { fmt } from './drilldown';

type DgaEvidence = NonNullable<DomainFinding['dga']>;
type TunnelEvidence = NonNullable<DomainFinding['tunnel']>;

/** A name with this many or more generated names reads as the malware pattern; this many ordinary failures as a DNS filter. */
const MANY_GENERATED = 10;
const MANY_ORDINARY = 20;
// a UUID, or a run of 16+ hex digits: a text pattern for an ID, not a detection rule
const ID_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{16,}/i;

/** The failed-lookups page for one device, opening on `range`. */
export function failedLookupsHref(ip: string, range: string): string {
	return `/threats/failed-lookups/${encodeURIComponent(ip)}?${new URLSearchParams({ range }).toString()}`;
}

/** The domain page in finding mode: the raw name the check read, plus the window words (`range`, or `from`/`to`). */
export function findingHref(raw: string, query: Record<string, string>): string {
	return `${domainHref(raw)}?${new URLSearchParams({ ...query, finding: raw }).toString()}`;
}

const pct = (part: number, whole: number) => `${Math.round((part / whole) * 100)}%`;
const lookupsWord = (n: number) => `${fmt(n)} ${n === 1 ? 'lookup' : 'lookups'}`;
const failedCount = (dns: DomainSummary['dns']) => dns.rcodes.find((r) => r.rcode === 'NXDOMAIN')?.lookups ?? 0;

/** What the window's lookups of the name show: failed, answered, or none. */
function lookupLine(dns: DomainSummary['dns']): string {
	const devices = `${dns.askers_complete ? '' : 'at least '}${fmt(dns.askers.length)} ${dns.askers.length === 1 ? 'device' : 'devices'}`;
	if (dns.lookups === 0) return 'No device looked it up in this window.';
	if (failedCount(dns) === dns.lookups) {
		return `Every one of its ${lookupsWord(dns.lookups)} from ${devices} in this window came back as “no such name” (NXDOMAIN), the pattern malware's generated names leave.`;
	}
	// not every lookup failed with NXDOMAIN, but none answered (SERVFAIL, or REFUSED from a DNS filter)
	if (dns.addresses === 0) return `None of its ${lookupsWord(dns.lookups)} from ${devices} in this window returned an address.`;
	const answered = dns.addresses === null ? 'too many addresses to count' : `${fmt(dns.addresses)} ${dns.addresses === 1 ? 'address' : 'addresses'}`;
	return `It resolves: ${lookupsWord(dns.lookups)} from ${devices} in this window, answered with ${answered}.`;
}

/** Why the DGA check listed the name, from its own measurement. */
export function dgaWhy(dga: DgaEvidence, dns: DomainSummary['dns']): string[] {
	const over = dga.entropy - dga.threshold;
	return [
		`NetTap scores the main part of the name, “${dga.label}” (${fmt(dga.length)} characters), by how evenly its characters are spread. It scored ${dga.entropy.toFixed(3)}; the check lists a name when that score is over ${dga.threshold} and the part is at least ${dga.min_length} characters long.${over < 0.1 ? ' That is only just over the line.' : ''}`,
		/\d/.test(dga.label) ? 'It mixes letters and digits, as many generated names do.' : 'It is letters only.',
		lookupLine(dns),
		'Long names built from real words can score this high. A generated name usually also fails to resolve, and comes with many similar ones.',
	];
}

/** Why the tunnelling check listed the name, from its own measurement. Never concludes either way. */
export function tunnelWhy(tunnel: TunnelEvidence, raw: string, dns: DomainSummary['dns']): string[] {
	const longest = tunnel.labels.reduce((a, b) => (b.length > a.length ? b : a), '');
	const parent = raw.slice(tunnel.subdomain.length + 1).replace(/\.$/, '');
	return [
		`The part before ${parent}, “${tunnel.subdomain}”, is ${fmt(tunnel.length)} characters long; the check lists a name when that part is over ${tunnel.threshold}. It has ${fmt(tunnel.labels.length)} ${tunnel.labels.length === 1 ? 'label' : 'labels'}, the longest “${longest}” (${fmt(longest.length)} characters).`,
		...(ID_PATTERN.test(tunnel.subdomain) ? ['It holds what looks like an ID (a UUID or a long run of hex digits). Apps put device or session IDs in names like this.'] : []),
		`This exact name was looked up ${fmt(dns.lookups)} ${dns.lookups === 1 ? 'time' : 'times'} in this window. Repeating one name is common for app telemetry, but on its own it can't show whether the device also sent many different long names under ${parent}, which is what tunnelling looks like. This page counts only this name.`,
	];
}

/** What to do about a listed name. */
export function findingTodo(finding: DomainFinding, raw: string): string[] {
	const parent = finding.tunnel ? raw.slice(finding.tunnel.subdomain.length + 1).replace(/\.$/, '') : null;
	return [
		'Check the devices listed below: should each of them be making this lookup?',
		'Find the app on those devices that looks this name up.',
		...(parent ? [`To settle whether it is tunnelling, look at that device's other lookups under ${parent} over this window (its DNS records in Log Explorer).`] : []),
		...(finding.dga ? ['If its lookups fail and a device asks for many similar names, check that device for malware.'] : []),
	];
}

/** Each kind of failed name: its short label and what usually causes it. */
export const KIND_WORDS: Record<FailedNameKind, { label: string; meaning: string }> = {
	service_discovery: {
		label: 'Service discovery',
		meaning: 'Service discovery: devices asking the network for printers and shared services, which many home routers answer with “no such name”.',
	},
	reverse: { label: 'Reverse lookup', meaning: 'Reverse lookups: asking which name belongs to an address. Many addresses have none, so these often fail.' },
	wpad: { label: 'Proxy discovery', meaning: 'Proxy discovery (WPAD): the system looking for a web proxy setting. With none set up, the lookup fails.' },
	bare: { label: 'Single-word name', meaning: 'Single-word names, such as a device name. They fail when no local DNS knows the name.' },
	local: { label: 'Local name', meaning: "Names for the home network (.local, .lan, .home and similar), which public DNS doesn't know." },
	generated: { label: 'Looks generated', meaning: "Names that look generated: NetTap's DGA check scores them as random." },
	other: { label: 'Other', meaning: "Ordinary names that don't exist, or that a DNS filter blocks." },
};

/** Coverage and concentration, only over the names actually read. */
function namesLine(f: FailedLookups): string[] {
	if (!f.failed_names_complete) {
		return [
			`More names failed than NetTap reads at once. It read the first ${fmt(f.failed_names_read)} in name order, so the kinds and counts below cover those names only, and a busier name may be missing.`,
		];
	}
	const top = f.failed_names[0];
	const main = [...f.kinds].sort((a, b) => b.lookups - a.lookups)[0];
	const other = f.kinds.find((k) => k.kind === 'other');
	return [
		f.failed_names_read === 1 && top
			? `All ${fmt(f.failed)} failures were for one name, ${top.name}.`
			: `All ${fmt(f.failed_names_read)} names that failed were read.${top && top.lookups * 2 >= f.failed ? ` The busiest, ${top.name}, was ${fmt(top.lookups)} of the ${fmt(f.failed)} failures.` : ''}`,
		...(main && main.lookups * 2 >= f.failed ? [KIND_WORDS[main.kind].meaning] : []),
		...(f.generated_names >= MANY_GENERATED
			? [`${fmt(f.generated_names)} of the names that failed look generated. That is the pattern of malware trying generated names until one works: look closer.`]
			: f.generated_names > 0
				? [`${fmt(f.generated_names)} of the names that failed ${f.generated_names === 1 ? 'looks' : 'look'} generated.`]
				: []),
		...(other && other.names >= MANY_ORDINARY
			? ["A DNS filter (Pi-hole, NextDNS or a router blocklist) answers “no such name” for blocked ads and trackers. If you run one, that may be why so many ordinary names failed."]
			: []),
	];
}

// OLD CODE: const meetsRule = (f) => f.lookups > 50 && f.failed / f.lookups > 0.4; (the daemon's meets_rule, from the detector's own rule)

/** The NXDOMAIN check's rule in words, with the daemon's thresholds. */
export const ruleWords = (rule: FailedLookups['rule']): string =>
	`NetTap lists a device when more than ${Math.round(rule.min_share * 100)}% of more than ${fmt(rule.min_lookups)} lookups fail.`;

/** Why the NXDOMAIN check listed the device, stating only what was measured. */
export function failedWhy(f: FailedLookups, who: string, words: string): string[] {
	return [
		`${who} made ${lookupsWord(f.lookups)} in the ${words}; ${fmt(f.failed)} of them${f.lookups > 0 ? ` (${pct(f.failed, f.lookups)})` : ''} came back as “no such name” (NXDOMAIN). ${ruleWords(f.rule)}`,
		// the page's window can differ from the Threats scan that listed it
		...(f.meets_rule ? [] : ["In this window that isn't met, so the check wouldn't list this device for it."]),
		...namesLine(f),
	];
}

/** What to do about a listed device. */
export function failedTodo(f: FailedLookups, who: string): string[] {
	return [
		`Find the app or setting on ${who} that asks for the busiest names below.`,
		...(f.generated_names > 0 ? ['Some names look generated: check the device for malware.'] : []),
	];
}
