import { describe, it, expect, vi, afterEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import DeviceCustomise from './DeviceCustomise.svelte';
import type { RegistryDevice } from '$api/devices-registry';
import { squarePicture } from '$lib/utils/device-picture';
import { captureMode } from '$lib/stores/captureMode';
import { WATCH_BRIDGE_NOTE } from '$api/devices-watched';

vi.mock('$lib/utils/device-picture', () => ({ squarePicture: vi.fn() }));

const device = (over: Partial<RegistryDevice> = {}): RegistryDevice => ({
	mac: 'D0:21:F9:5E:35:32',
	ips: ['192.168.1.1'],
	hostnames: [],
	manufacturer: 'Ubiquiti Inc',
	friendly_name: null,
	display_name: 'Ubiquiti gateway',
	discovered_name: 'Ubiquiti gateway',
	custom_name: null,
	icon: null,
	picture: null,
	category: 'infrastructure',
	first_seen: '2026-11-01T00:00:00Z',
	last_seen: '2026-11-02T00:00:00Z',
	is_new: false,
	...over,
});

/** The page's save: runs the action for the device's MAC, like the MAC page does. */
function pageSave(mac = 'D0:21:F9:5E:35:32') {
	return vi.fn(async (action: (m: string) => Promise<RegistryDevice>) => {
		await action(mac);
	});
}

function daemon(reply: () => Promise<unknown>) {
	const fetchMock = vi.fn(reply);
	vi.stubGlobal('fetch', fetchMock);
	return fetchMock;
}

const ok = (body: unknown) => async () => ({ ok: true, status: 200, json: async () => body });

describe('DeviceCustomise', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('starts with both panels closed', () => {
		render(DeviceCustomise, { device: device(), onsave: pageSave() });
		expect(screen.getByRole('button', { name: 'Rename' })).toHaveAttribute('aria-expanded', 'false');
		expect(screen.getByRole('button', { name: 'Change picture' })).toHaveAttribute('aria-expanded', 'false');
		expect(screen.queryByLabelText('Name')).not.toBeInTheDocument();
	});

	it('fills the name box with the current name, and Cancel closes it without saving', async () => {
		const onsave = pageSave();
		render(DeviceCustomise, { device: device({ custom_name: 'Office router' }), onsave });
		await fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
		expect(screen.getByLabelText('Name')).toHaveValue('Office router');
		expect(screen.getByLabelText('Name')).toHaveAttribute('maxlength', '64');
		await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
		expect(screen.queryByLabelText('Name')).not.toBeInTheDocument();
		expect(onsave).not.toHaveBeenCalled();
	});

	it('refuses a blank name without asking the daemon', async () => {
		const fetchMock = daemon(ok({}));
		render(DeviceCustomise, { device: device(), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
		await fireEvent.input(screen.getByLabelText('Name'), { target: { value: '   ' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
		expect(screen.getByRole('alert')).toHaveTextContent('Enter a name, or cancel.');
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it('offers the discovered name back only when the owner has named it', async () => {
		const fetchMock = daemon(ok({ device: device() }));
		const { unmount } = render(DeviceCustomise, { device: device(), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
		expect(screen.queryByRole('button', { name: 'Use the discovered name' })).not.toBeInTheDocument();
		unmount();

		render(DeviceCustomise, { device: device({ custom_name: 'Office router' }), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Use the discovered name' }));
		await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/devices/registry/D0%3A21%3AF9%3A5E%3A35%3A32/name', { method: 'DELETE' }));
	});

	it('saves a picked icon, pressed in the grid and shown in the preview', async () => {
		const fetchMock = daemon(ok({ device: device({ icon: 'printer' }) }));
		const { container } = render(DeviceCustomise, { device: device(), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Change picture' }));
		expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled(); // nothing chosen yet
		const printer = screen.getByRole('button', { name: 'Printer' });
		await fireEvent.click(printer);
		expect(printer).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByRole('button', { name: 'TV' })).toHaveAttribute('aria-pressed', 'false');
		expect(container.querySelector('.pic-preview .tile svg')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
		await vi.waitFor(() =>
			expect(fetchMock).toHaveBeenCalledWith(
				'/api/devices/registry/D0%3A21%3AF9%3A5E%3A35%3A32/picture',
				expect.objectContaining({ method: 'PUT', body: '{"icon":"printer"}' }),
			),
		);
	});

	it('offers Reset to default only when the device has an icon or photo', async () => {
		const { unmount } = render(DeviceCustomise, { device: device(), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Change picture' }));
		expect(screen.queryByRole('button', { name: 'Reset to default' })).not.toBeInTheDocument();
		unmount();
		const fetchMock = daemon(ok({ device: device() }));
		render(DeviceCustomise, { device: device({ picture: '/api/devices/registry/D0:21:F9:5E:35:32/picture?v=0123456789abcdef' }), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Change picture' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Reset to default' }));
		await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/devices/registry/D0%3A21%3AF9%3A5E%3A35%3A32/picture', { method: 'DELETE' }));
		expect(await screen.findByText('Picture reset.')).toBeInTheDocument();
	});

	it('says why a photo was refused, before any upload', async () => {
		vi.mocked(squarePicture).mockRejectedValueOnce(new Error('Choose a PNG, JPEG or WebP picture.'));
		const fetchMock = daemon(ok({}));
		render(DeviceCustomise, { device: device(), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Change picture' }));
		const input = screen.getByLabelText('Or upload a photo') as HTMLInputElement;
		expect(input).toHaveAttribute('accept', 'image/png,image/jpeg,image/webp');
		await fireEvent.change(input, { target: { files: [new File(['<svg/>'], 'logo.svg', { type: 'image/svg+xml' })] } });
		expect(await screen.findByRole('alert')).toHaveTextContent('Choose a PNG, JPEG or WebP picture.');
		expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it('keeps an earlier choice when a later file is refused', async () => {
		vi.mocked(squarePicture).mockRejectedValueOnce(new Error('Choose a picture smaller than 10 MB.'));
		render(DeviceCustomise, { device: device(), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Change picture' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Printer' }));
		await fireEvent.change(screen.getByLabelText('Or upload a photo'), { target: { files: [new File(['x'], 'big.png', { type: 'image/png' })] } });
		expect(await screen.findByRole('alert')).toHaveTextContent('Choose a picture smaller than 10 MB.');
		expect(screen.getByRole('button', { name: 'Printer' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
	});

	it('previews an uploaded photo and saves it as the image', async () => {
		vi.mocked(squarePicture).mockResolvedValueOnce('data:image/webp;base64,UklGRg==');
		const fetchMock = daemon(ok({ device: device({ picture: '/api/devices/registry/D0:21:F9:5E:35:32/picture?v=0123456789abcdef' }) }));
		const { container } = render(DeviceCustomise, { device: device(), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Change picture' }));
		await fireEvent.change(screen.getByLabelText('Or upload a photo'), { target: { files: [new File(['x'], 'tv.jpg', { type: 'image/jpeg' })] } });
		await vi.waitFor(() => expect(container.querySelector('.pic-preview .tile img')).toHaveAttribute('src', 'data:image/webp;base64,UklGRg=='));
		expect(screen.getByText('Preview')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
		await vi.waitFor(() =>
			expect(fetchMock).toHaveBeenCalledWith(
				'/api/devices/registry/D0%3A21%3AF9%3A5E%3A35%3A32/picture',
				expect.objectContaining({ method: 'PUT', body: '{"image":"data:image/webp;base64,UklGRg=="}' }),
			),
		);
		expect(await screen.findByText('Picture saved.')).toBeInTheDocument();
	});

	it('locks the icons while a photo is being read', async () => {
		let finish: (url: string) => void = () => {};
		vi.mocked(squarePicture).mockImplementationOnce(() => new Promise((resolve) => (finish = resolve)));
		render(DeviceCustomise, { device: device(), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Change picture' }));
		await fireEvent.change(screen.getByLabelText('Or upload a photo'), { target: { files: [new File(['x'], 'tv.jpg', { type: 'image/jpeg' })] } });
		expect(screen.getByRole('button', { name: 'Printer' })).toBeDisabled();
		finish('data:image/webp;base64,AAAA');
		await vi.waitFor(() => expect(screen.getByRole('button', { name: 'Printer' })).toBeEnabled());
	});

	it('shows the saved icon as pressed until something new is chosen', async () => {
		render(DeviceCustomise, { device: device({ icon: 'tv' }), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Change picture' }));
		expect(screen.getByRole('button', { name: 'TV' })).toHaveAttribute('aria-pressed', 'true');
		await fireEvent.click(screen.getByRole('button', { name: 'Printer' }));
		expect(screen.getByRole('button', { name: 'TV' })).toHaveAttribute('aria-pressed', 'false');
	});

	it('presses no icon while a photo is the saved picture', async () => {
		render(DeviceCustomise, { device: device({ icon: 'tv', picture: '/p?v=1' }), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Change picture' }));
		expect(screen.getByRole('button', { name: 'TV' })).toHaveAttribute('aria-pressed', 'false');
	});

	it('points aria-controls at a panel only while it is open', async () => {
		render(DeviceCustomise, { device: device(), onsave: pageSave() });
		const rename = screen.getByRole('button', { name: 'Rename' });
		expect(rename).not.toHaveAttribute('aria-controls');
		await fireEvent.click(rename);
		expect(rename).toHaveAttribute('aria-controls', 'device-name-panel');
		expect(document.getElementById('device-name-panel')).toBeInTheDocument();
	});

	it('returns focus to the button that opened the panel, and announces the save', async () => {
		daemon(ok({ device: device({ custom_name: 'Office router' }) }));
		render(DeviceCustomise, { device: device(), onsave: pageSave() });
		const rename = screen.getByRole('button', { name: 'Rename' });
		await fireEvent.click(rename);
		await fireEvent.input(screen.getByLabelText('Name'), { target: { value: 'Office router' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
		await vi.waitFor(() => expect(rename).toHaveFocus());
		expect(screen.getByRole('status')).toHaveTextContent('Name saved.');
	});

	it('returns focus on Cancel too', async () => {
		render(DeviceCustomise, { device: device(), onsave: pageSave() });
		const change = screen.getByRole('button', { name: 'Change picture' });
		await fireEvent.click(change);
		await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
		await vi.waitFor(() => expect(change).toHaveFocus());
	});

	it('disables every button while a save is in flight', async () => {
		let finish: () => void = () => {};
		const onsave = vi.fn(() => new Promise<void>((resolve) => (finish = resolve)));
		render(DeviceCustomise, { device: device(), onsave });
		await fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
		await fireEvent.input(screen.getByLabelText('Name'), { target: { value: 'Office router' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
		expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();
		expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
		expect(screen.getByRole('button', { name: 'Change picture' })).toBeDisabled();
		await fireEvent.click(screen.getByRole('button', { name: 'Saving…' }));
		expect(onsave).toHaveBeenCalledTimes(1);
		finish();
	});

	it('warns that a randomised MAC may not keep the name', async () => {
		const { unmount } = render(DeviceCustomise, { device: device(), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
		expect(screen.queryByText(/private \(randomised\) MAC address/)).not.toBeInTheDocument();
		unmount();
		render(DeviceCustomise, { device: device({ mac: 'DA:A1:19:00:00:01' }), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
		expect(screen.getByText(/private \(randomised\) MAC address/)).toBeInTheDocument();
	});
});

// NET-331: Watch, a third panel beside Rename and Change picture
describe('DeviceCustomise — Watch (NET-331)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		captureMode.set(null);
	});

	const watchBox = () => screen.getByLabelText('Tell me when it goes quiet for') as HTMLSelectElement;
	const DETAILS = '/api/devices/registry/D0%3A21%3AF9%3A5E%3A35%3A32/details';

	it('offers Off and the five watch times, starting at the saved one', async () => {
		render(DeviceCustomise, { device: device({ watch_after_min: 60 }), onsave: pageSave() });
		const button = screen.getByRole('button', { name: 'Watch' });
		expect(button).toHaveAttribute('aria-expanded', 'false');
		await fireEvent.click(button);
		expect(button).toHaveAttribute('aria-expanded', 'true');
		expect(Array.from(watchBox().options).map((o) => o.textContent)).toEqual(['Off', '15 minutes', '30 minutes', '1 hour', '4 hours', '1 day']);
		expect(watchBox().selectedOptions[0]).toHaveTextContent('1 hour');
		expect(watchBox()).not.toHaveAttribute('aria-invalid');
		expect(screen.getByText(/at least twice its longest quiet spell/)).toBeInTheDocument();
	});

	it('starts at Off for a device that is not watched', async () => {
		render(DeviceCustomise, { device: device(), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Watch' }));
		expect(watchBox().selectedOptions[0]).toHaveTextContent('Off');
	});

	// review L5: only the five times the daemon allows count as a saved value
	it('starts at Off for a saved value the daemon does not allow', async () => {
		render(DeviceCustomise, { device: device({ watch_after_min: 45 }), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Watch' }));
		expect(watchBox().selectedOptions[0]).toHaveTextContent('Off');
	});

	// review M1 (plan §4): one long connection can look silent between log entries
	it('says a device with one long connection needs a longer time too', async () => {
		render(DeviceCustomise, { device: device(), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Watch' }));
		expect(screen.getByText(/hold one long connection open \(a camera stream, a backup\), need longer/)).toBeInTheDocument();
	});

	// security review: a watch can't tell the device from one copying its MAC
	it('says the watch reports silence, not tampering', async () => {
		render(DeviceCustomise, { device: device(), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Watch' }));
		expect(screen.getByText(/It reports silence, not tampering: another device on your network can pretend to be this one\./)).toBeInTheDocument();
	});

	// review L4: the page needs to know the save edits the strict details route
	it("tells the page the watch edits the device's details", async () => {
		daemon(ok({ device: device({ watch_after_min: 30 }) }));
		const onsave = pageSave();
		render(DeviceCustomise, { device: device(), onsave });
		await fireEvent.click(screen.getByRole('button', { name: 'Watch' }));
		await fireEvent.change(watchBox(), { target: { value: watchBox().options[2].value } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
		await vi.waitFor(() => expect(onsave).toHaveBeenCalledWith(expect.any(Function), 'details'));
	});

	it('hides Watch when the page has no MAC to save a watch by, keeping Rename and Change picture', () => {
		render(DeviceCustomise, { device: device(), onsave: pageSave(), watchable: false });
		expect(screen.queryByRole('button', { name: 'Watch' })).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Rename' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Change picture' })).toBeInTheDocument();
	});

	it('saves the picked time through the page, with only watch_after_min, then closes and announces it', async () => {
		const fetchMock = daemon(ok({ device: device({ watch_after_min: 240 }) }));
		const onsave = pageSave();
		render(DeviceCustomise, { device: device(), onsave });
		const button = screen.getByRole('button', { name: 'Watch' });
		await fireEvent.click(button);
		await fireEvent.change(watchBox(), { target: { value: watchBox().options[4].value } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
		await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledWith(DETAILS, expect.objectContaining({ method: 'PUT', body: '{"watch_after_min":240}' })));
		expect(onsave).toHaveBeenCalledTimes(1);
		expect(await screen.findByText('Watch saved.')).toBeInTheDocument();
		await vi.waitFor(() => expect(button).toHaveFocus());
		expect(screen.queryByLabelText('Tell me when it goes quiet for')).not.toBeInTheDocument();
	});

	it('turns the watch off with null', async () => {
		const fetchMock = daemon(ok({ device: device({ watch_after_min: null }) }));
		render(DeviceCustomise, { device: device({ watch_after_min: 15 }), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Watch' }));
		await fireEvent.change(watchBox(), { target: { value: watchBox().options[0].value } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
		await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledWith(DETAILS, expect.objectContaining({ body: '{"watch_after_min":null}' })));
		expect(await screen.findByText('Watch turned off.')).toBeInTheDocument();
	});

	it("keeps the panel open with the daemon's reason when the save is refused", async () => {
		daemon(async () => ({ ok: false, status: 409, json: async () => ({ error: 'You can watch at most 50 devices.' }) }));
		render(DeviceCustomise, { device: device(), onsave: pageSave() });
		await fireEvent.click(screen.getByRole('button', { name: 'Watch' }));
		await fireEvent.change(watchBox(), { target: { value: watchBox().options[1].value } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
		expect(await screen.findByRole('alert')).toHaveTextContent('You can watch at most 50 devices.');
		expect(watchBox()).toBeInTheDocument();
		// review L6
		expect(watchBox()).toHaveAttribute('aria-invalid', 'true');
		expect(watchBox()).toHaveAttribute('aria-describedby', 'device-watch-help device-watch-error');
	});

	it('warns that a randomised MAC change reads as offline', async () => {
		render(DeviceCustomise, { device: device({ mac: '02:21:F9:5E:35:32' }), onsave: pageSave('02:21:F9:5E:35:32') });
		await fireEvent.click(screen.getByRole('button', { name: 'Watch' }));
		expect(screen.getByRole('note')).toHaveTextContent('will report the device offline');
	});

	it('hides Watch in bridge mode and says why, keeping Rename and Change picture', async () => {
		captureMode.set('bridge');
		render(DeviceCustomise, { device: device({ watch_after_min: 60 }), onsave: pageSave() });
		expect(screen.queryByRole('button', { name: 'Watch' })).not.toBeInTheDocument();
		expect(screen.getByText(WATCH_BRIDGE_NOTE)).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Rename' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Change picture' })).toBeInTheDocument();
	});

	it('shows Watch in mirror mode and while the mode is unknown', async () => {
		captureMode.set('mirror');
		const { unmount } = render(DeviceCustomise, { device: device(), onsave: pageSave() });
		expect(screen.getByRole('button', { name: 'Watch' })).toBeInTheDocument();
		expect(screen.queryByText(WATCH_BRIDGE_NOTE)).not.toBeInTheDocument();
		unmount();
		captureMode.set('unknown');
		render(DeviceCustomise, { device: device(), onsave: pageSave() });
		expect(screen.getByRole('button', { name: 'Watch' })).toBeInTheDocument();
	});
});
