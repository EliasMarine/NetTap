/**
 * Device traffic compare (NET-265): GET /api/moment/device-compare (daemon/api/device_compare.py).
 * The connections one device started in two equal, non-overlapping periods, by destination.
 */
import { getJson, isNumber, isObject, isString } from './drilldown';

export interface ComparePeriod {
	from: string;
	to: string;
	/** every connection the device started in [from, to), whatever the lists hold */
	total_bytes: number;
	/** destinations listed; a lower bound when !list_complete, null when !buckets_exact */
	destinations: number | null;
	list_complete: boolean;
	buckets_exact: boolean;
}

export interface CompareDestination {
	ip: string;
	/** the AS organisation, when Zeek's record had one */
	org: string | null;
	bytes: number;
}

export interface CompareChange {
	ip: string;
	org: string | null;
	a_bytes: number;
	b_bytes: number;
	delta: number;
}

/** The first 50 rows and how many there are in all */
export interface CompareList<R> {
	total: number;
	items: R[];
}

export interface DeviceCompareResponse {
	ip: string;
	a: ComparePeriod;
	b: ComparePeriod;
	/** no shard cut a list short: false sends only the totals */
	exact: boolean;
	/** exact, and every destination listed in both periods */
	complete: boolean;
	/** null unless complete */
	new: CompareList<CompareDestination> | null;
	gone: CompareList<CompareDestination> | null;
	/** null unless exact; partial: only destinations listed in both */
	changed: (CompareList<CompareChange> & { partial: boolean }) | null;
}

export interface CompareQuery {
	ip: string;
	a_from: string;
	a_to: string;
	b_from: string;
	b_to: string;
}

const isBoolean = (v: unknown): v is boolean => typeof v === 'boolean';
const isOrg = (v: unknown) => v === null || isString(v);
const isPeriod = (p: unknown) =>
	isObject(p) &&
	isString(p.from) &&
	isString(p.to) &&
	isNumber(p.total_bytes) &&
	(p.destinations === null || isNumber(p.destinations)) &&
	isBoolean(p.list_complete) &&
	isBoolean(p.buckets_exact);
const isList = (v: unknown, ok: (x: Record<string, unknown>) => boolean) =>
	isObject(v) && isNumber(v.total) && Array.isArray(v.items) && v.items.every((x) => isObject(x) && isString(x.ip) && isOrg(x.org) && ok(x));
const isDestination = (x: Record<string, unknown>) => isNumber(x.bytes);
const isChange = (x: Record<string, unknown>) => [x.a_bytes, x.b_bytes, x.delta].every(isNumber);

function wellFormed(body: unknown): body is DeviceCompareResponse {
	if (!isObject(body) || !isString(body.ip) || !isPeriod(body.a) || !isPeriod(body.b) || !isBoolean(body.exact) || !isBoolean(body.complete)) return false;
	// what the daemon withholds is null, never a shorter list
	const lists = body.complete ? isList(body.new, isDestination) && isList(body.gone, isDestination) : body.new === null && body.gone === null;
	const changed = body.exact ? isList(body.changed, isChange) && isBoolean((body.changed as Record<string, unknown>).partial) : body.changed === null;
	return lists && changed;
}

/** Throws the daemon's own reason (a 400's sentence, busy, too slow) and on a malformed reply. */
export async function getDeviceCompare(q: CompareQuery): Promise<DeviceCompareResponse> {
	const body = await getJson(`/api/moment/device-compare?${new URLSearchParams({ ...q }).toString()}`, 'Device compare');
	if (!wellFormed(body)) throw new Error('Device compare failed: the reply was malformed');
	return body;
}
