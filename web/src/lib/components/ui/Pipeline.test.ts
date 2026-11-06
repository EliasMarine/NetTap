import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import Pipeline from './Pipeline.svelte';
import { ICONS, type IconName } from './icons';

function iconMarkup(name: IconName): string {
	const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
	svg.innerHTML = ICONS[name];
	return svg.innerHTML;
}

describe('Pipeline', () => {
	it('shows each stage with its state as icon, word and detail', () => {
		const { container } = render(Pipeline, {
			stages: [
				{ key: 'capture', label: 'Capture', status: 'ok', detail: 'Mirror on enp3s0 · no packet drops' },
				{ key: 'zeek', label: 'Zeek', status: 'failing', detail: 'No logs for 12 minutes' },
				{ key: 'storage', label: 'Storage', status: 'unknown', detail: 'Not checked yet' },
			],
		});
		const items = container.querySelectorAll('.pipe > .pipe-item');
		expect(items).toHaveLength(3);

		const healthy = screen.getByRole('img', { name: 'Healthy' });
		expect(healthy.innerHTML).toBe(iconMarkup('check'));
		expect(items[0].querySelector('.pipe-k')).toHaveTextContent('Capture');
		expect(items[0].querySelector('.pipe-k')).not.toHaveClass('is-failing');
		expect(items[0].querySelector('.pipe-v')).toHaveTextContent('Mirror on enp3s0 · no packet drops');

		const failing = screen.getByRole('img', { name: 'Failing' });
		expect(failing.innerHTML).toBe(iconMarkup('warn'));
		expect(items[1].querySelector('.pipe-k')).toHaveClass('is-failing');

		expect(screen.getByRole('img', { name: 'Unknown' }).innerHTML).toBe(iconMarkup('changelog'));
		expect(items[2].querySelector('.pipe-k')).toHaveClass('is-unknown');
	});

	it('shows a warning stage (NET-168) with its own class, never as failing or unknown', () => {
		const { container } = render(Pipeline, {
			stages: [{ key: 'system', label: 'System', status: 'warn', detail: "Incomplete · some checks couldn't run" }],
		});
		const key = container.querySelector('.pipe-k');
		expect(screen.getByRole('img', { name: 'Warning' }).innerHTML).toBe(iconMarkup('warn'));
		expect(key).toHaveClass('is-warn');
		expect(key).not.toHaveClass('is-failing');
		expect(key).not.toHaveClass('is-unknown');
	});
});
