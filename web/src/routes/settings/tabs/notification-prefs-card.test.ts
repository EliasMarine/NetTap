/**
 * NET-319: the preferences card's "Tell me about new devices" switch loads from the daemon's settings
 * (absent reads as on), counts as an unsaved change, and is saved with the rest.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import Card from './NotificationPrefsCard.svelte';

const CONFIG = {
	min_severity: 2,
	email: { enabled: false, recipients: [], smtp_configured: true },
	webhook: { enabled: true, has_url: true, url_hint: 'hooks.example.com' },
};

/** The daemon's settings: GET answers `config`, PUT answers what it was sent (plus `putReply`, what only the reply carries). */
// OLD CODE: function stubConfig(config: Record<string, unknown>) { (F8: a PUT reply can differ from the GET, as the time zone can)
function stubConfig(config: Record<string, unknown>, putReply: Record<string, unknown> = {}) {
	const fn = vi.fn(async (_url: string, init?: RequestInit) => {
		const body = init?.method === 'PUT' ? { ...config, ...JSON.parse(String(init.body)), ...putReply } : config;
		return { ok: true, status: 200, json: async () => body };
	});
	vi.stubGlobal('fetch', fn);
	return fn;
}

function renderCard() {
	return render(Card, {
		locked: false,
		run: async (task: () => Promise<void>) => task(),
		onsaved: async () => {},
	});
}

const newDeviceSwitch = () => screen.getByRole('switch', { name: 'Tell me about new devices' });
// The switch starts on, so wait for something only the loaded settings show: CONFIG's webhook is on
const loaded = () => screen.findByLabelText('Webhook URL');

describe('Notification preferences: new devices (NET-319)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('loads the saved setting', async () => {
		stubConfig({ ...CONFIG, new_device: false });
		renderCard();
		await loaded();

		expect(newDeviceSwitch()).not.toBeChecked();
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
	});

	it('reads a config that never set it as on', async () => {
		stubConfig(CONFIG);
		renderCard();
		await loaded();

		expect(newDeviceSwitch()).toBeChecked();
	});

	it('marks the form unsaved when switched, and saves it in the PUT body', async () => {
		const fn = stubConfig({ ...CONFIG, new_device: true });
		renderCard();
		await loaded();
		expect(newDeviceSwitch()).toBeChecked();

		await fireEvent.click(newDeviceSwitch());
		expect(screen.getByText('Unsaved changes')).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Save notification settings' }));

		await screen.findByText('Notification settings saved.');
		const put = fn.mock.calls.find(([, init]) => init?.method === 'PUT');
		expect(JSON.parse(String(put?.[1]?.body))).toMatchObject({ new_device: false });
		expect(newDeviceSwitch()).not.toBeChecked();
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
	});
});

// F6 (NET-339): "Tell me when I near my data cap" is on by default and saved as `data_cap`, beside `new_device`
const dataCapSwitch = () => screen.getByRole('switch', { name: 'Tell me when I near my data cap' });

describe('Notification preferences: data cap warnings (F6)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('loads the saved setting', async () => {
		stubConfig({ ...CONFIG, data_cap: false });
		renderCard();
		await loaded();

		expect(dataCapSwitch()).not.toBeChecked();
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
	});

	it('reads a config that never set it as on', async () => {
		stubConfig(CONFIG);
		renderCard();
		await loaded();

		expect(dataCapSwitch()).toBeChecked();
	});

	it('links to where the cap is set', async () => {
		stubConfig(CONFIG);
		renderCard();
		await loaded();

		expect(screen.getByRole('link', { name: 'Network tab' })).toHaveAttribute('href', '?tab=network');
	});

	it('marks the form unsaved when switched, and saves it in the same PUT as new devices', async () => {
		const fn = stubConfig({ ...CONFIG, new_device: true, data_cap: true });
		renderCard();
		await loaded();

		await fireEvent.click(dataCapSwitch());
		expect(screen.getByText('Unsaved changes')).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Save notification settings' }));

		await screen.findByText('Notification settings saved.');
		const puts = fn.mock.calls.filter(([, init]) => init?.method === 'PUT');
		expect(puts).toHaveLength(1);
		expect(JSON.parse(String(puts[0][1]?.body))).toMatchObject({ new_device: true, data_cap: false });
		expect(dataCapSwitch()).not.toBeChecked();
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
	});
});

