import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import SettingsNav from './SettingsNav.svelte';

describe('SettingsNav (NET-273)', () => {
	it('shows the four groups and ten tabs, each wired to its panel', () => {
		render(SettingsNav, { active: 'retention', onselect: vi.fn() });

		const tablist = screen.getByRole('tablist', { name: 'Settings sections' });
		const tabs = within(tablist).getAllByRole('tab');
		expect(tabs).toHaveLength(10);
		// the group labels are for the eye only: a tablist owns tabs
		for (const group of ['Alerts & detection', 'Data', 'Network', 'General']) {
			expect(screen.getByText(group, { selector: '.nav-group' })).toHaveAttribute('aria-hidden', 'true');
		}
		const selected = tabs.filter((t) => t.getAttribute('aria-selected') === 'true');
		expect(selected.map((t) => t.textContent?.trim())).toEqual(['Storage & retention']);
		expect(screen.getByRole('tab', { name: 'Storage & retention' })).toHaveAttribute('aria-controls', 'settings-panel-retention');
		expect(screen.getByRole('tab', { name: 'Storage & retention' })).toHaveAttribute('id', 'settings-tab-retention');
		// a roving tabindex: only the selected tab is in the Tab order
		expect(tabs.filter((t) => t.tabIndex === 0)).toEqual(selected);
		expect(tablist).toHaveAttribute('aria-orientation', 'vertical');
	});

	it('selects a clicked tab, but not the one already open', async () => {
		const onselect = vi.fn();
		render(SettingsNav, { active: 'notifications', onselect });

		await fireEvent.click(screen.getByRole('tab', { name: 'Backup & restore' }));
		await fireEvent.click(screen.getByRole('tab', { name: 'Notifications' }));
		expect(onselect.mock.calls).toEqual([['backup']]);
	});

	it.each([
		['notifications', 'ArrowDown', 'suricata-rules', 'Suricata rules'],
		['notifications', 'ArrowRight', 'suricata-rules', 'Suricata rules'],
		['notifications', 'ArrowUp', 'about', 'About'],
		['about', 'ArrowDown', 'notifications', 'Notifications'],
		['capture', 'ArrowLeft', 'retention', 'Storage & retention'],
		['capture', 'Home', 'notifications', 'Notifications'],
		['capture', 'End', 'about', 'About'],
	] as const)('from %s, %s selects %s and moves focus to it', async (active, key, next, label) => {
		const onselect = vi.fn();
		render(SettingsNav, { active, onselect });

		const current = screen.getAllByRole('tab').find((t) => t.getAttribute('aria-selected') === 'true')!;
		await fireEvent.keyDown(current, { key });
		expect(onselect).toHaveBeenCalledWith(next);
		expect(document.activeElement).toBe(screen.getByRole('tab', { name: label }));
	});

	it('ignores other keys', async () => {
		const onselect = vi.fn();
		render(SettingsNav, { active: 'capture', onselect });

		await fireEvent.keyDown(screen.getByRole('tab', { name: 'Capture' }), { key: 'a' });
		expect(onselect).not.toHaveBeenCalled();
	});
});
