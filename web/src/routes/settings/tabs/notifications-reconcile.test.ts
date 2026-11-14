/**
 * NET-273: the preferences card and the channel and rule lists edit the same "settings-*" records, so
 * the Notifications tab reloads one after the other changes, and runs every write one at a time.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import Tab from './NotificationsTab.svelte';

type Reply = { status?: number; body: unknown };

const SETTINGS_EMAIL = { id: 'settings-email', type: 'email', name: 'Email (Settings)', config: {} };
const DISCORD = { id: 'ch-discord', type: 'discord', name: 'Home Discord', config: {} };
const config = (emailOn: boolean) => ({
	min_severity: 2,
	email: { enabled: emailOn, recipients: emailOn ? ['a@example.com'] : [], smtp_configured: true },
	webhook: { enabled: false, has_url: false, url_hint: '' },
});

/**
 * A small daemon: the settings email channel exists while email is on. `configGate` holds the next
 * settings read until the test opens it; `configFails` makes settings reads answer 500.
 */
function stubDaemon() {
	const state = {
		emailOn: true,
		channels: [SETTINGS_EMAIL, DISCORD] as { id: string }[],
		configGate: null as Promise<void> | null,
		configFails: false,
	};
	const reply = ({ status = 200, body }: Reply) => ({ ok: status < 400, status, json: async () => body });
	const fn = vi.fn(async (url: string, init?: RequestInit) => {
		const method = init?.method ?? 'GET';
		if (url === '/api/notifications/config' && method === 'GET') {
			if (state.configGate) await state.configGate;
			return state.configFails ? reply({ status: 500, body: {} }) : reply({ body: config(state.emailOn) });
		}
		if (url === '/api/notifications/config' && method === 'PUT') {
			state.emailOn = JSON.parse(String(init?.body)).email.enabled;
			state.channels = state.emailOn ? [SETTINGS_EMAIL, DISCORD] : [DISCORD];
			return reply({ body: config(state.emailOn) });
		}
		if (url.startsWith('/api/notifications/channels/') && method === 'DELETE') {
			const id = url.split('/').pop();
			state.channels = state.channels.filter((c) => c.id !== id);
			if (id === 'settings-email') state.emailOn = false;
			return reply({ body: { deleted: id } });
		}
		if (url === '/api/notifications/channels') return reply({ body: { channels: state.channels, count: state.channels.length } });
		if (url === '/api/notifications/rules') return reply({ body: { rules: [], count: 0 } });
		if (url === '/api/notifications/log') return reply({ body: { log: [], count: 0 } });
		if (url === '/api/notifications/test' && method === 'POST') return reply({ body: { success: true } });
		return reply({ status: 500, body: {} });
	});
	vi.stubGlobal('fetch', fn);
	const calls = (path: string, method = 'GET') =>
		fn.mock.calls.filter(([url, init]) => url === path && (init?.method ?? 'GET') === method).length;
	return { state, calls };
}

function gate() {
	let open: () => void = () => {};
	const opened = new Promise<void>((resolve) => (open = resolve));
	return { opened, open };
}

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

const emailSwitch = () => screen.getByRole('switch', { name: 'Enable email alerts' });
const severity = () => screen.getByLabelText('Alert severity threshold');
const saveButton = () => screen.getByRole('button', { name: 'Save notification settings' });
const CONFLICT = 'Channels changed since you started editing these preferences.';

/** The Delete button on a channel's row. */
function deleteChannelButton(name: string) {
	const row = screen.getByText(name).closest('li') as HTMLElement;
	return within(row).getByRole('button', { name: 'Delete' });
}

async function openTab() {
	const daemon = stubDaemon();
	render(Tab);
	await flush();
	expect(emailSwitch()).toBeChecked();
	return daemon;
}

