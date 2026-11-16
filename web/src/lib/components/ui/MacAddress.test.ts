import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import MacAddress from './MacAddress.svelte';

describe('MacAddress', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	it("shows the MAC, with no Private tag for a maker's address", () => {
		render(MacAddress, { mac: 'bc:24:11:00:00:01' });
		expect(screen.getByText('bc:24:11:00:00:01')).toBeInTheDocument();
		expect(screen.queryByText('Private')).not.toBeInTheDocument();
	});

	it('tags a MAC the device made up', () => {
		render(MacAddress, { mac: 'da:a1:19:00:00:01' });
		expect(screen.getByText('Private')).toHaveAttribute('title', expect.stringContaining('for privacy'));
	});

	it('copies the MAC and says so', async () => {
		const writeText = vi.fn().mockResolvedValue(undefined);
		vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
		render(MacAddress, { mac: 'bc:24:11:00:00:01' });
		await fireEvent.click(screen.getByRole('button', { name: 'Copy MAC address' }));
		expect(writeText).toHaveBeenCalledWith('bc:24:11:00:00:01');
		expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
		expect(screen.getByRole('status')).toHaveTextContent('Copied');
	});

	it('says "Copy failed" when neither the clipboard nor the fallback works', async () => {
		vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
		Object.defineProperty(document, 'execCommand', { value: vi.fn().mockReturnValue(false), configurable: true });
		render(MacAddress, { mac: 'bc:24:11:00:00:01' });
		await fireEvent.click(screen.getByRole('button', { name: 'Copy MAC address' }));
		expect(await screen.findByRole('button', { name: 'Copy failed' })).toBeInTheDocument();
		expect(document.execCommand).toHaveBeenCalledWith('copy');
	});

	it('falls back to the hidden textarea when there is no Clipboard API', async () => {
		vi.stubGlobal('navigator', { ...navigator, clipboard: undefined });
		Object.defineProperty(document, 'execCommand', { value: vi.fn().mockReturnValue(true), configurable: true });
		render(MacAddress, { mac: 'bc:24:11:00:00:01' });
		await fireEvent.click(screen.getByRole('button', { name: 'Copy MAC address' }));
		expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
	});
});
