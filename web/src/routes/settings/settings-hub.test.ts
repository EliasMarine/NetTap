/**
 * NET-273: one Settings page. The open tab follows the URL, only it is mounted, an unsaved edit holds
 * navigation behind a Keep editing / Discard bar, and a change being sent holds it until it lands.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { pageRefresh } from '$lib/stores/pageRefresh';
import { goto, followLink, historyState, resetNavigation, traverse, unload } from '../../tests/app-navigation.svelte';
import { SETTINGS_TABS } from './settings-helpers';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('../../tests/app-navigation.svelte'));
vi.mock('$app/navigation', () => import('../../tests/app-navigation.svelte'));

type Reply = { status?: number; body: unknown };
type Route = (init?: RequestInit) => Reply | Promise<Reply>;

const HUB_LISTS: Record<string, Route> = {
	'/api/notifications/channels': () => ({ body: { channels: [], count: 0 } }),
	'/api/notifications/rules': () => ({ body: { rules: [], count: 0 } }),
	'/api/notifications/log': () => ({ body: { log: [], count: 0 } }),
};

const STORAGE = { hot_days: 90, warm_days: 180, cold_days: 30, disk_threshold_percent: 80, emergency_threshold_percent: 90 };

/** Stub fetch: URLs in `routes` get their reply (a route may wait), the notification lists are empty, everything else a 500. */
function stubFetch(routes: Record<string, Route> = {}) {
	const all = { ...HUB_LISTS, ...routes };
	const fn = vi.fn(async (url: string, init?: RequestInit) => {
		const route = all[url.split('?')[0]];
		if (!route) return { ok: false, status: 500, json: async () => ({}) };
		const { status = 200, body } = await route(init);
		return { ok: status < 400, status, json: async () => body };
	});
	vi.stubGlobal('fetch', fn);
	return fn;
}

/** A reply the test lets through when it chooses. */
function gate() {
	let open: () => void = () => {};
	const opened = new Promise<void>((resolve) => (open = resolve));
	return { wait: () => opened, open };
}

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

const tab = (name: string) => screen.getByRole('tab', { name });
const panel = () => screen.getByRole('tabpanel');

async function openTab(name: string) {
	await fireEvent.click(tab(name));
	await flush();
}

const hotDays = () => screen.getByLabelText('Hot tier (Zeek metadata and Suricata alerts)') as HTMLInputElement;
const timeRange = () => screen.getByLabelText('Default time range');

/** An in-app link to `href`, for `followLink`. */
function linkTo(href: string) {
	const link = document.createElement('a');
	link.setAttribute('href', href);
	return link;
}
const BUSY_BAR = 'Sending your change… wait for it to finish before leaving the tab.';

beforeEach(() => resetNavigation());
afterEach(() => {
	vi.clearAllMocks();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	localStorage.clear();
});

