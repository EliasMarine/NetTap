// @ts-nocheck -- three ships no types; this canvas engine has one caller (Globe.svelte)
// Reads the design system's colour tokens off the page, so the globe follows the theme.
// The tokens stay the single source of colour: nothing here is a colour literal.

export const TOKEN_NAMES = [
	'bg', 'surface-1', 'surface-2', 'surface-3', 'line', 'line-strong',
	'text-1', 'text-2', 'text-3', 'accent', 'accent-strong', 'map-dot', 'hero-glow',
	'card-top', 'card-bottom', 'data-1', 'data-2', 'sev-critical', 'ok',
];

let probe = null;

function context() {
	if (!probe) {
		// Offscreen 1×1 canvas, never attached: the browser parses any CSS colour for us
		const c = document.createElement('canvas');
		c.width = 1;
		c.height = 1;
		probe = c.getContext('2d', { willReadFrequently: true });
	}
	return probe;
}

/** Any CSS colour → { r, g, b, a } in 0..1, sRGB as CSS paints it. */
export function parseColour(value) {
	const ctx = context();
	ctx.clearRect(0, 0, 1, 1);
	ctx.fillStyle = 'transparent'; // an invalid value keeps the previous style; reset first
	ctx.fillStyle = value || 'transparent';
	ctx.fillRect(0, 0, 1, 1);
	const d = ctx.getImageData(0, 0, 1, 1).data;
	return { r: d[0] / 255, g: d[1] / 255, b: d[2] / 255, a: d[3] / 255 };
}

/** Every token as a colour, plus a signature that changes when any token changes. */
export function readTheme(el) {
	const cs = getComputedStyle(el);
	const raw = TOKEN_NAMES.map((n) => cs.getPropertyValue('--' + n).trim());
	const colours = {};
	TOKEN_NAMES.forEach((n, i) => {
		colours[n] = parseColour(raw[i]);
	});
	return { colours, signature: raw.join('|') };
}
