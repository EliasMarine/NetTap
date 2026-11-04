import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import SeverityGauge from './SeverityGauge.svelte';
import { severityBuckets } from '$lib/utils/severity';

function draw(input: Parameters<typeof severityBuckets>[0]) {
	return render(SeverityGauge, {
		props: { buckets: severityBuckets(input), total: input.total, ariaLabel: `${input.total} alerts in the last 24 hours` },
	});
}

const classes = (container: HTMLElement) =>
	[...container.querySelectorAll('line.tick')].map((t) => [...t.classList].find((c) => c !== 'tick'));

describe('SeverityGauge', () => {
	it('draws 36 ticks coloured by severity share, in order', () => {
		const { container, getByRole } = draw({ total: 37, high: 10, medium: 15, low: 8 });
		expect(getByRole('img').getAttribute('aria-label')).toBe('37 alerts in the last 24 hours');
		const cls = classes(container);
		expect(cls).toHaveLength(36);
		expect(cls[0]).toBe('sevs-high');
		expect(cls.at(-1)).toBe('sevs-info');
		expect(cls.filter((c) => c === 'sevs-medium').length).toBeGreaterThan(cls.filter((c) => c === 'sevs-high').length);
		expect(cls).not.toContain('track');
		expect(container.querySelector('.d-num')?.textContent).toBe('37');
		expect(container.querySelector('.d-lbl')?.textContent).toBe('alerts');
		expect(container.innerHTML).not.toMatch(/NaN/);
	});

	it('gives a tiny severity at least one tick', () => {
		const cls = classes(draw({ total: 1001, high: 1, medium: 0, low: 1000 }).container);
		expect(cls.filter((c) => c === 'sevs-high')).toHaveLength(1);
	});

	it('draws 36 neutral ticks and a 0 for a zero total', () => {
		const { container } = draw({ total: 0, high: 0, medium: 0, low: 0 });
		expect(classes(container)).toEqual(Array(36).fill('track'));
		expect(container.querySelector('.d-num')?.textContent).toBe('0');
		expect(container.innerHTML).not.toMatch(/NaN/);
	});

	it('lists each level by word with its colour and count', () => {
		const { container } = draw({ total: 37, high: 10, medium: 15, low: 8, critical: 2 });
		const rows = [...container.querySelectorAll('.kv li')];
		expect(rows.map((r) => r.children[1].textContent)).toEqual(['Critical', 'High', 'Medium', 'Low', 'Info']);
		expect((rows[1].querySelector('.sw') as HTMLElement).style.getPropertyValue('--c')).toBe('var(--sev-high)');
		expect(rows[1].querySelector('b')?.textContent).toBe('10');
		expect(rows[1].querySelector('.pct')?.textContent).toBe('27%');
	});
});
