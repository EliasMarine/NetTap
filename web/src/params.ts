import { defineParams } from '@sveltejs/kit/params';
// `vite build` loads this file with plain Node: relative path, .ts extension, and nothing that imports an alias (sveltejs/kit#17442)
import { isPostureSlug } from './lib/posture/slugs.ts';

// OLD CODE START — kit 3 reads every matcher from this one file; src/params/posture.ts was (NET-315):
// import type { ParamMatcher } from '@sveltejs/kit';
// import { isPostureSlug } from '$lib/posture/score';
//
// /** /compliance/[category=posture]: the six Security posture categories; any other name is a 404. */
// export const match: ParamMatcher = (param) => isPostureSlug(param);
// OLD CODE END

export const params = defineParams({
	/** /compliance/[category=posture]: the six Security posture categories; any other name is a 404. A matcher returns the value, or undefined for no match. */
	posture: (param) => (isPostureSlug(param) ? param : undefined),
});
