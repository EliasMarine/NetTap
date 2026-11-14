import { describe, it, expect } from 'vitest';
import { isRedirect } from '@sveltejs/kit';
import { load as suricataRules } from './suricata-rules/+page';
import { load as notifications } from './notifications/+page';
import { load as backup } from './backup/+page';

// NET-273: the three pages are Settings tabs now; their old addresses open the tab
describe('old Settings sub-pages', () => {
	it.each([
		['/settings/suricata-rules', suricataRules, '/settings?tab=suricata-rules'],
		['/settings/notifications', notifications, '/settings?tab=notifications'],
		['/settings/backup', backup, '/settings?tab=backup'],
	])('%s redirects permanently to its tab', (_path, load, location) => {
		let thrown: unknown;
		try {
			(load as unknown as () => void)();
		} catch (err) {
			thrown = err;
		}
		expect(isRedirect(thrown)).toBe(true);
		expect(thrown).toMatchObject({ status: 308, location });
	});
});
