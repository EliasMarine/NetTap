import { describe, it, expect } from 'vitest';
import { SETTINGS_TABS } from '../../src/routes/settings/settings-helpers.ts';
import { APP_ROUTES } from './routes.ts';

// A typo'd ?tab= falls back to Notifications, so the sweep would check the wrong panel (F6 added Network)
describe('visual routes', () => {
	it('lists each route once', () => {
		const paths = APP_ROUTES.map((r) => r.path);
		expect(new Set(paths).size).toBe(paths.length);
	});

	it('every Settings ?tab= route names a real tab', () => {
		const ids = SETTINGS_TABS.map((t) => t.id as string);
		const tabs = APP_ROUTES.map((r) => new URL(r.path, 'http://x').searchParams.get('tab')).filter((t) => t !== null);
		expect(tabs).toContain('network');
		for (const t of tabs) expect(ids).toContain(t);
	});
});
