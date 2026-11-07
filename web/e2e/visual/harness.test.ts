import { describe, it, expect, vi } from 'vitest';
import type { Page } from '@playwright/test';
import { findTileSpills } from './severity-tiles.ts';

// The real config makes temp dirs when it loads, and Playwright's expect only works inside its runner
const { soft } = vi.hoisted(() => ({ soft: vi.fn() }));
// OLD CODE: vi.mock('../../playwright.visual.config.ts', () => ({ DAEMON_URL: 'http://fixture.test' })); (known-issues.ts needs FIRSTRUN_URL now)
vi.mock('../../playwright.visual.config.ts', () => ({ DAEMON_URL: 'http://fixture.test', FIRSTRUN_URL: 'http://firstrun.test' }));
vi.mock('@playwright/test', () => ({
	expect: { soft: (actual: unknown, message: string) => ({ toEqual: (want: unknown) => soft(actual, message, want) }) },
	test: { info: () => ({ annotations: [] }) },
}));

const { checkSeverityTiles } = await import('./harness.ts');

describe('checkSeverityTiles', () => {
	it("runs the tile check in the page and soft-fails on what it finds, naming the theme and width", async () => {
		const page = { evaluate: vi.fn().mockResolvedValue(['Low158,000: the tile overlaps the next one']) };
		await checkSeverityTiles(page as unknown as Page, 'graphite', 1440);
		expect(page.evaluate).toHaveBeenCalledWith(findTileSpills);
		expect(soft).toHaveBeenCalledWith(['Low158,000: the tile overlaps the next one'], 'severity tiles, graphite @ 1440', []);
	});
});
