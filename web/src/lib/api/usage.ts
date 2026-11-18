/**
 * Client for the durable usage ledger (F4, NET-329): the month's internet use, day by day, counted in the
 * owner's time zone, and that time zone (`/api/settings/timezone`). Contract: plans/2026-11-18-f4-usage-ledger.md §4.5.
 */

/**
 * A day's state, the first that applies (§4.5): `future` is after today and has no figures;
 * `not_counted` is before `since` or a day with no raw data when counting began; `stale` failed its
 * last recount (today: none in 45 min); `pending` hasn't been counted yet; `recount_pending` and
 * `old_rules` were counted under earlier exclusions (recountable, or not because raw data was cleared);
 * `approximate` lost raw data before it settled.
 */
export type UsageDayStatus = 'future' | 'not_counted' | 'stale' | 'pending' | 'recount_pending' | 'old_rules' | 'approximate' | 'counted';

export interface UsageBytes {
	download: number;
	upload: number;
	/** Between your own devices; not in `total`. */
	local: number;
	/** What crossed the ISP link: download + upload. */
	total: number;
}

export interface UsageDay {
	/** The local date, YYYY-MM-DD, in the ledger's zone. */
	date: string;
	/** The local day's UTC bounds, ISO; `end` is exclusive (23 or 25 hours on a daylight-saving day). */
	start: string;
	end: string;
	/** The end of what was counted (today: the last recount's query time); null before any count. */
	cutoff: string | null;
	/** Null where the day has no figures (`future`, `not_counted`, `pending`). */
	download: number | null;
	upload: number | null;
	local: number | null;
	/** download + upload, as on UsageBytes */
	total: number | null;
	status: UsageDayStatus;
	counted_at: string | null;
}

/** The ledger's sweep through older days (§4.4); the deploy check watches it. */
export interface UsageSweep {
	id: number;
	cursor: string | null;
	chunks_done: number;
	chunks_failed: number;
	finished_at: string | null;
}

export interface UsageDaily {
	/** The zone the days are counted in. */
	tz: string;
	/** A zone the owner picked that the ledger hasn't switched to yet. */
	pending_tz: string | null;
	/** The first counted local day, YYYY-MM-DD. */
	since: string | null;
	generation: number;
	updated_at: string | null;
	days: UsageDay[];
	/** Every day with figures, summed. */
	bytes: UsageBytes;
	/** Every non-future day is `counted`. */
	complete: boolean;
	gaps: { date: string; reason: UsageDayStatus }[];
}

export interface UsageMonth extends UsageDaily {
	year: number;
	month: number;
	/** The local month's bounds, ISO with their offsets; `month_end` is exclusive. */
	month_start: string;
	month_end: string;
	/** Null for a past month, under an hour in, or while any elapsed day isn't `counted`. */
	projected: number | null;
	daily_rate: number | null;
	days_remaining: number | null;
	sweep: UsageSweep | null;
}

export interface OwnerTimezone {
	tz: string;
	/** False until the owner picks one; NetTap counts in UTC until then. */
	set: boolean;
}

/** A save, or the daemon's reason it couldn't. */
export type SaveResult<T> = { ok: true; data: T } | { ok: false; error: string };

/** A day carries figures unless it is in the future, not counted or not counted yet (§4.5 `bytes`). */
export const hasFigures = (d: Pick<UsageDay, 'status'>): boolean => !['future', 'not_counted', 'pending'].includes(d.status);

/** The owner's current month, in the owner's time zone, with every day of it (as `/api/usage/daily` gives them). */
export async function getUsageMonth(): Promise<UsageMonth> {
	const res = await fetch('/api/usage/month');
	if (!res.ok) throw new Error(`Monthly usage failed: HTTP ${res.status}`);
	return res.json();
}

export async function getTimezone(): Promise<OwnerTimezone> {
	const res = await fetch('/api/settings/timezone');
	if (!res.ok) throw new Error(`Time zone failed: HTTP ${res.status}`);
	const body = await res.json();
	if (typeof body?.tz !== 'string') throw new Error('Time zone failed: the reply named no zone');
	return { tz: body.tz, set: body.set === true };
}

/** Count days in `tz` from now on; a 400 carries the daemon's reason ("That isn't a time zone NetTap knows"). */
export async function setTimezone(tz: string): Promise<SaveResult<OwnerTimezone>> {
	try {
		const res = await fetch('/api/settings/timezone', {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ tz }),
		});
		const body = await res.json().catch(() => null);
		if (!res.ok) return { ok: false, error: typeof body?.error === 'string' ? body.error : `HTTP ${res.status}` };
		return { ok: true, data: { tz: typeof body?.tz === 'string' ? body.tz : tz, set: true } };
	} catch {
		return { ok: false, error: "couldn't reach NetTap" };
	}
}