// F8 (NET-330): quiet hours: a switch, From and To times, "Critical alerts come through", and the zone they are read in
const QUIET_ON = { enabled: true, start: '23:00', end: '06:30', critical_through: false };
const quietSwitch = () => screen.getByRole('switch', { name: 'Hold notifications overnight' });
const criticalSwitch = () => screen.getByRole('switch', { name: 'Critical alerts come through' });
const fromTime = () => screen.getByLabelText('From') as HTMLInputElement;
const toTime = () => screen.getByLabelText('To') as HTMLInputElement;
const saveButton = () => screen.getByRole('button', { name: 'Save notification settings' });
const setTime = (el: HTMLElement, value: string) => fireEvent.input(el, { target: { value } });
const putBodies = (fn: ReturnType<typeof stubConfig>) =>
	fn.mock.calls.filter(([, init]) => init?.method === 'PUT').map(([, init]) => JSON.parse(String(init?.body)));

describe('Notification preferences: quiet hours (F8)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('loads the saved window and names the time zone', async () => {
		stubConfig({ ...CONFIG, quiet: QUIET_ON, tz: 'Europe/London' });
		renderCard();
		await loaded();

		expect(quietSwitch()).toBeChecked();
		expect(fromTime()).toHaveValue('23:00');
		expect(toTime()).toHaveValue('06:30');
		expect(criticalSwitch()).not.toBeChecked();
		expect(screen.getByText(/Europe\/London/)).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Display tab' })).toHaveAttribute('href', '?tab=display');
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
	});

	it('reads a daemon that never sent quiet hours as off, with the default window once switched on', async () => {
		stubConfig(CONFIG);
		renderCard();
		await loaded();

		expect(quietSwitch()).not.toBeChecked();
		await fireEvent.click(quietSwitch());
		expect(fromTime()).toHaveValue('22:00');
		expect(toTime()).toHaveValue('07:00');
		expect(criticalSwitch()).toBeChecked();
	});

	it('shows the times only while the switch is on', async () => {
		stubConfig({ ...CONFIG, quiet: { ...QUIET_ON, enabled: false } });
		renderCard();
		await loaded();

		expect(screen.queryByLabelText('From')).not.toBeInTheDocument();
		expect(screen.queryByRole('switch', { name: 'Critical alerts come through' })).not.toBeInTheDocument();

		await fireEvent.click(quietSwitch());
		expect(fromTime()).toBeInTheDocument();
		expect(toTime()).toBeInTheDocument();
		expect(criticalSwitch()).toBeInTheDocument();

		await fireEvent.click(quietSwitch());
		expect(screen.queryByLabelText('From')).not.toBeInTheDocument();
	});

	it('saves the window in the PUT body', async () => {
		const fn = stubConfig({ ...CONFIG, quiet: { ...QUIET_ON, enabled: false } });
		renderCard();
		await loaded();

		await fireEvent.click(quietSwitch());
		await setTime(fromTime(), '21:15');
		await setTime(toTime(), '05:45');
		await fireEvent.click(criticalSwitch());
		await fireEvent.click(saveButton());

		await screen.findByText('Notification settings saved.');
		expect(putBodies(fn)).toHaveLength(1);
		// QUIET_ON starts with critical alerts held back, so the one click turned them through
		expect(putBodies(fn)[0].quiet).toEqual({ enabled: true, start: '21:15', end: '05:45', critical_through: true });
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
	});

	it('marks the form unsaved when a time changes, and locks the test send until it is saved', async () => {
		stubConfig({ ...CONFIG, quiet: QUIET_ON });
		renderCard();
		await loaded();
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();

		await setTime(toTime(), '07:30');
		expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Send test notification' })).toBeDisabled();

		await setTime(toTime(), '06:30');
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
	});

	it('marks the form unsaved when only "Critical alerts come through" changes', async () => {
		stubConfig({ ...CONFIG, quiet: QUIET_ON });
		renderCard();
		await loaded();

		await fireEvent.click(criticalSwitch());
		expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
	});

	it('refuses From equal to To: an inline error and Save is off', async () => {
		const fn = stubConfig({ ...CONFIG, quiet: QUIET_ON });
		renderCard();
		await loaded();
		expect(saveButton()).toBeEnabled();

		await setTime(toTime(), '23:00');

		expect(screen.getByRole('alert')).toHaveTextContent('From and To must be different times.');
		expect(toTime()).toHaveAttribute('aria-invalid', 'true');
		expect(saveButton()).toBeDisabled();
		// OLD CODE: a PUT count with no click, which passed whatever Save's state (two-angle review).
		// button.click() is ignored on a disabled button, as in a browser (fireEvent.click isn't)
		saveButton().click();
		await new Promise((r) => setTimeout(r));
		expect(putBodies(fn)).toHaveLength(0);

		await setTime(toTime(), '07:00');
		expect(screen.queryByRole('alert')).not.toBeInTheDocument();
		expect(saveButton()).toBeEnabled();
	});

	it('refuses a cleared time field', async () => {
		stubConfig({ ...CONFIG, quiet: QUIET_ON });
		renderCard();
		await loaded();

		await setTime(fromTime(), '');

		expect(screen.getByRole('alert')).toHaveTextContent('Choose both times.');
		expect(saveButton()).toBeDisabled();
		expect(fromTime()).toHaveAttribute('aria-invalid', 'true');
		expect(toTime()).not.toHaveAttribute('aria-invalid');
		expect(screen.getByRole('group', { name: 'Hold notifications overnight' })).toContainElement(fromTime());
	});

	it('lets an invalid draft be switched off and saved with the last saved times', async () => {
		const fn = stubConfig({ ...CONFIG, quiet: QUIET_ON });
		renderCard();
		await loaded();

		await setTime(toTime(), '23:00');
		expect(saveButton()).toBeDisabled();

		await fireEvent.click(quietSwitch());
		expect(screen.queryByRole('alert')).not.toBeInTheDocument();
		expect(saveButton()).toBeEnabled();
		await fireEvent.click(saveButton());

		await screen.findByText('Notification settings saved.');
		expect(putBodies(fn)[0].quiet).toEqual({ enabled: false, start: '23:00', end: '06:30', critical_through: false });
	});

	it('says the times are in UTC when the owner never set a zone', async () => {
		stubConfig({ ...CONFIG, quiet: QUIET_ON, tz: 'UTC', tz_set: false });
		renderCard();
		await loaded();

		expect(screen.getByText(/You haven't set a time zone yet, so times are in UTC/)).toBeInTheDocument();
		expect(screen.queryByText(/Times are in your time zone/)).not.toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Display tab' })).toHaveAttribute('href', '?tab=display');
	});

	it('keeps naming the zone after a save, from the reply rather than the first load', async () => {
		// the owner changed the zone in Display after this form loaded; the PUT reply carries the current one
		stubConfig({ ...CONFIG, quiet: QUIET_ON, tz: 'Europe/London' }, { tz: 'America/New_York' });
		renderCard();
		await loaded();
		expect(screen.getByText(/Europe\/London/)).toBeInTheDocument();

		await setTime(toTime(), '07:00');
		await fireEvent.click(saveButton());

		await screen.findByText('Notification settings saved.');
		expect(screen.getByText(/America\/New_York/)).toBeInTheDocument();
		expect(screen.queryByText(/Europe\/London/)).not.toBeInTheDocument();
		expect(toTime()).toHaveValue('07:00');
	});

	it("shows the daemon's reason when it refuses the window", async () => {
		const fn = vi.fn(async (_url: string, init?: RequestInit) =>
			init?.method === 'PUT'
				? { ok: false, status: 400, json: async () => ({ error: 'quiet: start and end must differ' }) }
				: { ok: true, status: 200, json: async () => ({ ...CONFIG, quiet: QUIET_ON, tz: 'UTC' }) },
		);
		vi.stubGlobal('fetch', fn);
		renderCard();
		await loaded();

		await setTime(toTime(), '07:00');
		await fireEvent.click(saveButton());

		expect(await screen.findByText('quiet: start and end must differ')).toBeInTheDocument();
		expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
	});
});

