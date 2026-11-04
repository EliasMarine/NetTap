import type { LayoutServerLoad } from './$types';

/**
 * The shell's user row needs only the name. Authorisation stays in hooks.server.ts: this
 * never redirects and never returns more than the username (PLAN.md §5.5).
 */
export const load: LayoutServerLoad = ({ locals }) => ({
	username: locals.user?.username ?? null,
});
