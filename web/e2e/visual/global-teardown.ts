import { rmSync } from 'node:fs';

/** Removes the temp root made when playwright.visual.config.ts loaded (data dirs, token, session). */
export default function globalTeardown(): void {
	const root = process.env.NETTAP_VISUAL_TMP;
	if (root) rmSync(root, { recursive: true, force: true });
}
