import { describe, it, expect } from 'vitest';
import { downloadErrorPage } from './download-error-page';
import { DOWNLOAD_ERROR_MESSAGE } from '$lib/api/pcap';

// NET-373: a refused PCAP download reads as words in its tab and tells the PCAP page why
async function page(reason: unknown, status = 404) {
	const res = downloadErrorPage(reason, status);
	const html = await res.text();
	return { res, html, doc: new DOMParser().parseFromString(html, 'text/html') };
}

/** The message the page's script posts, read back out of the script. */
function posted(doc: Document): { message: unknown; target: string } {
	const script = doc.querySelector('script')?.textContent ?? '';
	const sent: { message: unknown; target: string }[] = [];
	const opener = { postMessage: (message: unknown, target: string) => sent.push({ message, target }) };
	new Function('window', 'location', script)({ opener }, { origin: 'https://nettap.local' });
	expect(sent).toHaveLength(1);
	return sent[0];
}

describe('downloadErrorPage', () => {
	it("keeps the daemon's status, is HTML, and is never cached", async () => {
		const { res } = await page('No capture file holds packets from this window.', 404);
		expect(res.status).toBe(404);
		expect(res.headers.get('content-type')).toBe('text/html; charset=utf-8');
		expect(res.headers.get('cache-control')).toBe('no-store');
	});

	it('says what happened in words and posts the reason to the opener on its own origin', async () => {
		const reason = 'No capture file holds packets from this window.';
		const { doc } = await page(reason);
		expect(doc.querySelector('h1')?.textContent).toBe("The download didn't start");
		expect(doc.body.textContent).toContain(reason);
		expect(posted(doc)).toEqual({ message: { type: DOWNLOAD_ERROR_MESSAGE, message: reason }, target: 'https://nettap.local' });
	});

	it('keeps markup in the reason as text, in the page and in the script', async () => {
		// a line separator inside a script string is a syntax error in older engines
		const reason = `Invalid display filter: "</script><img src=x onerror=alert(1)>" & 'more' \u2028 end`;
		const { doc } = await page(reason, 400);
		expect(doc.querySelectorAll('script')).toHaveLength(1);
		expect(doc.querySelector('img')).toBeNull();
		expect(doc.body.textContent).toContain(reason);
		expect(posted(doc).message).toEqual({ type: DOWNLOAD_ERROR_MESSAGE, message: reason });
	});

	it('says the download failed when the daemon gave no reason', async () => {
		for (const reason of [undefined, '', '   ', 42, { error: 'x' }]) {
			const { doc } = await page(reason, 500);
			expect(doc.querySelector('p')?.textContent).toBe('The download failed.');
		}
	});
});
