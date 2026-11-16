/**
 * The Security posture category pages' traffic detail: GET /api/posture/{slug} (daemon/api/posture.py)
 * for Encryption, DNS security and Patch currency, and Alert response's input (NET-308). A failure
 * throws the daemon's reason; a reply that isn't the expected shape throws too, never reads as zeros.
 */
import { getJson, isBoolean, isNumber, isObject, isString } from './drilldown';
import { getNetworkIsolation, type NetworkIsolation } from './iot';

export interface NamedCount {
	name: string;
	count: number;
}
export interface PortCount {
	port: number;
	count: number;
}
export interface IpCount {
	ip: string;
	count: number;
}
/** A capped device list: `lan` connections came from devices on the network, `other` from devices not in `rows`. */
export interface DeviceList<R> {
	lan: number;
	other: number;
	rows: R[];
}
/** A fixed filter's count, and the Log Explorer query that lists exactly its records. */
export interface RiskyBucket {
	count: number;
	logs_query: string;
}
/** What an address says about where it is; "private_local" is not proof the traffic stayed in this network. */
export type AddressScope = 'private_local' | 'unknown' | 'public';

interface DetailBase {
	from: string;
	to: string;
	excluded_ips: string[];
}

/** NET-308: every figure is the scored set, connections with data both ways */
export interface EncryptionDevice {
	ip: string;
	connections: number;
	// OLD CODE: payload_both: number; (NET-308: always `connections` now)
	private_local: number;
	services: NamedCount[];
	ports: PortCount[];
}
export interface EncryptionDetail extends DetailBase {
	category: 'encryption';
	eligible: number;
	encrypted: number;
	unencrypted: {
		total: number;
		// OLD CODE: payload_both: number; (NET-308: always `total` now)
		private_local: number;
		services: NamedCount[];
		services_other: number;
		risky: { telnet: RiskyBucket; ftp: RiskyBucket; http: RiskyBucket };
	};
	devices: DeviceList<EncryptionDevice>;
}

export interface DnsResolver {
	ip: string;
	count: number;
	org: string | null;
	scope: AddressScope;
	/** A private/local-scope resolver's own lookups out: plain to public addresses, and DoT; null otherwise */
	upstream?: { plain_public: number; dot: number } | null;
}
export interface DnsDevice {
	ip: string;
	count: number;
	resolvers: { ip: string; count: number; org: string | null }[];
}
export interface DnsDetail extends DetailBase {
	category: 'dns-security';
	plain: number;
	over_tls: number;
	plain_scope: { private_local: number; unknown: number; public: number };
	resolvers: { plain: DnsResolver[]; over_tls: DnsResolver[] };
	public_devices: DeviceList<DnsDevice>;
}

export interface PatchDevice {
	ip: string;
	connections: number;
	ports: PortCount[];
	destinations: IpCount[];
}
export interface PatchDetail extends DetailBase {
	category: 'patch-currency';
	// OLD CODE: /** Connections with a legacy label, each counted once (the score counts labels) */
	/** Connections with a legacy label, each counted once, as the score counts them (NET-308) */
	unique_connections: number;
	protocols: { name: string; count: number; devices: DeviceList<PatchDevice> }[];
}

/** One rule's alerts in the window: a rule name, "" for an empty one, null for none (NET-308) */
export interface ResponseGroup {
	rule: string | null;
	count: number;
	/** An investigation open during the window links one of its alerts */
	investigated: boolean;
}
/** Alert response's input: the high-severity rules among the counted alerts, and their follow-up */
export interface AlertResponseDetail {
	category: 'alert-response';
	from: string;
	to: string;
	/** Rules whose counted alerts are mostly high severity (Suricata priority 1) */
	needing: number;
	investigated: number;
	/** Uninvestigated first, then the busiest; at most 25 (`needing` counts them all) */
	groups: ResponseGroup[];
	investigations: {
		open_during: number;
		linked_alerts: number;
		/** Links made before NET-308, with no rule recorded: they cover nothing */
		unresolved_links: number;
		/** Records the daemon couldn't read */
		skipped: number;
	};
}

// OLD CODE START — NET-308: Alert response's reply joined the three traffic details
// export interface PostureDetails {
// 	encryption: EncryptionDetail;
// 	'dns-security': DnsDetail;
// 	'patch-currency': PatchDetail;
// }
// export type TrafficSlug = keyof PostureDetails;
// OLD CODE END
export interface PostureDetails {
	encryption: EncryptionDetail;
	'dns-security': DnsDetail;
	'patch-currency': PatchDetail;
	'alert-response': AlertResponseDetail;
}
export type DetailSlug = keyof PostureDetails;
export type TrafficSlug = Exclude<DetailSlug, 'alert-response'>;

// --- Shape checks ---

