/**
 * View helpers for /certificates (NET-154): the plain title, evidence, explanation and advice for
 * each finding, how sites, devices and statuses read, and the window notices.
 *
 * Every sentence states only what the overview measured: Zeek's verification result, the
 * certificate's stored dates, and the sessions it counted. "Couldn't be verified" never claims
 * the device accepted or refused the certificate, because Zeek can't see that.
 */
import type { CertDetail, CertDevice, CertFinding, CertSite, FindingKind } from '$lib/api/certificates';
import { loadFailed } from '$lib/utils/load-failed';
import { customRange, formatWhen } from '$lib/utils/drilldown';

export type Names = ReadonlyMap<string, string>;

// OLD CODE START — NET-160: a drill-down link carries its own window ("Custom")
// export type RangeValue = '24h' | '7d' | '30d';
// OLD CODE END
export type RangeValue = '24h' | '7d' | '30d' | 'custom';

export interface RangeOption {
	value: RangeValue;
	label: string;
	hours: number;
	words: string;
}

export const RANGES: readonly RangeOption[] = [
	{ value: '24h', label: '24h', hours: 24, words: 'last 24 hours' },
	{ value: '7d', label: '7d', hours: 168, words: 'last 7 days' },
	{ value: '30d', label: '30d', hours: 720, words: 'last 30 days' },
];

/** A window a link brought (?from=&to=), shown as "Custom". */
export interface CustomRange extends RangeOption {
	from: string;
	to: string;
}

// OLD CODE START — slice 2a: moved to lib/utils/drilldown.ts, so Log Explorer and Alerts take
// the same Custom window
// /**
//  * The window from a drill-down link (NET-160): the address and domain pages pass the window
//  * their figures came from, so the certificates match them. Null unless both ends are dates
//  * and `from` is before `to`.
//  */
// export function customRange(from: string | null, to: string | null): CustomRange | null {
// 	if (!from || !to) return null;
// 	const start = new Date(from);
// 	const end = new Date(to);
// 	if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start >= end) return null;
// 	return {
// 		value: 'custom',
// 		label: 'Custom',
// 		hours: (end.getTime() - start.getTime()) / 3_600_000,
// 		words: `window ${formatWhen(start.toISOString())} to ${formatWhen(end.toISOString())}`,
// 		from: start.toISOString(),
// 		to: end.toISOString(),
// 	};
// }
// OLD CODE END
export { customRange };

const fmt = (n: number): string => n.toLocaleString('en-GB');
const plural = (n: number, one: string, many = `${one}s`): string => `${fmt(n)} ${n === 1 ? one : many}`;

// ---------------------------------------------------------------------------
// Names
// ---------------------------------------------------------------------------

/** A device's registry name, else its address. */
export function deviceName(ip: string | null | undefined, names: Names): string {
	if (!ip) return 'an unknown device';
	return names.get(ip) ?? ip;
}

/** "Kitchen iPad", "Kitchen iPad and 2 more", or '' when no device was recorded. */
export function whoUsed(clients: readonly string[], total: number, names: Names): string {
	if (clients.length === 0) return '';
	const first = deviceName(clients[0], names);
	return total > 1 ? `${first} and ${fmt(total - 1)} more` : first;
}

/** The server name a device asked for; without one, the server's address. */
export function siteName(site: string | null | undefined, server: string | null | undefined): string {
	return site || server || 'an unnamed server';
}

const capitalise = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1);

// ---------------------------------------------------------------------------
// Statuses, dates and days
// ---------------------------------------------------------------------------

/** One validation status in words: Zeek's text, except "ok" and a missing status. */
export function statusWords(status: string): string {
	if (status === 'ok') return 'verified';
	if (status === 'unchecked') return 'not checked';
	return status;
}

/** Statuses, busiest first, with their session counts: "verified (40); not checked (2)". */
export function statusList(statuses: Readonly<Record<string, number>>): string {
	return Object.entries(statuses)
		.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
		.map(([status, n]) => `${statusWords(status)} (${fmt(n)})`)
		.join('; ');
}

const failedOnly = (failed: Readonly<Record<string, number>> | undefined): string =>
	Object.keys(failed ?? {})
		.sort()
		.join('; ');

/** "2 Mar 2026"; the raw text when it isn't a date; "—" when missing. */
export function formatDay(iso: string | null | undefined): string {
	if (!iso) return '—';
	const d = new Date(iso);
	return Number.isFinite(d.getTime()) ? d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : iso;
}

// OLD CODE START — slice 2a: moved to lib/utils/drilldown.ts with customRange, which words windows with it
// /** "5 Nov, 21:05"; "—" when missing. */
// export function formatWhen(iso: string | null | undefined): string {
// 	if (!iso) return '—';
// 	const d = new Date(iso);
// 	return Number.isFinite(d.getTime())
// 		? d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
// 		: iso;
// }
// OLD CODE END
export { formatWhen };

