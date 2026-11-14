import { redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';

/** NET-273: Suricata rules is a tab of the one Settings page now, so the old address opens it there. */
export const load: PageLoad = () => {
	redirect(308, '/settings?tab=suricata-rules');
};