// NET-331: "Tell me when a watched device goes offline or comes back" is on by default and saved as `watched_device`
const watchedSwitch = () => screen.getByRole('switch', { name: 'Tell me when a watched device goes offline or comes back' });

describe('Notification preferences: watched devices (NET-331)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('loads the saved setting', async () => {
		stubConfig({ ...CONFIG, watched_device: false });
		renderCard();
		await loaded();

		expect(watchedSwitch()).not.toBeChecked();
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
	});

	it('reads a config that never set it as on', async () => {
		stubConfig(CONFIG);
		renderCard();
		await loaded();

		expect(watchedSwitch()).toBeChecked();
	});

	it('marks the form unsaved when switched, and saves it in the same PUT as the others', async () => {
		const fn = stubConfig({ ...CONFIG, new_device: true, data_cap: true, watched_device: true });
		renderCard();
		await loaded();

		await fireEvent.click(watchedSwitch());
		expect(screen.getByText('Unsaved changes')).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Save notification settings' }));

		await screen.findByText('Notification settings saved.');
		const puts = fn.mock.calls.filter(([, init]) => init?.method === 'PUT');
		expect(puts).toHaveLength(1);
		expect(JSON.parse(String(puts[0][1]?.body))).toMatchObject({ new_device: true, data_cap: true, watched_device: false });
		expect(watchedSwitch()).not.toBeChecked();
		expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
	});
});
