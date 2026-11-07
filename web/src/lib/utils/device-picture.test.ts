import { describe, it, expect, vi, afterEach } from 'vitest';
import { centreSquare, pictureFileError, squarePicture, PICTURE_SIZE } from './device-picture';

describe('pictureFileError', () => {
	it('accepts PNG, JPEG and WebP up to 10 MB', () => {
		for (const type of ['image/png', 'image/jpeg', 'image/webp']) {
			expect(pictureFileError({ type, size: 10 * 1024 * 1024 })).toBeNull();
		}
	});

	it('refuses other types, SVG included', () => {
		for (const type of ['image/svg+xml', 'image/gif', 'image/heic', 'text/html', '']) {
			expect(pictureFileError({ type, size: 100 })).toBe('Choose a PNG, JPEG or WebP picture.');
		}
	});

	it('refuses a file over 10 MB, and an empty one', () => {
		expect(pictureFileError({ type: 'image/png', size: 10 * 1024 * 1024 + 1 })).toBe('Choose a picture smaller than 10 MB.');
		expect(pictureFileError({ type: 'image/png', size: 0 })).toBe('That file is empty.');
	});
});

describe('centreSquare', () => {
	it('crops the middle of a wide, a tall and a square image', () => {
		expect(centreSquare(400, 300)).toEqual({ sx: 50, sy: 0, side: 300 });
		expect(centreSquare(300, 401)).toEqual({ sx: 0, sy: 50, side: 300 });
		expect(centreSquare(256, 256)).toEqual({ sx: 0, sy: 0, side: 256 });
	});
});

describe('squarePicture', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('rejects a wrong type before decoding anything', async () => {
		const decode = vi.fn();
		vi.stubGlobal('createImageBitmap', decode);
		await expect(squarePicture(new File(['<svg/>'], 'a.svg', { type: 'image/svg+xml' }))).rejects.toThrow('Choose a PNG');
		expect(decode).not.toHaveBeenCalled();
	});

	it('says so when the browser cannot read the file', async () => {
		vi.stubGlobal('createImageBitmap', vi.fn().mockRejectedValue(new Error('bad')));
		await expect(squarePicture(new File(['x'], 'a.png', { type: 'image/png' }))).rejects.toThrow("Couldn't read that picture");
	});

	/** A fake canvas whose toDataURL answers each type with `encode(type)`. */
	function fakeCanvas(encode: (type: string) => string) {
		const context = {
			drawImage: vi.fn(),
			fillRect: vi.fn(),
			fillStyle: '',
			globalCompositeOperation: 'source-over',
			imageSmoothingEnabled: false,
			imageSmoothingQuality: 'low',
		};
		const toDataURL = vi.fn((type: string) => encode(type));
		const realCreate = document.createElement.bind(document);
		vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
			if (tag !== 'canvas') return realCreate(tag);
			return { width: 0, height: 0, getContext: () => context, toDataURL } as unknown as HTMLCanvasElement;
		});
		return { context, toDataURL };
	}

	it('draws the centre square at 256 px, smoothly, and asks for WebP', async () => {
		const close = vi.fn();
		vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 400, height: 300, close }));
		const { context, toDataURL } = fakeCanvas(() => 'data:image/webp;base64,AAAA');
		await expect(squarePicture(new File(['x'], 'a.jpg', { type: 'image/jpeg' }))).resolves.toBe('data:image/webp;base64,AAAA');
		expect(context.drawImage).toHaveBeenCalledWith(expect.anything(), 50, 0, 300, 300, 0, 0, PICTURE_SIZE, PICTURE_SIZE);
		expect(context.imageSmoothingQuality).toBe('high');
		expect(toDataURL).toHaveBeenCalledWith('image/webp', 0.85);
		expect(toDataURL).toHaveBeenCalledTimes(1);
		expect(context.fillRect).not.toHaveBeenCalled();
		expect(close).toHaveBeenCalled();
		vi.restoreAllMocks();
	});

	it('falls back to JPEG on white where the browser hands back PNG for WebP', async () => {
		vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 300, height: 300, close: vi.fn() }));
		const { context, toDataURL } = fakeCanvas((type) => (type === 'image/jpeg' ? 'data:image/jpeg;base64,BBBB' : 'data:image/png;base64,CCCC'));
		await expect(squarePicture(new File(['x'], 'a.png', { type: 'image/png' }))).resolves.toBe('data:image/jpeg;base64,BBBB');
		expect(context.globalCompositeOperation).toBe('destination-over');
		expect(context.fillStyle).toBe('#ffffff');
		expect(context.fillRect).toHaveBeenCalledWith(0, 0, PICTURE_SIZE, PICTURE_SIZE);
		expect(toDataURL).toHaveBeenLastCalledWith('image/jpeg', 0.85);
		vi.restoreAllMocks();
	});
});
