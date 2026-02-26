/**
 * Global test setup for Vitest.
 * Loaded by vitest via the setupFiles config in vite.config.ts.
 */

import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/svelte';
import { afterEach } from 'vitest';

// Ensure DOM cleanup runs after every test to prevent leaked renders.
afterEach(() => {
	cleanup();
});