type Check = (v: unknown) => boolean;
const count: Check = (v) => isNumber(v) && v >= 0;
const list = (v: unknown, item: Check) => Array.isArray(v) && v.every(item);
const obj = (v: unknown, fields: Record<string, Check>) => isObject(v) && Object.entries(fields).every(([k, check]) => check(v[k]));
const orgOf: Check = (v) => v === null || isString(v);
const named: Check = (v) => obj(v, { name: isString, count });
const port: Check = (v) => obj(v, { port: count, count });
const ipCount: Check = (v) => obj(v, { ip: isString, count });
const devices = (row: Check): Check => (v) => obj(v, { lan: count, other: count, rows: (r) => list(r, row) });
const risky: Check = (v) => obj(v, { count, logs_query: isString });
const SCOPES: readonly unknown[] = ['private_local', 'unknown', 'public'];
const resolver: Check = (v) =>
	obj(v, { ip: isString, count, org: orgOf, scope: (s) => SCOPES.includes(s) }) &&
	(isObject(v) && (v.upstream === undefined || v.upstream === null || obj(v.upstream, { plain_public: count, dot: count })));

// The traffic details report the excluded addresses they left out; alerts never leave them out
const excluded: Check = (e) => list(e, isString);
const group: Check = (v) => obj(v, { rule: (r) => r === null || isString(r), count, investigated: isBoolean });

const CHECKS: Record<DetailSlug, Record<string, Check>> = {
	encryption: {
		excluded_ips: excluded,
		eligible: count,
		encrypted: count,
		unencrypted: (v) =>
			obj(v, {
				total: count,
				// OLD CODE: payload_both: count, (NET-308)
				private_local: count,
				services: (s) => list(s, named),
				services_other: count,
				risky: (r) => obj(r, { telnet: risky, ftp: risky, http: risky }),
			}),
		// OLD CODE: devices: devices((d) => obj(d, { ip: isString, connections: count, payload_both: count, … })), (NET-308)
		devices: devices((d) => obj(d, { ip: isString, connections: count, private_local: count, services: (s) => list(s, named), ports: (p) => list(p, port) })),
	},
	'dns-security': {
		excluded_ips: excluded,
		plain: count,
		over_tls: count,
		plain_scope: (v) => obj(v, { private_local: count, unknown: count, public: count }),
		resolvers: (v) => obj(v, { plain: (r) => list(r, resolver), over_tls: (r) => list(r, resolver) }),
		public_devices: devices((d) => obj(d, { ip: isString, count, resolvers: (r) => list(r, (x) => obj(x, { ip: isString, count, org: orgOf })) })),
	},
	'patch-currency': {
		excluded_ips: excluded,
		unique_connections: count,
		protocols: (v) =>
			list(v, (p) => obj(p, { name: isString, count, devices: devices((d) => obj(d, { ip: isString, connections: count, ports: (x) => list(x, port), destinations: (x) => list(x, ipCount) })) })),
	},
	'alert-response': {
		needing: count,
		investigated: count,
		groups: (v) => list(v, group),
		investigations: (v) => obj(v, { open_during: count, linked_alerts: count, unresolved_links: count, skipped: count }),
	},
};

// OLD CODE START — NET-308: excluded_ips moved to the traffic slugs' checks
// export function isPostureDetail<S extends TrafficSlug>(slug: S, v: unknown): v is PostureDetails[S] {
// 	return obj(v, { category: (c) => c === slug, from: isString, to: isString, excluded_ips: (e) => list(e, isString), ...CHECKS[slug] });
// }
// OLD CODE END
/** True when `v` is a complete reply for `slug`. */
export function isPostureDetail<S extends DetailSlug>(slug: S, v: unknown): v is PostureDetails[S] {
	return obj(v, { category: (c) => c === slug, from: isString, to: isString, ...CHECKS[slug] });
}

/** The detail behind one category's score, over exactly `win`. */
export async function getPostureDetail<S extends DetailSlug>(slug: S, win: { from: string; to: string }): Promise<PostureDetails[S]> {
	const query = new URLSearchParams({ from: win.from, to: win.to }).toString();
	const body = await getJson(`/api/posture/${slug}?${query}`, 'The posture detail');
	if (!isPostureDetail(slug, body)) throw new Error('The posture reply was malformed');
	return body;
}

// --- Smart-device isolation (NET-308: the Network segmentation score) ---

const RISKS: readonly unknown[] = ['critical', 'high', 'medium', 'low'];
const ports: Check = (v) => list(v, (p) => isNumber(p));
const pair: Check = (v) =>
	obj(v, {
		iot_device: (d) => obj(d, { mac: isString, name: isString, ip: isString }),
		internal_target: (t) => obj(t, { ip: isString }),
		risk: (r) => RISKS.includes(r),
		connection_count: count,
		ports,
		reached: isBoolean,
		reached_ports: ports,
		description: isString,
	});
const score: Check = (v) => v === null || (isNumber(v) && v >= 0 && v <= 100);

/** True when `v` is a complete isolation reply; a score that isn't null or 0–100 is malformed. */
export function isIsolation(v: unknown): v is NetworkIsolation {
	return obj(v, {
		segmentation_score: score,
		segmentation_grade: (g) => g === null || isString(g),
		pairs: (p) => list(p, pair),
		recommendation: isString,
	});
}

/** The IoT isolation the score reads, over exactly `win`; a malformed reply throws, never reads as 100. */
export async function getIsolation(win: { from: string; to: string }): Promise<NetworkIsolation> {
	const body: unknown = await getNetworkIsolation(win);
	if (!isIsolation(body)) throw new Error('The isolation reply was malformed');
	return body;
}
