/**
 * The Security posture category pages' traffic detail: GET /api/posture/{slug} (daemon/api/posture.py)
 * for Encryption, DNS security and Patch currency. A failure throws the daemon's reason; a reply that
 * isn't the expected shape throws too, never reads as zeros.
 */
import { getJson, isNumber, isObject, isString } from './drilldown';

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

export interface EncryptionDevice {
	ip: string;
	connections: number;
	payload_both: number;
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
		payload_both: number;
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
	/** Connections with a legacy label, each counted once (the score counts labels) */
	unique_connections: number;
	protocols: { name: string; count: number; devices: DeviceList<PatchDevice> }[];
}

export interface PostureDetails {
	encryption: EncryptionDetail;
	'dns-security': DnsDetail;
	'patch-currency': PatchDetail;
}
export type TrafficSlug = keyof PostureDetails;
export const TRAFFIC_SLUGS: readonly TrafficSlug[] = ['encryption', 'dns-security', 'patch-currency'];

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

const CHECKS: Record<TrafficSlug, Record<string, Check>> = {
	encryption: {
		eligible: count,
		encrypted: count,
		unencrypted: (v) =>
			obj(v, {
				total: count,
				payload_both: count,
				private_local: count,
				services: (s) => list(s, named),
				services_other: count,
				risky: (r) => obj(r, { telnet: risky, ftp: risky, http: risky }),
			}),
		devices: devices((d) => obj(d, { ip: isString, connections: count, payload_both: count, private_local: count, services: (s) => list(s, named), ports: (p) => list(p, port) })),
	},
	'dns-security': {
		plain: count,
		over_tls: count,
		plain_scope: (v) => obj(v, { private_local: count, unknown: count, public: count }),
		resolvers: (v) => obj(v, { plain: (r) => list(r, resolver), over_tls: (r) => list(r, resolver) }),
		public_devices: devices((d) => obj(d, { ip: isString, count, resolvers: (r) => list(r, (x) => obj(x, { ip: isString, count, org: orgOf })) })),
	},
	'patch-currency': {
		unique_connections: count,
		protocols: (v) =>
			list(v, (p) => obj(p, { name: isString, count, devices: devices((d) => obj(d, { ip: isString, connections: count, ports: (x) => list(x, port), destinations: (x) => list(x, ipCount) })) })),
	},
};

/** True when `v` is a complete reply for `slug`. */
export function isPostureDetail<S extends TrafficSlug>(slug: S, v: unknown): v is PostureDetails[S] {
	return obj(v, { category: (c) => c === slug, from: isString, to: isString, excluded_ips: (e) => list(e, isString), ...CHECKS[slug] });
}

/** The traffic detail behind one category's score, over exactly `win`. */
export async function getPostureDetail<S extends TrafficSlug>(slug: S, win: { from: string; to: string }): Promise<PostureDetails[S]> {
	const query = new URLSearchParams({ from: win.from, to: win.to }).toString();
	const body = await getJson(`/api/posture/${slug}?${query}`, 'The posture detail');
	if (!isPostureDetail(slug, body)) throw new Error('The posture reply was malformed');
	return body;
}
