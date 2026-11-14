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
const BUSY_BAR = 'Saving your changes… wait for this to finish before leaving the tab.';

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

		expect(goto).toHaveBeenCalledWith('?tab=capture', { keepFocus: true, noScroll: true });
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
		expect(panels).toHaveLength(10);
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
		expect(screen.getByText(BUSY_BAR)).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Discard and continue' })).not.toBeInTheDocument();
		expect(unload()).toBe(true);

		save.open();
		await flush();
		expect(screen.getByText('Retention settings saved and applied to OpenSearch.')).toBeInTheDocument();
		expect(screen.queryByText(BUSY_BAR)).not.toBeInTheDocument();
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();

		await openTab('About');
		expect(panel()).toHaveAttribute('id', 'settings-panel-about');
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