describe('Settings hub — tabs from the URL', () => {
	it.each([
		['suricata-rules', 'Rules Suricata runs'],
		['notifications', 'Notification channels'],
		['backup', 'Export configuration'],
		// NET-363: Infrastructure's Configure UniFi lands here
		['integrations', 'UniFi controller'],
	])('?tab=%s opens that panel', async (id, heading) => {
		resetNavigation(`http://localhost/settings?tab=${id}`);
		stubFetch();
		render(Page);
		await flush();

		expect(panel()).toHaveAttribute('id', `settings-panel-${id}`);
		expect(within(panel()).getByRole('heading', { name: heading })).toBeInTheDocument();
		expect(screen.getAllByRole('heading', { level: 1 }).map((h) => h.textContent)).toEqual(['Settings']);
	});

	it('a tab click navigates to ?tab=, adding a history entry', async () => {
		stubFetch();
		render(Page);
		await openTab('Capture');

		expect(goto).toHaveBeenCalledWith('?tab=capture', { reset: false });
		expect(historyState()).toEqual({ entries: ['/settings', '/settings?tab=capture'], index: 1 });
		expect(panel()).toHaveAttribute('id', 'settings-panel-capture');
		expect(tab('Capture')).toHaveAttribute('aria-selected', 'true');
	});

	it('an in-page ?tab= link, Back and Forward switch the panel while Settings stays open', async () => {
		resetNavigation('http://localhost/settings?tab=api-keys');
		stubFetch({ '/api/settings/api-keys': () => ({ body: { keys: {} } }) });
		render(Page);
		await flush();
		const heading = screen.getByRole('heading', { level: 1 });

		followLink(screen.getByRole('link', { name: 'Settings › Suricata rules' }));
		await flush();
		expect(panel()).toHaveAttribute('id', 'settings-panel-suricata-rules');

		traverse(-1);
		await flush();
		expect(panel()).toHaveAttribute('id', 'settings-panel-api-keys');

		traverse(1);
		await flush();
		expect(panel()).toHaveAttribute('id', 'settings-panel-suricata-rules');
		expect(screen.getByRole('heading', { level: 1 })).toBe(heading);
	});

	it('every tab controls a panel that exists, and only the open one has its component', async () => {
		stubFetch();
		const { container } = render(Page);
		await flush();

		for (const t of screen.getAllByRole('tab')) {
			expect(document.getElementById(t.getAttribute('aria-controls')!)).not.toBeNull();
		}
		const panels = Array.from(container.querySelectorAll<HTMLElement>('[role="tabpanel"]'));
		// OLD CODE: expect(panels).toHaveLength(10); (NET-358: + Account)
		expect(panels).toHaveLength(11);
		expect(panels.filter((p) => !p.hidden).map((p) => p.id)).toEqual(['settings-panel-notifications']);
		expect(panels.filter((p) => p.childElementCount > 0).map((p) => p.id)).toEqual(['settings-panel-notifications']);
	});

	it.each(SETTINGS_TABS.map((t) => [t.id, t.group, t.intro]))('the %s panel opens with its group and a plain-English line', async (id, group, intro) => {
		resetNavigation(`http://localhost/settings?tab=${id}`);
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);

		const line = within(panel()).getByText(intro);
		expect(line.closest('.panel-intro')).toHaveTextContent(group);
	});
});

