import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import SeverityPill from './SeverityPill.svelte';
import type { SeverityLevel } from '$lib/utils/severity';

const SHAPES: [SeverityLevel, string, string][] = [
	['critical', 'Critical', 'path[d="M5 .5 9.5 5 5 9.5.5 5z"]'],
	['high', 'High', 'path[d="M5 1 9.4 9H.6z"]'],
	['medium', 'Medium', 'rect[rx="1.5"]'],
	['low', 'Low', 'circle[r="4"]:not(.hollow)'],
	['info', 'Info', 'circle.hollow[r="3.4"]'],
];

describe('SeverityPill', () => {
	it.each(SHAPES)('%s shows its colour class, shape and word', (level, word, shape) => {
		const { container } = render(SeverityPill, { level });
		const pill = container.querySelector('span.sev')!;
		expect(pill).toHaveClass(`sev-${level}`);
		expect(pill).toHaveTextContent(word);
		const svg = pill.querySelector('svg')!;
		expect(svg).toHaveAttribute('aria-hidden', 'true');
		expect(svg.querySelector(shape)).toBeInTheDocument();
		expect(svg.children).toHaveLength(1);
		expect(container.querySelector('.sev-count')).toBeNull();
	});

	it('renders the count tile with the pill on top and the count below', () => {
		const { container } = render(SeverityPill, { level: 'medium', count: 1234 });
		const tile = container.querySelector('.sev-count')!;
		expect(tile.firstElementChild).toHaveClass('sev', 'sev-medium');
		expect(tile.querySelector(':scope > b')).toHaveTextContent('1,234');
	});

	it('shows a zero count', () => {
		const { container } = render(SeverityPill, { level: 'critical', count: 0 });
		expect(container.querySelector('.sev-count > b')).toHaveTextContent('0');
	});
});