/** Whole days left, as the daemon counts them (rounded down), in words. */
export function runsOut(days: number | null | undefined): string {
	if (days === null || days === undefined) return 'Unknown';
	if (days < 0) return 'Already ran out';
	if (days === 0) return 'Within a day';
	return plural(days, 'day');
}

/** "runs out in 12 days", "has already run out": days left as the end of a sentence. */
export function runsOutSentence(days: number | null | undefined): string {
	if (days === null || days === undefined) return 'has no stored expiry date';
	if (days < 0) return 'has already run out';
	if (days === 0) return 'runs out within a day';
	return `runs out in ${plural(days, 'day')}`;
}

// ---------------------------------------------------------------------------
// Findings
// ---------------------------------------------------------------------------

export const FINDING_LABEL: Record<FindingKind, string> = {
	'unverified-alongside-verified': 'Unexpected authority',
	unverified: "Couldn't verify",
	'expired-at-use': 'Expired when used',
	'chain-expired': 'Expired in chain',
	weak: 'Weak',
	'device-expiry': 'Runs out soon',
};

// "an MD5 signature", "an 800-bit…", otherwise "a SHA-1 signature", "a 1024-bit RSA key"
const article = (text: string): string => (/^(MD5|8)/.test(text) ? 'an' : 'a');

function weakWords(weaknesses: readonly string[] | undefined): string {
	return (weaknesses ?? []).map((w) => `${article(w)} ${w}`).join(' and ');
}

/** The finding as one plain sentence, naming the devices whose sessions it counts. */
export function findingTitle(f: CertFinding, names: Names): string {
	const who = whoUsed(f.clients, f.clients_total, names) || 'A device';
	const site = siteName(f.site, f.server);
	switch (f.kind) {
		case 'unverified-alongside-verified':
			return `${who} got a certificate for ${site} from an unexpected authority, and it couldn't be verified`;
		case 'unverified':
			return `${who} got a certificate for ${site} that couldn't be verified`;
		case 'expired-at-use':
			return `${who} got the certificate for ${site} after it had expired`;
		case 'chain-expired':
			return `${who} got a certificate chain for ${site} that failed with an expiry error`;
		case 'weak':
			return `${who} connects to ${site} with a weak certificate`;
		case 'device-expiry':
			return `${capitalise(deviceName(f.server, names))}'s certificate for ${site} ${runsOutSentence(f.days_left)}`;
	}
}

/** The raw evidence under the title, in mono. */
export function findingEvidence(f: CertFinding): string {
	const site = siteName(f.site, f.server);
	switch (f.kind) {
		case 'unverified-alongside-verified':
			return `${site} · ${f.authority ?? 'unknown authority'}, others got ${f.other_authority} · ${failedOnly(f.failed)}`;
		case 'unverified':
		case 'chain-expired':
			return `${site} · ${failedOnly(f.failed)}`;
		case 'expired-at-use':
			return `${site} · expired ${formatDay(f.not_after)} · last seen ${formatWhen(f.last_seen)}`;
		case 'weak':
			return `${site} · ${(f.weaknesses ?? []).join(' · ')}`;
		case 'device-expiry':
			return `${site} · ${f.server ?? '—'}${f.port ? `:${f.port}` : ''} · runs out ${formatDay(f.not_after)}`;
	}
}

/** What the finding means, from the figures it carries. */
export function findingExplanation(f: CertFinding, detail: CertDetail | undefined, names: Names): string {
	const site = siteName(f.site, f.server);
	const sessions = plural(f.sessions, 'session');
	const failed = failedOnly(f.failed);
	switch (f.kind) {
		case 'unverified-alongside-verified':
			return (
				`Other connections to ${site} got a certificate from ${f.other_authority} that verified every time. ` +
				`${sessions} got one from ${f.authority ?? 'an unknown authority'} that didn't (${failed}). ` +
				'A different, untrusted authority for the same site is what interception looks like, ' +
				'though security software and some work networks do it on purpose.'
			);
		case 'unverified':
			return (
				"NetTap checks each certificate against a copy of Mozilla's list of trusted authorities, bundled with Zeek. " +
				`For ${sessions} this one didn't pass (${failed}). That can mean the site uses its own private authority, ` +
				'sent an incomplete chain, or the connection was intercepted.'
			);
		case 'expired-at-use':
			return (
				`This certificate expired on ${formatDay(f.not_after)}, but the server still sent it in ${sessions}, the last on ${formatWhen(f.last_seen)}. ` +
				'NetTap sees the certificate sent, not whether the device accepted it. Browsers refuse expired certificates, ' +
				"so if these connections went ahead, whatever made them isn't checking certificates."
			);
		case 'chain-expired':
			return (
				`For ${sessions} the check failed with "${failed}". ` +
				(detail?.details_available
					? `The site's own certificate was valid until ${formatDay(detail.not_after)}, so another certificate in the chain had run out.`
					: "NetTap has no stored details for the site's own certificate, so it can't tell which certificate in the chain ran out.")
			);
		case 'weak':
			return (
				`The certificate ${site} sent uses ${weakWords(f.weaknesses)}. ` +
				'Public certificate authorities stopped issuing these years ago because they can be forged with enough computing power.'
			);
		case 'device-expiry':
			return (
				`${capitalise(deviceName(f.server, names))} served this certificate for ${site} on port ${f.port ?? '—'}. ` +
				`It ${runsOutSentence(f.days_left)} (${formatDay(f.not_after)}). After that, browsers warn every time you ` +
				"open that device's page, and apps that check certificates may stop connecting."
			);
	}
}