describe('Settings hub — unsaved edits', () => {
	async function openDirtyDisplay() {
		resetNavigation('http://localhost/settings?tab=display');
		stubFetch();
		render(Page);
		await flush();
		await fireEvent.change(screen.getByLabelText('Default time range'), { target: { value: '7d' } });
		expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
	}

	// F4 (NET-329): the time zone is saved on NetTap, and an unsaved pick holds the tab like any other edit
	it('holds a tab switch on an unsaved time zone alone', async () => {
		resetNavigation('http://localhost/settings?tab=display');
		stubFetch({ '/api/settings/timezone': () => ({ body: { tz: 'UTC', set: true } }) });
		render(Page);
		await flush();
		await fireEvent.change(screen.getByLabelText('Your time zone'), { target: { value: 'Europe/London' } });

		await fireEvent.click(tab('About'));
		expect(screen.getByText('You have unsaved changes in Display.')).toBeInTheDocument();
		expect(panel()).toHaveAttribute('id', 'settings-panel-display');
	});

	// F6 (NET-339): the data cap card on Network counts like the tab's other forms
	it('holds a tab switch on an unsaved data cap alone, and while a cap is being saved', async () => {
		resetNavigation('http://localhost/settings?tab=network');
		const save = gate();
		const cap = { monthly_cap_bytes: 0, monthly_cap_gb: 0, enabled: false, current_usage_bytes: 0, usage_percent: 0, since: null, complete: false, lower_bound_bytes: 0 };
		stubFetch({
			'/api/bandwidth/cap': () => ({ body: cap }),
			'/api/settings/bandwidth-cap': async () => {
				await save.wait();
				return { body: { result: 'saved', monthly_cap_gb: 100, monthly_cap_bytes: 100e9 } };
			},
		});
		render(Page);
		await flush();
		await fireEvent.input(screen.getByLabelText('Monthly cap in GB'), { target: { value: '100' } });

		await fireEvent.click(tab('About'));
		expect(screen.getByText('You have unsaved changes in Network.')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));

		await fireEvent.click(screen.getByRole('button', { name: 'Save data cap' }));
		await fireEvent.click(tab('About'));
		expect(screen.getByText(BUSY_BAR)).toBeInTheDocument();
		expect(panel()).toHaveAttribute('id', 'settings-panel-network');

		save.open();
		await flush();
		expect(await screen.findByText('Data cap saved.')).toBeInTheDocument();
	});

	// NET-340: the weekly report card saves on its own, so the Notifications tab passes its state up
	it('holds a tab switch on an unsaved weekly report alone, and while it is being saved', async () => {
		resetNavigation('http://localhost/settings?tab=notifications');
		const save = gate();
		stubFetch({
			'/api/reports/schedules': () => ({ body: { schedules: [], tz: 'Europe/London' } }),
			'/api/reports/card': async (init) => {
				await save.wait();
				return { body: { ...JSON.parse(String(init?.body)), id: '6f1d2c3b-4a5e-4f60-8a7b-9c0d1e2f3a4b', tz: 'Europe/London', rev: 1, confirm_token: 't', card: true } };
			},
		});
		render(Page);
		await flush();
		await fireEvent.input(await screen.findByLabelText('Email addresses, one per line'), { target: { value: 'owner@example.com' } });

		await fireEvent.click(tab('About'));
		expect(screen.getByText('You have unsaved changes in Notifications.')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));

		await fireEvent.click(screen.getByRole('button', { name: 'Save weekly report' }));
		await fireEvent.click(tab('About'));
		expect(screen.getByText(BUSY_BAR)).toBeInTheDocument();

		save.open();
		await flush();
		// OLD CODE: expect(await screen.findByText('Saved. The weekly report is on.')).toBeInTheDocument(); (NET-357: a new schedule starts off, and only the addresses were edited)
		expect(await screen.findByText('Saved. The weekly report is off.')).toBeInTheDocument();
	});

	it('holds a tab switch: Keep editing stays, Discard and continue goes', async () => {
		await openDirtyDisplay();

		await fireEvent.click(tab('About'));
		expect(screen.getByText('You have unsaved changes in Display.')).toBeInTheDocument();
		expect(panel()).toHaveAttribute('id', 'settings-panel-display');
		expect(historyState().entries).toEqual(['/settings?tab=display']);

		await fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
		expect(screen.queryByText('You have unsaved changes in Display.')).not.toBeInTheDocument();
		expect(screen.getByLabelText('Default time range')).toHaveValue('7d');

		await fireEvent.click(tab('About'));
		await fireEvent.click(screen.getByRole('button', { name: 'Discard and continue' }));
		await flush();
		expect(panel()).toHaveAttribute('id', 'settings-panel-about');
		expect(historyState()).toEqual({ entries: ['/settings?tab=display', '/settings?tab=about'], index: 1 });

		// The edit was dropped: Display opens again on what is saved, and nothing holds the next switch
		traverse(-1);
		await flush();
		expect(screen.getByLabelText('Default time range')).toHaveValue('');
		await openTab('About');
		expect(panel()).toHaveAttribute('id', 'settings-panel-about');
	});

	it('Discard on a link to the open tab puts its saved values back, and the next edit is held again', async () => {
		await openDirtyDisplay();

		followLink(linkTo('/settings?tab=display'));
		await flush();
		expect(screen.getByText('You have unsaved changes in Display.')).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Discard and continue' }));
		await flush();
		expect(goto).toHaveBeenLastCalledWith(expect.any(URL), { reset: false });
		expect(timeRange()).toHaveValue('');
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();

		await fireEvent.change(timeRange(), { target: { value: '7d' } });
		await fireEvent.click(tab('About'));
		expect(screen.getByText('You have unsaved changes in Display.')).toBeInTheDocument();
		expect(panel()).toHaveAttribute('id', 'settings-panel-display');
	});

	it('moves focus to the bar, and Keep editing puts it back where it was', async () => {
		await openDirtyDisplay();
		timeRange().focus();

		followLink(linkTo('/settings?tab=about'));
		await flush();
		expect(screen.getByRole('button', { name: 'Keep editing' })).toHaveFocus();
		await fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
		expect(timeRange()).toHaveFocus();

		// From a tab click, focus goes back to the tab that is still open
		tab('About').focus();
		await fireEvent.click(tab('About'));
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
		expect(tab('Display')).toHaveFocus();
	});

	it('a second hold while the bar has focus keeps the first place for Keep editing', async () => {
		await openDirtyDisplay();
		timeRange().focus();

		followLink(linkTo('/settings?tab=about'));
		await flush();
		expect(screen.getByRole('button', { name: 'Keep editing' })).toHaveFocus();
		followLink(linkTo('/settings?tab=backup'));
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
		expect(timeRange()).toHaveFocus();
	});

	it('Discard and continue puts focus on the tab it opens', async () => {
		await openDirtyDisplay();

		await fireEvent.click(tab('About'));
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Discard and continue' }));
		await flush();
		expect(panel()).toHaveAttribute('id', 'settings-panel-about');
		expect(tab('About')).toHaveFocus();
	});

	it("lets only Discard's own navigation through: after a Back that goes nowhere, the next switch is held", async () => {
		stubFetch();
		render(Page);
		await openTab('Display');
		await fireEvent.change(timeRange(), { target: { value: '7d' } });
		vi.spyOn(window.history, 'go').mockImplementation(() => {});

		traverse(-1);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Discard and continue' }));
		await flush();
		expect(panel()).toHaveAttribute('id', 'settings-panel-display');

		await fireEvent.change(timeRange(), { target: { value: '1h' } });
		await fireEvent.click(tab('About'));
		expect(screen.getByText('You have unsaved changes in Display.')).toBeInTheDocument();
		expect(panel()).toHaveAttribute('id', 'settings-panel-display');
	});

	it('Back, then Discard, carries on backward, and Back again keeps going', async () => {
		stubFetch();
		render(Page);
		await openTab('About');
		await openTab('Display');
		await fireEvent.change(screen.getByLabelText('Default time range'), { target: { value: '7d' } });
		const go = vi.spyOn(window.history, 'go').mockImplementation((delta = 0) => traverse(delta));

		traverse(-1);
		await flush();
		expect(panel()).toHaveAttribute('id', 'settings-panel-display');
		expect(historyState().index).toBe(2);

		await fireEvent.click(screen.getByRole('button', { name: 'Discard and continue' }));
		await flush();
		expect(go).toHaveBeenCalledWith(-1);
		expect(panel()).toHaveAttribute('id', 'settings-panel-about');
		expect(goto).toHaveBeenCalledTimes(2); // the two tab clicks: Discard didn't push a new entry

		traverse(-1);
		await flush();
		expect(panel()).toHaveAttribute('id', 'settings-panel-notifications');
		expect(historyState()).toEqual({ entries: ['/settings', '/settings?tab=about', '/settings?tab=display'], index: 0 });
	});

	it('Forward, then Discard, carries on forward', async () => {
		stubFetch();
		render(Page);
		await openTab('Display');
		await openTab('About');
		traverse(-1);
		await flush();
		await fireEvent.change(screen.getByLabelText('Default time range'), { target: { value: '7d' } });
		const go = vi.spyOn(window.history, 'go').mockImplementation((delta = 0) => traverse(delta));

		traverse(1);
		await flush();
		expect(screen.getByText('You have unsaved changes in Display.')).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Discard and continue' }));
		await flush();
		expect(go).toHaveBeenCalledWith(1);
		expect(panel()).toHaveAttribute('id', 'settings-panel-about');
		expect(historyState()).toEqual({ entries: ['/settings', '/settings?tab=display', '/settings?tab=about'], index: 2 });
	});

	it('holds a switch away from edited notification preferences', async () => {
		stubFetch({
			'/api/notifications/config': () => ({
				body: { min_severity: 2, email: { enabled: false, recipients: [], smtp_configured: true }, webhook: { enabled: false } },
			}),
		});
		render(Page);
		await flush();
		await fireEvent.change(screen.getByLabelText('Alert severity threshold'), { target: { value: 'low' } });

		await fireEvent.click(tab('About'));
		expect(screen.getByText('You have unsaved changes in Notifications.')).toBeInTheDocument();
		expect(panel()).toHaveAttribute('id', 'settings-panel-notifications');
	});

	it("asks the browser to prompt on a reload only while there's something to lose", async () => {
		resetNavigation('http://localhost/settings?tab=display');
		stubFetch();
		render(Page);
		await flush();
		expect(unload()).toBe(false);

		await fireEvent.change(screen.getByLabelText('Default time range'), { target: { value: '7d' } });
		expect(unload()).toBe(true);
		await flush();
		expect(screen.queryByText('You have unsaved changes in Display.')).not.toBeInTheDocument();
	});
});

