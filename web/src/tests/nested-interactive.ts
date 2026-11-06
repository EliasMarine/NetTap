/**
 * NET-160: IP addresses became links, and a link inside a link or a button breaks keyboard and
 * screen-reader use (and the HTML spec). Page tests call this on their rendered DOM.
 */
import { expect } from 'vitest';

const OUTER = 'a, button, [role=button]';
const INNER = 'a, button, [role=button], [tabindex]';

/** Every interactive element inside a link or button, described as "outer > inner". */
export function nestedInteractive(root: ParentNode): string[] {
	const describe = (el: Element) => `${el.tagName.toLowerCase()}${el.textContent ? ` "${el.textContent.trim().slice(0, 40)}"` : ''}`;
	return [...root.querySelectorAll(OUTER)].flatMap((outer) =>
		[...outer.querySelectorAll(INNER)].map((inner) => `${describe(outer)} > ${describe(inner)}`),
	);
}

/** Fails, naming each pair, when any link or button holds another interactive element. */
export function expectNoNestedInteractive(root: ParentNode): void {
	expect(nestedInteractive(root), 'interactive elements nested inside a link or button').toEqual([]);
}
