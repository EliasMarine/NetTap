/**
 * NET-369 (QA 2026-11-23 #9): the drawer's section headers (the IoT device dialog's Trust score
 * breakdown, Device info, Quick stats, and every other drawer) toggled their content but exposed no
 * state. Each header says whether it is open and, while open, which body it controls.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import DrawerSection from './DrawerSection.svelte';

const body = (text: string) => createRawSnippet(() => ({ render: () => `<p>${text}</p>` }));

function header(name: string): HTMLElement {
	return screen.getByRole('button', { name });
}

/** The element a header's aria-controls names, or null when it names none. */
function controlled(name: string): HTMLElement | null {
	const id = header(name).getAttribute('aria-controls');
	return id ? document.getElementById(id) : null;
}

describe('DrawerSection disclosure state (NET-369)', () => {
	it('each open header names its own body, and a closed one names none', async () => {
		render(DrawerSection, { title: 'Device info', children: body('MAC and vendor') });
		render(DrawerSection, { title: 'Quick stats', children: body('Bytes and flows') });

		for (const [name, text] of [['Device info', 'MAC and vendor'], ['Quick stats', 'Bytes and flows']]) {
			expect(header(name)).toHaveAttribute('aria-expanded', 'true');
			expect(controlled(name)).toHaveTextContent(text);
		}
		expect(header('Device info').getAttribute('aria-controls')).not.toBe(header('Quick stats').getAttribute('aria-controls'));

		await fireEvent.click(header('Device info'));
		expect(header('Device info')).toHaveAttribute('aria-expanded', 'false');
		expect(header('Device info')).not.toHaveAttribute('aria-controls');
		expect(screen.queryByText('MAC and vendor')).not.toBeInTheDocument();
		// the other section is untouched
		expect(header('Quick stats')).toHaveAttribute('aria-expanded', 'true');
		expect(controlled('Quick stats')).toHaveTextContent('Bytes and flows');

		await fireEvent.click(header('Device info'));
		expect(header('Device info')).toHaveAttribute('aria-expanded', 'true');
		expect(controlled('Device info')).toHaveTextContent('MAC and vendor');
	});

	it('a section that starts collapsed says so', () => {
		render(DrawerSection, { title: 'Trust score breakdown', defaultExpanded: false, children: body('Pillars') });

		expect(header('Trust score breakdown')).toHaveAttribute('aria-expanded', 'false');
		expect(header('Trust score breakdown')).not.toHaveAttribute('aria-controls');
		expect(screen.queryByText('Pillars')).not.toBeInTheDocument();
	});
});