describe('Settings hub — a change being sent holds navigation', () => {
	it('a restore holds the switch until it lands, then Retention reads the restored values', async () => {
		resetNavigation('http://localhost/settings?tab=retention');
		let hot = 90;
		const restore = gate();
		const fetchFn = stubFetch({
			'/api/setup/storage': () => ({ body: { ...STORAGE, hot_days: hot } }),
			'/api/backup/validate': () => ({ body: { is_valid: true, warnings: [], errors: [], preview: {} } }),
			'/api/backup/import': async () => {
				await restore.wait();
				hot = 45;
				return { body: { success: true, applied: ['storage_retention'], errors: [], warnings: [] } };
			},
		});
		const reads = () => fetchFn.mock.calls.filter(([url, init]) => url === '/api/setup/storage' && !init?.method).length;
		const { container } = render(Page);
		await flush();
		expect(hotDays().value).toBe('90');

		await openTab('Backup & restore');
		const file = new File([JSON.stringify({ metadata: { schema_version: 1 }, sections: {} })], 'nettap.json', { type: 'application/json' });
		await fireEvent.change(container.querySelector('input[type="file"]') as HTMLInputElement, { target: { files: [file] } });
		await fireEvent.click(await screen.findByRole('button', { name: 'Apply configuration' }));

		await fireEvent.click(tab('Storage & retention'));
		expect(screen.getByText(BUSY_BAR)).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Discard and continue' })).not.toBeInTheDocument();
		expect(panel()).toHaveAttribute('id', 'settings-panel-backup');

		restore.open();
		expect(await screen.findByText('Import successful')).toBeInTheDocument();
		expect(screen.queryByText(BUSY_BAR)).not.toBeInTheDocument();

		await openTab('Storage & retention');
		expect(reads()).toBe(2);
		expect(hotDays().value).toBe('45');
	});

	it('a save holds the switch with no Discard, and the switch works once it lands', async () => {
		resetNavigation('http://localhost/settings?tab=retention');
		const save = gate();
		stubFetch({
			'/api/setup/storage': async (init) => {
				if (init?.method !== 'POST') return { body: STORAGE };
				await save.wait();
				return { body: { ilm_applied: true } };
			},
		});
		render(Page);
		await flush();
		await fireEvent.input(hotDays(), { target: { value: '120' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save retention settings' }));

		await fireEvent.click(tab('About'));
		await flush();
		expect(screen.getByText(BUSY_BAR)).toBeInTheDocument();
		expect(screen.getByText(BUSY_BAR).closest('.leave-bar')).toHaveFocus();
		expect(screen.queryByRole('button', { name: 'Discard and continue' })).not.toBeInTheDocument();
		expect(unload()).toBe(true);

		save.open();
		await flush();
		expect(screen.getByText('Retention settings saved and applied to OpenSearch.')).toBeInTheDocument();
		expect(screen.queryByText(BUSY_BAR)).not.toBeInTheDocument();
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
		// The bar had focus when it went: it goes back to the open tab
		expect(tab('Storage & retention')).toHaveFocus();

		await openTab('About');
		expect(panel()).toHaveAttribute('id', 'settings-panel-about');
	});

	// NET-358: a password change holds the switch and a reload until the server answers
	it('a password change holds the switch with no Discard until it lands', async () => {
		resetNavigation('http://localhost/settings?tab=account');
		const change = gate();
		stubFetch({
			'/api/account/password': async () => {
				await change.wait();
				return { body: { success: true } };
			},
		});
		render(Page);
		await flush();
		await fireEvent.input(screen.getByLabelText('Current password'), { target: { value: 'Old-Pass-1' } });
		await fireEvent.input(screen.getByLabelText('New password'), { target: { value: 'New-Pass-1' } });
		await fireEvent.input(screen.getByLabelText('Confirm new password'), { target: { value: 'New-Pass-1' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Change password' }));

		await fireEvent.click(tab('About'));
		await flush();
		expect(screen.getByText(BUSY_BAR)).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Discard and continue' })).not.toBeInTheDocument();
		expect(panel()).toHaveAttribute('id', 'settings-panel-account');
		expect(unload()).toBe(true);

		change.open();
		await flush();
		expect(screen.getByText(/^Password changed\./)).toBeInTheDocument();
		expect(screen.queryByText(BUSY_BAR)).not.toBeInTheDocument();
		expect(unload()).toBe(false);

		await openTab('About');
		expect(panel()).toHaveAttribute('id', 'settings-panel-about');
	});
});

describe('Settings hub — what does not hold navigation', () => {
	it('an edit typed while a save is sent stays unsaved', async () => {
		resetNavigation('http://localhost/settings?tab=retention');
		const save = gate();
		stubFetch({
			'/api/setup/storage': async (init) => {
				if (init?.method !== 'POST') return { body: STORAGE };
				await save.wait();
				return { body: { ilm_applied: true } };
			},
		});
		render(Page);
		await flush();
		await fireEvent.input(hotDays(), { target: { value: '120' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save retention settings' }));
		await fireEvent.input(hotDays(), { target: { value: '150' } });

		save.open();
		await flush();
		expect(screen.getByText('Retention settings saved and applied to OpenSearch.')).toBeInTheDocument();
		expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
		await fireEvent.click(tab('About'));
		expect(screen.getByText('You have unsaved changes in Storage & retention.')).toBeInTheDocument();
	});

	it('a rule update in flight does not hold a tab switch', async () => {
		resetNavigation('http://localhost/settings?tab=suricata-rules');
		const update = gate();
		stubFetch({
			'/api/suricata/rules/live': () => ({
				body: { available: true, enabled_rules: 1, disabled_rules: 0, last_updated: null, sources: [], schedule: '0 0 * * *', error: null },
			}),
			'/api/suricata/rules/custom': () => ({ body: { content: '', rule_count: 0, max_rules: 2000, max_bytes: 262144 } }),
			'/api/suricata/rules/commercial': () => ({ body: { configured: false, active: false, last_update_ok: null, applying: false, activation: null } }),
			'/api/suricata/rules/update': async () => {
				await update.wait();
				return { body: { success: true, output: '', reload_output: '' } };
			},
		});
		render(Page);
		await flush();
		await fireEvent.click(screen.getAllByRole('button', { name: 'Update rules now' })[0]);
		expect(screen.getAllByText('Updating…').length).toBeGreaterThan(0);

		await openTab('About');
		expect(panel()).toHaveAttribute('id', 'settings-panel-about');
		expect(screen.queryByText(BUSY_BAR)).not.toBeInTheDocument();
		update.open();
	});

	// NET-358: only a change being sent holds; a half-typed password is dropped on a switch
	it('a typed, unsent password does not hold a tab switch', async () => {
		resetNavigation('http://localhost/settings?tab=account');
		stubFetch();
		render(Page);
		await flush();
		await fireEvent.input(screen.getByLabelText('Current password'), { target: { value: 'Old-Pass-1' } });

		await openTab('About');
		expect(panel()).toHaveAttribute('id', 'settings-panel-about');
		expect(screen.queryByText(/You have unsaved changes/)).not.toBeInTheDocument();
	});

	it('the notification preferences loading does not hold a tab switch', async () => {
		const config = gate();
		stubFetch({
			'/api/notifications/config': async () => {
				await config.wait();
				return { body: { min_severity: 2, email: { enabled: false, recipients: [], smtp_configured: true }, webhook: { enabled: false } } };
			},
		});
		render(Page);
		await flush();

		await openTab('About');
		expect(panel()).toHaveAttribute('id', 'settings-panel-about');
		expect(screen.queryByText(BUSY_BAR)).not.toBeInTheDocument();
		config.open();
	});
});

// NET-365 / NET-367 (23 Nov QA): only what the user changed holds navigation
describe('Settings hub — untouched forms do not hold navigation', () => {
	const channelsCard = () => within(panel()).getByRole('heading', { name: 'Notification channels' }).closest('.card') as HTMLElement;
	const field = (id: string) => document.getElementById(id) as HTMLInputElement;

	it('a new channel cancelled and reopened with nothing typed does not hold a tab switch (NET-365)', async () => {
		stubFetch();
		render(Page);
		await flush();
		await fireEvent.click(within(channelsCard()).getByRole('button', { name: 'Add channel' }));
		await fireEvent.input(field('channel-name'), { target: { value: 'Ops Slack' } });
		await fireEvent.click(within(channelsCard()).getByRole('button', { name: 'Cancel' }));
		await fireEvent.click(within(channelsCard()).getByRole('button', { name: 'Add channel' }));

		await openTab('About');
		expect(panel()).toHaveAttribute('id', 'settings-panel-about');
		expect(screen.queryByText(/You have unsaved changes/)).not.toBeInTheDocument();
	});

	it('an SMTP port typed alone holds a tab switch, and Cancel lets it go (NET-365)', async () => {
		stubFetch();
		render(Page);
		await flush();
		await fireEvent.click(within(channelsCard()).getByRole('button', { name: 'Add channel' }));
		await fireEvent.change(field('channel-type'), { target: { value: 'email' } });
		await fireEvent.input(field('cfg-smtp_port'), { target: { value: '587' } });

		await fireEvent.click(tab('About'));
		expect(screen.getByText('You have unsaved changes in Notifications.')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
		await fireEvent.click(within(channelsCard()).getByRole('button', { name: 'Cancel' }));
		await fireEvent.click(within(channelsCard()).getByRole('button', { name: 'Add channel' }));

		await openTab('About');
		expect(panel()).toHaveAttribute('id', 'settings-panel-about');
	});

	it.each<[string, Record<string, Route>]>([
		[
			'integrations',
			{
				'/api/integrations/unifi/status': () => ({
					body: { configured: true, controller_url: 'https://192.168.1.1', site_id: 'default', connected: true, last_poll_time: 0, cache_counts: { clients: 0, devices: 0 }, last_error: null },
				}),
			},
		],
		['api-keys', { '/api/settings/api-keys': () => ({ body: { keys: { MAXMIND_LICENSE_KEY: true, SMTP_PASSWORD: true } } }) }],
		[
			'suricata-rules',
			{
				'/api/suricata/rules/live': () => ({
					body: { available: true, enabled_rules: 1, disabled_rules: 0, last_updated: null, sources: [], schedule: '0 0 * * *', error: null },
				}),
				'/api/suricata/rules/custom': () => ({ body: { content: '', rule_count: 0, max_rules: 2000, max_bytes: 262144 } }),
				'/api/suricata/rules/commercial': () => ({ body: { configured: true, active: true, last_update_ok: true, applying: false, activation: null } }),
			},
		],
	])("%s: every secret field is one Chrome's password manager never fills, and the loaded tab does not hold a switch (NET-367)", async (id, routes) => {
		resetNavigation(`http://localhost/settings?tab=${id}`);
		stubFetch(routes);
		render(Page);
		await flush();

		const secrets = Array.from(panel().querySelectorAll('input[type="password"]'));
		expect(secrets.length).toBeGreaterThan(0);
		for (const input of secrets) expect(input).toHaveAttribute('autocomplete', 'one-time-code');

		await openTab('About');
		expect(panel()).toHaveAttribute('id', 'settings-panel-about');
		expect(screen.queryByText(/You have unsaved changes/)).not.toBeInTheDocument();
	});
});

describe("Settings hub — the top bar's Refresh", () => {
	it.each([
		['Notifications', true],
		['Suricata rules', true],
		['Storage & retention', true],
		['About', true],
		['Capture', false],
		['Backup & restore', false],
		['Display', false],
	])('on %s: offered %s', async (name, offered) => {
		resetNavigation('http://localhost/settings?tab=network');
		stubFetch();
		render(Page);
		await flush();
		expect(get(pageRefresh).available).toBe(false);

		if (name !== 'Network') await openTab(name);
		expect(get(pageRefresh).available).toBe(offered);
	});

	it("a slow load from the tab just left never touches the open tab's indicator", async () => {
		resetNavigation('http://localhost/settings?tab=about');
		const health = gate();
		stubFetch({
			'/api/system/health': async () => {
				await health.wait();
				return { status: 503, body: {} };
			},
			'/api/storage/status': () => ({ body: { disk_usage_percent: 12 } }),
			'/api/setup/storage': () => ({ body: STORAGE }),
		});
		render(Page);
		await flush();
		expect(get(pageRefresh).running).toBe(true);

		await openTab('Storage & retention');
		const settled = get(pageRefresh);
		expect(settled).toMatchObject({ available: true, running: false, status: 'ok' });

		health.open();
		await flush();
		expect(get(pageRefresh)).toEqual(settled);
	});
});
