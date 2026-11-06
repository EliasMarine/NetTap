/**
 * The address and domain pages' figures (NET-160): GET /api/addresses/{ip} and
 * GET /api/domains/{name} (daemon/api/addresses.py, domains.py). Every figure is exact for
 * its window or says it isn't: byte totals carry how many connections were measured, lists
 * carry whether they are complete. Errors throw with the daemon's reason (bad input, busy,
 * too slow), never an empty reply that would read as "none".
 */

/** A byte total and how much of it was measured: `measured` of `connections` carried the field. */
export interface ByteTotal {
	total: number;
	measured: number;
	connections: number;
	partial: boolean;
}

export interface TimelinePoint {
	t: string;
	n: number;
}

export interface AddressPeer {
	ip: string;
	lan: boolean;
	connections: number;
	/** Data to the page's address in this peer's sessions; null when none of them measured it. */
	bytes_to: number | null;
	/** Data from the page's address in this peer's sessions; null when none of them measured it. */
	bytes_from: number | null;
	/** Some sessions carried no byte count, so both figures are lower bounds. */
	bytes_partial: boolean;
	last_seen: string;
}

// OLD CODE START — one row per (port, transport, service) counted a connection Zeek logged with two
// services once per service; the daemon now groups by port and transport
// /** A row keeps connections whose port, transport or service is missing (null), so the rows add up. */
// export interface AddressPort {
// 	port: number | null;
// 	transport: string | null;
// 	service: string | null;
// 	connections: number;
// }
// OLD CODE END
/** One port reached on the address. A missing port or transport is null, so the rows add up. */
export interface AddressPort {
	port: number | null;
	transport: string | null;
	/** The services Zeek saw on it, most common first; [] when none */
	services: string[];
	connections: number;
}

export interface TlsName {
	/** null: the client sent no name (SNI). */
	name: string | null;
	sessions: number;
	statuses: Record<string, number>;
}

export interface ThreatFeedHit {
	feed: string;
	label: string;
	indicator?: string;
	type?: string;
}

export interface ThreatIntel {
	matched: boolean;
	feeds: ThreatFeedHit[];
	indicators: number;
}

export interface AddressSummary {
	ip: string;
	from: string;
	to: string;
	/** The daemon's own answer: on your network. */
	lan: boolean;
	connections: number;
	first_seen: string | null;
	last_seen: string | null;
	bytes_to: ByteTotal;
	bytes_from: ByteTotal;
	peers: AddressPeer[];
	peers_complete: boolean;
	ports: AddressPort[];
	ports_complete: boolean;
	timeline: TimelinePoint[];
	tls_names: TlsName[];
	tls_complete: boolean;
	alerts: number;
	/** null: no threat indicators loaded yet, so the address wasn't checked. */
	threat_intel: ThreatIntel | null;
}

export interface DomainAsker {
	ip: string;
	lan: boolean;
	lookups: number;
	last_seen: string;
}

export interface DomainAnswer {
	value: string;
	/** ip links to its address, name to its domain page, other (TXT, MX text …) is text. */
	kind: 'ip' | 'name' | 'other';
	lan: boolean | null;
	lookups: number;
}

export interface DomainSummary {
	name: string;
	from: string;
	to: string;
	dns: {
		lookups: number;
		askers: DomainAsker[];
		askers_complete: boolean;
		answers: DomainAnswer[];
		answers_complete: boolean;
		/** Distinct IP answers; null when the answers were too many to count. */
		addresses: number | null;
		rcodes: { rcode: string | null; lookups: number }[];
		timeline: TimelinePoint[];
	};
	tls: {
		sessions: number;
		servers: { ip: string; lan: boolean; sessions: number }[];
		servers_complete: boolean;
		clients: { ip: string; lan: boolean; sessions: number }[];
		clients_complete: boolean;
		statuses: Record<string, number>;
	};
	http: { requests: number };
	alerts: {
		/** Alerts whose host fields name this domain; null when no alert in the window carries one. */
		tagged: number | null;
		alerts_in_window: number;
		with_host_field: number;
	};
}

/** The reply's JSON; a failure throws the daemon's own reason, or "<what> failed: HTTP n". */
export async function getJson(url: string, what: string): Promise<unknown> {
	const res = await fetch(url);
	if (!res.ok) {
		const reason = await res
			.json()
			.then((body: unknown) => (body && typeof body === 'object' && 'error' in body ? String(body.error) : ''))
			.catch(() => '');
		throw new Error(reason || `${what} failed: HTTP ${res.status}`);
	}
	return res.json();
}

