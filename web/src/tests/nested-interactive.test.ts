import { describe, it, expect } from 'vitest';
import { expectNoNestedInteractive, nestedInteractive } from './nested-interactive';

function dom(html: string): HTMLElement {
	const div = document.createElement('div');
	div.innerHTML = html;
	return div;
}

describe('expectNoNestedInteractive', () => {
	it('passes sibling links and buttons', () => {
		expectNoNestedInteractive(dom('<span><a href="/x">x</a><button>menu</button></span><p tabindex="0">p</p>'));
	});

	it.each([
		['a link in a link', '<a href="/a">a <a href="/b">b</a></a>'],
		['a link in a button', '<button>row <a href="/b">b</a></button>'],
		['a role=button in a link', '<a href="/a"><span role="button">x</span></a>'],
		['a focusable span in a button', '<button><span tabindex="0">x</span></button>'],
		['a button in a role=button', '<div role="button"><button>x</button></div>'],
	])('finds %s', (_what, html) => {
		// innerHTML closes an <a> before a nested <a>, so build that case by hand
		const root = html.startsWith('<a href="/a">a <a') ? nestedLinks() : dom(html);
		expect(nestedInteractive(root)).toHaveLength(1);
		expect(() => expectNoNestedInteractive(root)).toThrow();
	});
});

function nestedLinks(): HTMLElement {
	const root = document.createElement('div');
	const outer = document.createElement('a');
	outer.href = '/a';
	const inner = document.createElement('a');
	inner.href = '/b';
	outer.append(inner);
	root.append(outer);
	return root;
}
