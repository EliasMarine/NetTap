/**
 * Client-side API helpers for the CyberChef integration endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CyberChefStatus {
	available: boolean;
	version: string;
	container_running: boolean;
	container_name: string;
}

export interface CyberChefRecipe {
	name: string;
	description: string;
	category: string;
	recipe_fragment: string;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get CyberChef container availability and version information.
 */
export async function getCyberChefStatus(): Promise<CyberChefStatus> {
	const res = await fetch('/api/cyberchef/status');

	if (!res.ok) {
		return {
			available: false,
			version: '',
			container_running: false,
			container_name: '',
		};
	}

	return res.json();
}

/**
 * Retrieve the list of pre-built CyberChef recipes.
 * Optionally filter by category (e.g. "decode", "encode", "network").
 */
export async function getRecipes(
	category?: string
): Promise<{ recipes: CyberChefRecipe[]; count: number }> {
	const params = category ? `?category=${encodeURIComponent(category)}` : '';
	const res = await fetch(`/api/cyberchef/recipes${params}`);

	if (!res.ok) {
		return { recipes: [], count: 0 };
	}

	return res.json();
}

/**
 * Build a CyberChef URL with the given recipe fragment and input data.
 * Returns a URL that can be opened in an iframe or new tab.
 */
export async function buildRecipeUrl(
	recipe_fragment: string,
	input_data: string
): Promise<{ url: string }> {
	const res = await fetch('/api/cyberchef/url', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ recipe_fragment, input_data }),
	});

	if (!res.ok) {
		const body = await res.json().catch(() => ({}));
		throw new Error(body.error || `Failed to build recipe URL (HTTP ${res.status})`);
	}

	return res.json();
}
