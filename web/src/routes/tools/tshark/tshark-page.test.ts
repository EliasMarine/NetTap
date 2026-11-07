import { describe, it, expect } from 'vitest';
import { isRedirect } from '@sveltejs/kit';
import { load } from './+page';

// OLD CODE START — NET-188: the page redirects to /packets now; this rendered the old AnalysisPanel
// import { render, screen } from '@testing-library/svelte';
// import { readable } from 'svelte/store';
// import Page from './+page.svelte';
//
// vi.mock('$app/stores', () => ({ page: readable({ url: new URL('http://localhost/tools/tshark'), params: {} }) }));
//
// describe('TShark packet analysis page', () => {
// 	afterEach(() => vi.unstubAllGlobals());
//
// 	it('has one page title, a link back to the tools, and the analysis panel', () => {
// 		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
// 		render(Page);
// 		expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
// 		expect(screen.getByRole('heading', { level: 1, name: 'TShark packet analysis' })).toBeInTheDocument();
// 		expect(screen.getByRole('link', { name: 'Tools' })).toHaveAttribute('href', '/tools');
// 		expect(screen.getByRole('button', { name: 'Refresh TShark status' })).toBeInTheDocument();
// 	});
// });
// OLD CODE END

describe('/tools/tshark', () => {
	it('redirects permanently to Packet analysis, dropping the old link’s parameters', () => {
		let thrown: unknown;
		try {
			(load as unknown as () => void)();
		} catch (err) {
			thrown = err;
		}
		expect(isRedirect(thrown)).toBe(true);
		expect(thrown).toMatchObject({ status: 308, location: '/packets' });
	});
});