/** What to do. Never invents a cause the figures don't show. */
export function findingAdvice(f: CertFinding): string {
	switch (f.kind) {
		case 'unverified-alongside-verified':
			return (
				'Check whether security software, or a work profile on the device, inspects encrypted traffic. ' +
				"If nothing should, don't sign in to anything from that device until you know why, and look for profiles or apps you don't recognise."
			);
		case 'unverified':
			return (
				"If an app or device talks to its maker's own servers, a private authority can be normal. " +
				'Otherwise use Check it now to see what the site sends today, and update the app or device.'
			);
		case 'expired-at-use':
			return 'Update the app or device that kept connecting. If the site is yours, renew its certificate.';
		case 'chain-expired':
			return "This is usually the site's problem. Use Check it now to see what it sends today. If the site is yours, update the chain it sends.";
		case 'weak':
			return "Update the device's firmware or the app. If the server is yours, reissue the certificate with a SHA-256 signature and a key of at least 2,048 bits.";
		case 'device-expiry':
			return 'Renew the certificate on that device, or turn on automatic renewal if it has it.';
	}
}

// ---------------------------------------------------------------------------
// Sites and devices
// ---------------------------------------------------------------------------

export interface StatusChip {
	label: string;
	tone: '' | 'is-ok' | 'is-warn' | 'is-bad';
}

const failedStatus = (statuses: Readonly<Record<string, number>>): boolean =>
	Object.keys(statuses).some((s) => s !== 'ok' && s !== 'unchecked');

/** A site's status: its most serious finding, else what verification showed. */
export function siteStatus(site: CertSite, worstKind: FindingKind | undefined): StatusChip {
	if (worstKind) return { label: FINDING_LABEL[worstKind], tone: site.worst === 'low' ? 'is-warn' : 'is-bad' };
	if (site.verified) return { label: 'Verified', tone: 'is-ok' };
	if (!failedStatus(site.statuses)) return { label: 'ok' in site.statuses ? 'Partly checked' : 'Not checked', tone: '' };
	// Failures at your own servers are normal (self-signed admin pages) and never a finding
	return { label: site.scope === 'public' ? 'Not verified' : 'Not verified, your network', tone: '' };
}

/** A device row's verification in words. */
export function deviceVerification(device: CertDevice): string {
	if (device.verified) return 'Verified';
	if (device.self_signed) return 'Self-signed';
	const failed = Object.keys(device.statuses).filter((s) => s !== 'ok' && s !== 'unchecked');
	if (failed.length) return capitalise(failed.sort().join('; '));
	return 'ok' in device.statuses ? 'Partly checked' : 'Not checked';
}

/** Does a site match the search: its name, server, authorities or the names of its devices? */
export function siteMatches(site: CertSite, query: string, names: Names): boolean {
	const q = query.trim().toLowerCase();
	if (!q) return true;
	const haystack = [site.name, site.server, ...site.authorities, ...site.clients, ...site.clients.map((ip) => names.get(ip))];
	return haystack.some((value) => value?.toLowerCase().includes(q));
}

// ---------------------------------------------------------------------------
// Window notices
// ---------------------------------------------------------------------------

const clock = (at: Date): string => at.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });

/**
 * What a failed load says while older figures stay on screen. A different window names both,
 * so the figures are never read as the window the pills now show.
 */
export function staleNotice(failed: RangeOption, shown: RangeOption, at: Date, reason: string): string {
	const why = reason ? ` ${reason}` : '';
	if (failed.value === shown.value) return `${loadFailed('certificate data', true)}${why}`;
	return `Couldn't load the ${failed.words}; showing the ${shown.words} loaded at ${clock(at)}.${why}`;
}
