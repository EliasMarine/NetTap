/**
 * MAC address helpers (NET-316).
 */

const MAC = /^[0-9a-f]{2}([:-][0-9a-f]{2}){5}$/i;

/**
 * A MAC the device made up rather than its maker's: the locally administered bit (0x02 of the
 * first byte) is set, so the second hex digit is 2, 6, A or E. Phones and laptops do this per
 * network for privacy, which is why such a MAC can change. False for anything that isn't a MAC.
 */
export function isPrivateMac(mac: string): boolean {
	const text = mac.trim();
	return MAC.test(text) && (parseInt(text.slice(0, 2), 16) & 0x02) !== 0;
}