describe('Notifications tab — preferences and channels stay in step (NET-273)', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('a test send reloads Recent deliveries', async () => {
		const daemon = await openTab();
		const reads = daemon.calls('/api/notifications/log');

		await fireEvent.click(screen.getByRole('button', { name: 'Send test notification' }));
		await flush();
		expect(screen.getByText('Test notification sent successfully.')).toBeInTheDocument();
		expect(daemon.calls('/api/notifications/log')).toBe(reads + 1);
	});

	it('the first preferences load holds the lock, so no channel change runs under it', async () => {
		const daemon = stubDaemon();
		const first = gate();
		daemon.state.configGate = first.opened;
		render(Tab);
		await flush();
		expect(deleteChannelButton('Home Discord')).toBeDisabled();

		daemon.state.configGate = null;
		first.open();
		await flush();
		expect(deleteChannelButton('Home Discord')).toBeEnabled();
		expect(emailSwitch()).toBeChecked();
	});

	it('a preferences save reloads the channel list beside it', async () => {
		const { calls } = await openTab();
		expect(screen.getByText('Email (Settings)')).toBeInTheDocument();

		await fireEvent.click(emailSwitch());
		await fireEvent.click(saveButton());
		await flush();

		expect(calls('/api/notifications/channels')).toBe(2);
		expect(screen.queryByText('Email (Settings)')).not.toBeInTheDocument();
		expect(screen.getByText('1 channel')).toBeInTheDocument();
	});

	it('deleting the settings email channel turns a clean form’s email switch off', async () => {
		const { calls } = await openTab();

		await fireEvent.click(deleteChannelButton('Email (Settings)'));
		await flush();

		expect(calls('/api/notifications/config')).toBe(2);
		expect(emailSwitch()).not.toBeChecked();
		expect(screen.queryByText(CONFLICT)).not.toBeInTheDocument();
		expect(saveButton()).toBeEnabled();
	});

	it('an edited form keeps its edits after a channel change, but saving waits for a reload', async () => {
		const { calls } = await openTab();
		await fireEvent.change(severity(), { target: { value: 'medium' } });

		await fireEvent.click(deleteChannelButton('Email (Settings)'));
		await flush();

		expect(screen.getByText(CONFLICT)).toBeInTheDocument();
		expect(saveButton()).toBeDisabled();
		expect(severity()).toHaveValue('medium');
		expect(emailSwitch()).toBeChecked();
		expect(calls('/api/notifications/config')).toBe(1);

		await fireEvent.click(screen.getByRole('button', { name: 'Reload preferences' }));
		await flush();
		expect(screen.queryByText(CONFLICT)).not.toBeInTheDocument();
		expect(severity()).toHaveValue('high');
		expect(emailSwitch()).not.toBeChecked();
		expect(saveButton()).toBeEnabled();
	});

	it('nothing can be typed or changed while the reload after a channel change runs', async () => {
		const { state, calls } = await openTab();
		const held = gate();
		state.configGate = held.opened;

		await fireEvent.click(deleteChannelButton('Email (Settings)'));
		await flush();

		expect(severity()).toBeDisabled();
		expect(emailSwitch()).toBeDisabled();
		expect(saveButton()).toBeDisabled();
		const discordDelete = deleteChannelButton('Home Discord');
		expect(discordDelete).toBeDisabled();
		await fireEvent.click(discordDelete);
		expect(calls('/api/notifications/channels/ch-discord', 'DELETE')).toBe(0);

		held.open();
		state.configGate = null;
		await flush();
		expect(severity()).toBeEnabled();
		expect(emailSwitch()).not.toBeChecked();
		expect(deleteChannelButton('Home Discord')).toBeEnabled();
	});

	it('a failed reload keeps saving off and offers to try again', async () => {
		const { state } = await openTab();
		state.configFails = true;

		await fireEvent.click(deleteChannelButton('Email (Settings)'));
		await flush();

		expect(screen.getByText('Could not load the current notification settings, so saving is off.')).toBeInTheDocument();
		expect(saveButton()).toBeDisabled();

		state.configFails = false;
		await fireEvent.click(screen.getByRole('button', { name: 'Reload preferences' }));
		await flush();
		expect(screen.queryByText(/Could not load the current notification settings/)).not.toBeInTheDocument();
		expect(saveButton()).toBeEnabled();
	});

});
