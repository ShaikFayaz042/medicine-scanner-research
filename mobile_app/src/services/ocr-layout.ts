/**
 * Rebuilding the printed layout from OCR bounding boxes.
 *
 * Kept free of native imports so the geometry can be exercised on its own,
 * the same way `barcode.ts` is. `scanner.ts` owns the camera/OCR pipeline and
 * calls in here.
 */

import type { TextBlock } from "expo-mlkit-ocr";

/**
 * Lines whose vertical centres sit within this fraction of the taller line's
 * height are treated as belonging to the same printed row. 0.6 tolerates the
 * baseline jitter between a small label and a larger value without merging two
 * genuinely separate rows.
 */
const ROW_TOLERANCE = 0.6;

/** Column separator in the rebuilt text. Any whitespace satisfies the parsers. */
const COLUMN_GAP = "  ";

type Box = { x: number; y: number; width: number; height: number };
type PositionedLine = { text: string; box: Box };

const centreY = (box: Box) => box.y + box.height / 2;

/**
 * Rebuilds the printed row layout from the OCR bounding boxes.
 *
 * ML Kit reports text as blocks, and on a medicine pack it routinely puts a
 * column of labels in one block and the column of values in another. The flat
 * `RecognitionResult.text` is just those blocks concatenated, so a pack printed
 *
 *     B.NO. 49302   EXP. 12/2026
 *
 * arrives as `B.NO.` / `EXP.` / `49302` / `12/2026` - every label adjacent to
 * the wrong value. That breaks label-based extraction outright: a regex
 * matching `B.NO.` followed by whitespace captures `EXP`, silently, as the
 * batch number.
 *
 * Grouping lines by vertical position and sorting each group left to right puts
 * the original rows back, which is what both the regexes and the LLM need in
 * order to pair a label with its value.
 *
 * The grouping assumes roughly axis-aligned text; this OCR wrapper exposes only
 * upright bounding boxes, with no corner points or rotation angle, so a badly
 * skewed photo will still degrade.
 */
export function reconstructRows(blocks: TextBlock[]): string {
  const lines: PositionedLine[] = blocks
    .flatMap((block) => block?.lines ?? [])
    .map((line) => ({ text: line?.text?.trim() ?? "", box: line?.boundingBox }))
    .filter(
      (line): line is PositionedLine =>
        line.text.length > 0 && !!line.box && line.box.height > 0,
    );

  if (!lines.length) return "";

  // Top to bottom first, so rows are built in reading order.
  lines.sort((a, b) => centreY(a.box) - centreY(b.box));

  const rows: { items: PositionedLine[]; centre: number; height: number }[] = [];

  for (const line of lines) {
    const centre = centreY(line.box);
    const row = rows[rows.length - 1];

    const belongsToRow =
      row &&
      Math.abs(centre - row.centre) <=
        ROW_TOLERANCE * Math.max(line.box.height, row.height);

    if (row && belongsToRow) {
      row.items.push(line);
      // Running means, so the band stays put instead of drifting downwards as
      // each new line is absorbed.
      const n = row.items.length;
      row.centre = (row.centre * (n - 1) + centre) / n;
      row.height = (row.height * (n - 1) + line.box.height) / n;
    } else {
      rows.push({ items: [line], centre, height: line.box.height });
    }
  }

  return rows
    .map((row) =>
      row.items
        .slice()
        .sort((a, b) => a.box.x - b.box.x)
        .map((item) => item.text)
        .join(COLUMN_GAP),
    )
    .join("\n");
}

