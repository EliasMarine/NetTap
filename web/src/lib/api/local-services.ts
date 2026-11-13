/**
 * The local service browser (NET-264): GET /api/local-services (daemon/api/local_services.py).
 * One row per observed announcement: a service instance seen from one sender (IP, MAC, VLAN as
 * the frames showed it). The sender is not claimed to own the service: a router that reflects
 * mDNS between VLANs gets rows of its own.
 */
import { getJson, isObject, isString } from './drilldown';

export type VlanState = 'tagged' | 'untagged' | 'unknown';

export interface ServiceSender {
	ip: string;
	mac: string | null;
	/** The owner's or the registry's name for the MAC; never from the IP alone */
	name: string | null;
	vlan: string | null;
	/** unknown: the flow's conn record isn't written yet, so neither MAC nor VLAN is known */
	vlan_state: VlanState;
}

export interface LocalServiceRow {
	protocol: 'mdns' | 'ssdp';
	/** Raw DNS-SD type, e.g. "_airplay._tcp"; null for SSDP */
	service_type: string | null;
	instance: string | null;
	sender: ServiceSender;
	last_seen: string;
}

export interface LocalServicesResponse {
	from: string;
	to: string;
	/** A list or a read hit its cap: the rows are not every announcement */
	truncated: boolean;
	rows: LocalServiceRow[];
}

const isNullableString = (v: unknown) => v === null || isString(v);
const isSender = (s: unknown) =>
	isObject(s) &&
	isString(s.ip) &&
	isNullableString(s.mac) &&
	isNullableString(s.name) &&
	isNullableString(s.vlan) &&
	(s.vlan_state === 'tagged' || s.vlan_state === 'untagged' || s.vlan_state === 'unknown');
const isRow = (r: unknown) =>
	isObject(r) &&
	(r.protocol === 'mdns' || r.protocol === 'ssdp') &&
	isNullableString(r.service_type) &&
	isNullableString(r.instance) &&
	isSender(r.sender) &&
	isString(r.last_seen);

/** The announcements seen in the window. Throws the daemon's reason, or on a malformed reply. */
export async function getLocalServices(opts: { from: string; to: string }): Promise<LocalServicesResponse> {
	const q = new URLSearchParams({ from: opts.from, to: opts.to });
	const body = await getJson(`/api/local-services?${q.toString()}`, 'Local services');
	const ok =
		isObject(body) &&
		isString(body.from) &&
		isString(body.to) &&
		typeof body.truncated === 'boolean' &&
		Array.isArray(body.rows) &&
		body.rows.every(isRow);
	if (!ok) throw new Error('Local services failed: the reply was malformed');
	return body as unknown as LocalServicesResponse;
}
