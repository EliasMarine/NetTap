import { describe, it, expect, vi, afterEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import DeviceCustomise from './DeviceCustomise.svelte';
import type { RegistryDevice } from '$api/devices-registry';
import { squarePicture } from '$lib/utils/device-picture';

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
