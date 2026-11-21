/**
 * NET-331: watched devices ("tell me if this device goes quiet").
 *
 *   GET /api/devices/watched                                  → WatchedDevicesResponse
 *   PUT /api/devices/registry/{mac}/details {watch_after_min} → {device}
 *
 * The watch is one of F2's device details. A body of only {"watch_after_min": null} clears it
 * even for a device the registry no longer knows, so a watch restored from a backup can be removed.
 */
import { saveDevice, type RegistryDevice } from './devices-registry';

/** The daemon's allowed watch times, in minutes (device_details.WATCH_CHOICES). */
export const WATCH_CHOICES = [15, 30, 60, 240, 1440] as const;
export type WatchMinutes = (typeof WATCH_CHOICES)[number];

export type WatchState = 'unknown' | 'up' | 'down';

/** The last run of the daemon's watched-devices check. Times are ISO strings, null before the first. */
export interface WatchCheck {
	attempt_at: string | null;
	success_at: string | null;
	capture_at: string | null;
	coverage_since: string | null;
	/** Why the last run didn't look: capture not ready, nothing new indexed, or the details file unreadable. */
	skipped: 'mode' | 'pipeline' | 'store' | null;
	/** With skipped "mode": the daemon's fixed words for why, such as "promiscuous mode is off". */
	reason?: string | null;
	/** A fixed sentence when the check failed or its state file is unreadable. */
	error: string | null;
}

export interface WatchedDevice {
	mac: string;
	/** The owner's own name, or null. */
	name: string | null;
	after_min: number;
	state: WatchState;
	/** The last confirmed sighting (the incident's when down), or null before the first. */
	seen_at: string | null;
	/** When the device entered its state, or null while waiting for the first sighting. */
	since: string | null;
}

export interface WatchedDevicesResponse {
	check: WatchCheck;
	devices: WatchedDevice[];
}

/** Why watching is off in bridge mode, shown wherever the Watch control or card would be. */
export const WATCH_BRIDGE_NOTE =
	"Watching isn't available in inline bridge mode: every device's traffic reaches NetTap with the router's MAC address, so NetTap can't tell when one goes quiet.";

/** The plain-English name of a watch time: "15 minutes", "1 hour", "1 day". */
export function watchLabel(minutes: number): string {
	if (minutes % 1440 === 0) return minutes === 1440 ? '1 day' : `${minutes / 1440} days`;
	if (minutes % 60 === 0) return minutes === 60 ? '1 hour' : `${minutes / 60} hours`;
	return `${minutes} minutes`;
}

/** True for a watch time the daemon allows; anything else reads as not watched. */
export const isWatchMinutes = (value: unknown): value is WatchMinutes => (WATCH_CHOICES as readonly unknown[]).includes(value);

// OLD CODE START — TypeScript review M4: the daemon's own reason (its 503 sentence) never reached the card
// export async function getWatchedDevices(): Promise<WatchedDevicesResponse> {
// 	const res = await fetch('/api/devices/watched');
// 	if (!res.ok) throw new Error(`Watched devices failed: HTTP ${res.status}`);
// 	return res.json();
// }
// OLD CODE END
/** The watched list, or throws a reason fit to show: the daemon's own sentence when it sent one. */
export async function getWatchedDevices(): Promise<WatchedDevicesResponse> {
	let res: Response;
	try {
		res = await fetch('/api/devices/watched');
	} catch {
		throw new Error("Couldn't reach NetTap. Check the connection and try again.");
	}
	if (!res.ok) {
		const body = await res.json().catch(() => null);
		throw new Error(body?.error ?? `NetTap answered HTTP ${res.status}.`);
	}
	return res.json();
}

/** Watch a device for `minutes` of silence, or stop watching it (null). Resolves to the device as saved. */
export const setWatch = (mac: string, minutes: WatchMinutes | null): Promise<RegistryDevice> =>
	saveDevice(mac, 'details', 'PUT', { watch_after_min: minutes });
