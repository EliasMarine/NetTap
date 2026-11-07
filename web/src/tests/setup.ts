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

// Ensure DOM cleanup runs after every test to prevent leaked renders.
afterEach(() => {
	cleanup();
});
