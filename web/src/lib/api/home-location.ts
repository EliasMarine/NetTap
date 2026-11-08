/**
 * Client for the network's home location (Settings › Network location), which the Live page's
 * globe flies packets from. The daemon validates every write; checkHomeLocation mirrors its rules
 * so the form can say what's wrong before sending.
 */

export interface HomeLocation {
	lat: number;
	lon: number;
	label: string;
}

const ENDPOINT = '/api/settings/home-location';
const MAX_LABEL = 80;

/** The daemon's error message, else a plain one with the status. */
async function failure(res: Response, what: string): Promise<Error> {
	const body = await res.json().catch(() => null);
	const message = body && typeof body.error === 'string' ? body.error : `${what}: HTTP ${res.status}`;
	return new Error(message);
}

export async function getHomeLocation(): Promise<HomeLocation | null> {
	const res = await fetch(ENDPOINT);
	if (!res.ok) throw await failure(res, "Couldn't load the network location");
	const body = await res.json();
	return body?.home ?? null;
}

export async function saveHomeLocation(home: HomeLocation): Promise<HomeLocation> {
	const res = await fetch(ENDPOINT, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(home) });
	if (!res.ok) throw await failure(res, "Couldn't save the location");
	return (await res.json()).home;
}

export async function clearHomeLocation(): Promise<void> {
	const res = await fetch(ENDPOINT, { method: 'DELETE' });
	if (!res.ok) throw await failure(res, "Couldn't clear the location");
}

/** A suggestion from NetTap's internet address, looked up on request; not saved. */
export async function lookupWanLocation(): Promise<HomeLocation> {
	const res = await fetch(`${ENDPOINT}/wan-lookup`, { method: 'POST' });
	if (!res.ok) throw await failure(res, "Couldn't look up your WAN location");
	return (await res.json()).suggestion;
}

/** The form's text as a location, or what's wrong with it (the daemon's rules). */
export function checkHomeLocation(form: { label: string; lat: string; lon: string }): HomeLocation | string {
	const lat = Number(form.lat.trim());
	const lon = Number(form.lon.trim());
	const label = form.label.trim();
	if (form.lat.trim() === '' || !Number.isFinite(lat) || lat < -90 || lat > 90) return 'Latitude must be a number from -90 to 90.';
	if (form.lon.trim() === '' || !Number.isFinite(lon) || lon < -180 || lon > 180) return 'Longitude must be a number from -180 to 180.';
	if (label.length > MAX_LABEL) return `The name must be at most ${MAX_LABEL} characters.`;
	return { lat, lon, label };
}
