import { ImageManipulator, SaveFormat } from "expo-image-manipulator";
import { reconstructRows } from "./ocr-layout";

export type Size = { width: number; height: number };
export type Rect = { x: number; y: number; width: number; height: number };

/**
 * Grow the requested region slightly before cropping. Two reasons:
 *  - the preview stream and the still capture are not guaranteed to come from
 *    exactly the same sensor crop on every Android device, so a little slack
 *    keeps the target inside the cropped image;
 *  - ML Kit reads characters more reliably when they are not flush against the
 *    image edge.
 */
const FRAME_PADDING = 0.06;

/** ML Kit wants roughly 16px of character height; upscaling small crops helps. */
const TARGET_OCR_WIDTH = 1280;
const MAX_UPSCALE = 3;

const clamp = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), max);

/**
 * Translates a rectangle measured in on-screen preview coordinates into pixel
 * coordinates of the captured photo.
 *
 * `CameraView` renders its preview "aspect fill": the frame is scaled by the
 * larger of the two axis ratios and the overflow is clipped evenly on both
 * sides. Undoing that transform is what makes the crop line up with the box the
 * user actually saw on screen.
 *
 * Returns `null` when either size is degenerate, in which case callers should
 * fall back to the uncropped image.
 */
export function mapPreviewRectToPhoto(
  rect: Rect,
  preview: Size,
  photo: Size,
  padding: number = FRAME_PADDING,
): Rect | null {
  if (preview.width <= 0 || preview.height <= 0) return null;
  if (photo.width <= 0 || photo.height <= 0) return null;

  const scale = Math.max(
    preview.width / photo.width,
    preview.height / photo.height,
  );

  // How much of the photo is clipped off each edge to fill the preview.
  const clippedX = (photo.width * scale - preview.width) / 2;
  const clippedY = (photo.height * scale - preview.height) / 2;

  const padX = rect.width * padding;
  const padY = rect.height * padding;

  const left = (rect.x - padX + clippedX) / scale;
  const top = (rect.y - padY + clippedY) / scale;
  const right = (rect.x + rect.width + padX + clippedX) / scale;
  const bottom = (rect.y + rect.height + padY + clippedY) / scale;

  const originX = Math.round(clamp(left, 0, photo.width));
  const originY = Math.round(clamp(top, 0, photo.height));
  const maxX = Math.round(clamp(right, 0, photo.width));
  const maxY = Math.round(clamp(bottom, 0, photo.height));

  const width = maxX - originX;
  const height = maxY - originY;
  if (width < 1 || height < 1) return null;

  return { x: originX, y: originY, width, height };
}

export type RegionTextResult = {
  /** Recognised text with the pack's printed rows rebuilt. Send this onwards. */
  text: string;
  /** ML Kit's own block concatenation, kept for debugging comparisons. */
  rawText: string;
  /** URI of the image that was actually handed to the OCR engine. */
  uri: string;
  /** False when the crop could not be computed and the full frame was used. */
  cropped: boolean;
};

/**
 * Crops the captured photo down to the region the user framed, then runs OCR on
 * just that region so unrelated packaging text never reaches the parser.
 */
export async function recognizeTextInRegion(
  photoUri: string,
  photoSize: Size,
  frame: Rect,
  previewSize: Size,
): Promise<RegionTextResult> {
  const crop = mapPreviewRectToPhoto(frame, previewSize, photoSize);

  let uri = photoUri;
  let cropped = false;

  if (crop) {
    const context = ImageManipulator.manipulate(photoUri).crop({
      originX: crop.x,
      originY: crop.y,
      width: crop.width,
      height: crop.height,
    });

    const upscale = Math.min(MAX_UPSCALE, TARGET_OCR_WIDTH / crop.width);
    if (upscale > 1) {
      context.resize({ width: Math.round(crop.width * upscale) });
    }

    const rendered = await context.renderAsync();
    const saved = await rendered.saveAsync({
      format: SaveFormat.JPEG,
      compress: 1,
    });

    uri = saved.uri;
    cropped = true;
  }

  let ocr: typeof import("expo-mlkit-ocr");
  try {
    ocr = await import("expo-mlkit-ocr");
  } catch {
    throw new Error(
      "Text scanning is unavailable in this app build. Install a MediCheck development build with OCR support.",
    );
  }

  const result = await ocr.recognizeText(uri);
  const rawText = (result.text ?? "").trim();

  // Prefer the rebuilt layout; fall back to ML Kit's concatenation if no
  // geometry came back (an empty result, or a future OCR backend without boxes).
  const text = reconstructRows(result.blocks ?? []) || rawText;

  return { text, rawText, uri, cropped };
}
