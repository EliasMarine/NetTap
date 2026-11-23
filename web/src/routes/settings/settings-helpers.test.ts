import { describe, it, expect } from 'vitest';
import { SETTINGS_GROUPS, SETTINGS_TABS, tabFrom } from './settings-helpers';

describe('Settings tabs (NET-273)', () => {
	// OLD CODE: it('has four groups and ten tabs, with the ids old links use', () => { (NET-358: + Account)
	it('has four groups and eleven tabs, with the ids old links use', () => {
		expect(SETTINGS_GROUPS.map((g) => g.label)).toEqual(['Alerts & detection', 'Data', 'Network', 'General']);
		// OLD CODE: 'notifications', 'suricata-rules', 'retention', 'capture', 'backup', 'network', 'integrations', 'api-keys', 'display', 'about', (NET-358)
		expect(SETTINGS_TABS.map((t) => t.id)).toEqual([
			'notifications', 'suricata-rules', 'retention', 'capture', 'backup', 'network', 'integrations', 'api-keys', 'display', 'account', 'about',
		]);
		expect(SETTINGS_TABS.find((t) => t.id === 'backup')?.group).toBe('Data');
		expect(SETTINGS_TABS.find((t) => t.id === 'account')).toMatchObject({
			label: 'Account',
			group: 'General',
			intro: 'Your sign-in to this NetTap: change the password you open the dashboard with.',
		});
		expect(SETTINGS_TABS.every((t) => t.intro.endsWith('.'))).toBe(true);
	});

	it.each([
		['/settings?tab=network', 'network'],
		['/settings?tab=capture', 'capture'],
		['/settings?tab=suricata-rules', 'suricata-rules'],
		['/settings?tab=account', 'account'],
		['/settings', 'notifications'],
		['/settings?tab=nope', 'notifications'],
		['/settings?tab=', 'notifications'],
		['/settings?tab=__proto__', 'notifications'],
	])('%s opens %s', (href, tab) => {
		expect(tabFrom(new URL(href, 'http://localhost'))).toBe(tab);
	});
});
