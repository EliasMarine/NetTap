/**
 * The error text of the web app's own 401 for a call with no session (hooks.server.ts). The shell's
 * ping check (routes/+layout.svelte) matches it to tell a lapsed session from the daemon's own 401,
 * so both sides read it from here.
 */
export const SIGN_IN_FIRST = 'Sign in first';