const windowQuery = (from: string, to: string) => new URLSearchParams({ from, to }).toString();
const isObject = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object';
// OLD CODE START — `partial` unchecked, so a reply without it showed an exact figure
// const isByteTotal = (v: unknown) => isObject(v) && ['total', 'measured', 'connections'].every((k) => typeof v[k] === 'number');
// OLD CODE END
const isNumber = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const isBoolean = (v: unknown): v is boolean => typeof v === 'boolean';
const isByteTotal = (v: unknown) => isObject(v) && ['total', 'measured', 'connections'].every((k) => isNumber(v[k])) && isBoolean(v.partial);
/** null (no indicators loaded) or a checked result; a missing field is malformed, not "not checked" */
const isNullable = (v: unknown, test: (x: unknown) => boolean) => v === null || test(v);
const isString = (v: unknown): v is string => typeof v === 'string';
const isPort = (v: unknown) =>
	isObject(v) &&
	isNullable(v.port, isNumber) &&
	isNullable(v.transport, isString) &&
	Array.isArray(v.services) &&
	v.services.every(isString) &&
	isNumber(v.connections);
const isThreatIntel = (v: unknown) => v === null || (isObject(v) && isBoolean(v.matched) && Array.isArray(v.feeds) && isNumber(v.indicators));

/** Everything the address page shows for `ip` in the window. */
export async function getAddressSummary(ip: string, from: string, to: string): Promise<AddressSummary> {
	const body = await getJson(`/api/addresses/${encodeURIComponent(ip)}?${windowQuery(from, to)}`, 'Address summary');
	// Every part the page reads, so a malformed reply is an error, never a blank that reads as "none"
	// OLD CODE START — flags, alerts and threat intel unchecked, so a reply missing them read as complete
	// const ok =
	// 	isObject(body) &&
	// 	typeof body.connections === 'number' &&
	// 	isByteTotal(body.bytes_to) &&
	// 	isByteTotal(body.bytes_from) &&
	// 	[body.peers, body.ports, body.timeline, body.tls_names].every(Array.isArray);
	// OLD CODE END
	const ok =
		isObject(body) &&
		isNumber(body.connections) &&
		isNumber(body.alerts) &&
		isBoolean(body.lan) &&
		isByteTotal(body.bytes_to) &&
		isByteTotal(body.bytes_from) &&
		[body.peers, body.ports, body.timeline, body.tls_names].every(Array.isArray) &&
		[body.peers_complete, body.ports_complete, body.tls_complete].every(isBoolean) &&
		(body.ports as unknown[]).every(isPort) &&
		isThreatIntel(body.threat_intel);
	if (!ok) throw new Error('Address summary failed: the reply was malformed');
	return body as unknown as AddressSummary;
}

/** Everything the domain page shows for `name` in the window. */
export async function getDomainSummary(name: string, from: string, to: string): Promise<DomainSummary> {
	const body = await getJson(`/api/domains/${encodeURIComponent(name)}?${windowQuery(from, to)}`, 'Domain summary');
	// OLD CODE START — the counts under tls, http and alerts, and the complete flags, were cast unchecked
	// const ok =
	// 	isObject(body) &&
	// 	isObject(body.dns) &&
	// 	typeof body.dns.lookups === 'number' &&
	// 	[body.dns.askers, body.dns.answers, body.dns.rcodes, body.dns.timeline].every(Array.isArray) &&
	// 	isObject(body.tls) &&
	// 	[body.tls.servers, body.tls.clients].every(Array.isArray) &&
	// 	isObject(body.http) &&
	// 	isObject(body.alerts);
	// OLD CODE END
	const { dns, tls, http, alerts } = isObject(body) ? body : ({} as Record<string, unknown>);
	const ok =
		isObject(dns) &&
		isNumber(dns.lookups) &&
		(dns.addresses === null || isNumber(dns.addresses)) &&
		[dns.askers, dns.answers, dns.rcodes, dns.timeline].every(Array.isArray) &&
		[dns.askers_complete, dns.answers_complete].every(isBoolean) &&
		isObject(tls) &&
		isNumber(tls.sessions) &&
		isObject(tls.statuses) &&
		[tls.servers, tls.clients].every(Array.isArray) &&
		[tls.servers_complete, tls.clients_complete].every(isBoolean) &&
		isObject(http) &&
		isNumber(http.requests) &&
		isObject(alerts) &&
		(alerts.tagged === null || isNumber(alerts.tagged)) &&
		isNumber(alerts.alerts_in_window) &&
		isNumber(alerts.with_host_field);
	if (!ok) throw new Error('Domain summary failed: the reply was malformed');
	return body as unknown as DomainSummary;
}
