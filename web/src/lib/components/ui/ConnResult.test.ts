import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import ConnResult, { type ConnResultKind } from './ConnResult.svelte';

describe('ConnResult', () => {
	it.each<[ConnResultKind, string, string | null]>([
		['completed', 'Completed', null],
		['ongoing', 'Ongoing', 'is-live'],
		['no-reply', 'No reply', 'is-medium'],
		['reset', 'Reset', 'is-high'],
	])('%s reads %s with the matching dot class', (result, word, cls) => {
		const { container } = render(ConnResult, { result });
		const res = container.querySelector('span.res')!;
		expect(res).toHaveTextContent(word);
		expect([...res.classList].filter((c) => c !== 'res' && !c.startsWith('svelte-'))).toEqual(cls ? [cls] : []);
	});
});
