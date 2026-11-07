import { redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';

/**
 * NET-188: TShark packet analysis became Packet analysis (/packets), which reads the saved
 * captures by time and filter instead of by file path. The old links' parameters (a path, a
 * filter, a timestamp) don't make a /packets search, so they are dropped rather than guessed.
 */
export const load: PageLoad = () => {
	redirect(308, '/packets');
};
