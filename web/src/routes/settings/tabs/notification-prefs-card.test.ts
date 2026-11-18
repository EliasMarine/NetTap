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

/** The daemon's settings: GET answers `config`, PUT answers what it was sent. */
function stubConfig(config: Record<string, unknown>) {
	const fn = vi.fn(async (_url: string, init?: RequestInit) => {
		const body = init?.method === 'PUT' ? { ...config, ...JSON.parse(String(init.body)) } : config;
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
