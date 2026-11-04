/** Pure helpers for the top bar (search hand-off and the "Updated" text). */

const IPV4 = /^(\d{1,3})(\.\d{1,3}){3}$/;
const IPV6 = /^[0-9a-f:]+$/i;

/** Where a global search goes: Log Explorer filtered by IP, or searching for the text. */
export function searchTarget(text: string): string | null {
	const q = text.trim();
	if (!q) return null;
	const isIp = IPV4.test(q) || (q.includes(':') && IPV6.test(q));
	return isIp ? `/logs?ip=${encodeURIComponent(q)}` : `/logs?query=${encodeURIComponent(q)}`;
}

/** "Updated 12 s ago", from the page's last fully successful load. */
export function updatedText(updatedAt: number | null, now: number): string {
	if (updatedAt === null) return 'Not updated yet';
	const s = Math.max(0, Math.floor((now - updatedAt) / 1000));
	if (s < 5) return 'Updated just now';
	if (s < 60) return `Updated ${s} s ago`;
	if (s < 3600) return `Updated ${Math.floor(s / 60)} min ago`;
	const at = new Date(updatedAt);
	return `Updated at ${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`;
}
