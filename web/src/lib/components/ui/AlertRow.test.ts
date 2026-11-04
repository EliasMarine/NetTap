import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import AlertRow from './AlertRow.svelte';
import { ICONS, type IconName } from './icons';

function iconMarkup(name: IconName): string {
	const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
	svg.innerHTML = ICONS[name];
	return svg.innerHTML;
}

const ALERT = {
	severity: 'high' as const,
	title: 'Kitchen iPad looked up a .su website',
	signature: 'ET DNS Query for .su TLD (Soviet Union) Often Malware Related',
	device: { name: 'Kitchen iPad', category: 'tablet' },
	count: 2,
	lastSeen: '21:05',
};

describe('AlertRow', () => {
	it('is one button on the six-column grid: severity, title over signature, device, count, time, chevron', () => {
		render(AlertRow, { ...ALERT, onselect: vi.fn() });
		const row = screen.getByRole('button');
		expect(row).toHaveClass('alert-row');
		expect(row.children).toHaveLength(6);
		expect(row.children[0]).toHaveClass('sev', 'sev-high');
		expect(row.querySelector('.alert-main > .alert-title')).toHaveTextContent(ALERT.title);
		const sig = row.querySelector('.alert-main > .sig')!;
		expect(sig).toHaveTextContent(ALERT.signature);
		expect(sig).toHaveAttribute('title', ALERT.signature);
		const who = row.children[2];
		expect(who).toHaveClass('who', 'hide-sm');
		expect(who.querySelector('svg')!.innerHTML).toBe(iconMarkup('tablet'));
		expect(who.querySelector('.trunc')).toHaveTextContent('Kitchen iPad');
		expect(row.children[3]).toHaveTextContent('×2');
		expect(row.children[4]).toHaveTextContent('21:05');
		expect(row.querySelectorAll('.hide-sm')).toHaveLength(3);
		expect(row.children[5]).toHaveClass('chev');
	});

	it('marks the open alert with aria-current', () => {
		const { unmount } = render(AlertRow, { ...ALERT, selected: true, onselect: vi.fn() });
		expect(screen.getByRole('button')).toHaveAttribute('aria-current', 'true');
		unmount();
		render(AlertRow, { ...ALERT, onselect: vi.fn() });
		expect(screen.getByRole('button')).toHaveAttribute('aria-current', 'false');
	});

	it('calls onselect once on click', async () => {
		const onselect = vi.fn();
		render(AlertRow, { ...ALERT, onselect });
		await fireEvent.click(screen.getByRole('button'));
		expect(onselect).toHaveBeenCalledOnce();
	});

	it('keeps the grid aligned when there is no device', () => {
		render(AlertRow, { ...ALERT, device: undefined, onselect: vi.fn() });
		const row = screen.getByRole('button');
		expect(row.children).toHaveLength(6);
		expect(row.children[2]).toHaveClass('hide-sm');
		expect(row.children[2]).toBeEmptyDOMElement();
	});
});
