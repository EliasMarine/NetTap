/**
 * NET-200: an owner's photo for a device, made small and square in the browser before upload.
 * Re-encoding through a canvas also drops the file's metadata (a phone photo's GPS position).
 * The daemon checks the bytes again; this only spares the owner a round trip.
 */

/** The source types the browser takes; the daemon accepts the same three. */
export const PICTURE_TYPES = ['image/png', 'image/jpeg', 'image/webp'] as const;
/** The largest source file: it is shrunk to PICTURE_SIZE before it leaves the browser. */
export const PICTURE_SOURCE_MAX_BYTES = 10 * 1024 * 1024;
/** The side of the square the photo is cropped to, in pixels. */
export const PICTURE_SIZE = 256;

/** Why `file` can't be used as a device picture, or null when it can. */
export function pictureFileError(file: Pick<File, 'type' | 'size'>): string | null {
	if (!(PICTURE_TYPES as readonly string[]).includes(file.type)) return 'Choose a PNG, JPEG or WebP picture.';
	if (file.size > PICTURE_SOURCE_MAX_BYTES) return 'Choose a picture smaller than 10 MB.';
	if (file.size === 0) return 'That file is empty.';
	return null;
}

/** The centre square of a `width` × `height` image: where to read from, in source pixels. */
export function centreSquare(width: number, height: number): { sx: number; sy: number; side: number } {
	const side = Math.min(width, height);
	return { sx: Math.floor((width - side) / 2), sy: Math.floor((height - side) / 2), side };
}

/**
 * The file as a PICTURE_SIZE square data URL: WebP, or PNG where the browser can't encode WebP
 * (toDataURL falls back by itself; the daemon takes both). Rejects with a plain-English reason.
 */
export async function squarePicture(file: File): Promise<string> {
	const problem = pictureFileError(file);
	if (problem) throw new Error(problem);
	let bitmap: ImageBitmap;
	try {
		bitmap = await createImageBitmap(file);
	} catch {
		throw new Error("Couldn't read that picture. Try another file.");
	}
	try {
		const { sx, sy, side } = centreSquare(bitmap.width, bitmap.height);
		const canvas = document.createElement('canvas');
		canvas.width = PICTURE_SIZE;
		canvas.height = PICTURE_SIZE;
		const context = canvas.getContext('2d');
		if (!context) throw new Error("This browser can't resize pictures.");
		context.drawImage(bitmap, sx, sy, side, side, 0, 0, PICTURE_SIZE, PICTURE_SIZE);
		// OLD CODE: return canvas.toDataURL('image/webp', 0.85); (review: the PNG fallback of a noisy photo can pass the daemon's 256 KB cap)
		const webp = canvas.toDataURL('image/webp', 0.85);
		// A browser that can't encode WebP hands back PNG; JPEG stays small (a transparent picture loses its transparency)
		return webp.startsWith('data:image/webp') ? webp : canvas.toDataURL('image/jpeg', 0.85);
	} finally {
		bitmap.close();
	}
}
