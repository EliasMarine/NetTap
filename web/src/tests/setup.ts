/**
 * Global test setup for Vitest.
 * Loaded by vitest via the setupFiles config in vite.config.ts.
 */

import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/svelte';
import { afterEach } from 'vitest';

// jsdom has no scrollIntoView. A page that scrolls from a timer (PCAP Search's preview, 50 ms
// after it loads) threw an uncaught TypeError when the timer outlived its test on a slow runner,
// which failed CI's Integration Tests with every test passing.
if (typeof Element !== 'undefined') Element.prototype.scrollIntoView ??= function scrollIntoView() {};

// jsdom has HTMLDialogElement but none of its methods. DetailDrawer opens as a modal (NET-349);
// these stand-ins only toggle `open` and fire `close`, so the browser's own behaviour (the inert
// page, top layer, Escape) is covered by the Playwright suite, not here.
if (typeof HTMLDialogElement !== 'undefined') {
	const proto = HTMLDialogElement.prototype;
	proto.showModal ??= function showModal(this: HTMLDialogElement) {
		this.setAttribute('open', '');
	};
	proto.close ??= function close(this: HTMLDialogElement) {
		if (!this.hasAttribute('open')) return;
		this.removeAttribute('open');
		// the browser queues `close` as a task; firing it synchronously would run page handlers inside
		// the caller (an effect teardown, where Svelte still reads the old props)
		setTimeout(() => this.dispatchEvent(new Event('close')), 0);
	};
}

// Ensure DOM cleanup runs after every test to prevent leaked renders.
afterEach(() => {
	cleanup();
});
