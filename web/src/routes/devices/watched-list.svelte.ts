/**
 * NET-331: the Watched devices card's list. The Devices page's loader reads it with everything else;
 * the card's Try again and Stop watching read only this list, so the rest of the page keeps its state
 * (TypeScript review L1). Newest read wins: an older reply that lands late never overwrites a newer one.
 */
import { getWatchedDevices, type WatchedDevicesResponse } from '$api/devices-watched';

export class WatchedList {
	/** The last list loaded, or null before the first. */
	data = $state<WatchedDevicesResponse | null>(null);
	/** Why the latest read failed, or null when it succeeded (the last list stays). */
	error = $state<string | null>(null);
	#latest = 0;

	/** Reads the list and keeps it if no newer read has started; rejects when the read fails. */
	async load(): Promise<WatchedDevicesResponse> {
		const read = ++this.#latest;
		try {
			const data = await getWatchedDevices();
			if (read === this.#latest) {
				this.data = data;
				this.error = null;
			}
			return data;
		} catch (e) {
			if (read === this.#latest) this.error = e instanceof Error ? e.message : "Couldn't load watched devices.";
			throw e;
		}
	}

	/** The card's own reload: the failure shows on the card, so it isn't thrown on. */
	reload = (): Promise<void> => this.load().then(
		() => undefined,
		() => undefined,
	);
}
