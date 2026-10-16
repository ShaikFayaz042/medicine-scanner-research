/**
 * Barcode parsing for pharmaceutical packaging.
 *
 * Packs carry one of two useful things:
 *  - a plain product code (EAN-13 / UPC / EAN-8), which is just a GTIN and
 *    carries no batch or expiry at all; or
 *  - GS1 element strings (GS1-128, GS1 DataMatrix, GS1 QR), which encode the
 *    GTIN *plus* the batch, expiry, production date and serial as a sequence of
 *    Application Identifier (AI) + value pairs.
 *
 * The AI form is what lets us fill in the fields without any OCR at all.
 */

/** FNC1, transmitted by scanners as ASCII group separator. */
const GS = "";

/** Symbology identifiers some scanners prepend to the payload. */
const SYMBOLOGY_PREFIXES = ["]C1", "]e0", "]d2", "]Q3", "]J1"];

type AiSpec = {
  /** Fixed number of data characters, or "variable" (runs to FNC1 / end). */
  length: number | "variable";
  label: string;
};

/**
 * Only the AIs a medicine scanner actually needs, plus the fixed-length ones we
 * must know about in order to walk past them correctly. An unrecognised AI stops
 * parsing rather than guessing a length and corrupting everything after it.
 */
const AI_TABLE: Record<string, AiSpec> = {
  "00": { length: 18, label: "SSCC" },
  "01": { length: 14, label: "GTIN" },
  "02": { length: 14, label: "Contained GTIN" },
  "10": { length: "variable", label: "Batch/lot" },
  "11": { length: 6, label: "Production date" },
  "12": { length: 6, label: "Due date" },
  "13": { length: 6, label: "Packaging date" },
  "15": { length: 6, label: "Best before" },
  "16": { length: 6, label: "Sell by" },
  "17": { length: 6, label: "Expiry date" },
  "20": { length: 2, label: "Variant" },
  "21": { length: "variable", label: "Serial" },
  "22": { length: "variable", label: "Consumer product variant" },
  "30": { length: "variable", label: "Count" },
  "37": { length: "variable", label: "Count of trade items" },
  "240": { length: "variable", label: "Additional product ID" },
  "241": { length: "variable", label: "Customer part number" },
  "710": { length: "variable", label: "National healthcare number" },
  "711": { length: "variable", label: "National healthcare number" },
  "712": { length: "variable", label: "National healthcare number" },
  "713": { length: "variable", label: "National healthcare number" },
  "714": { length: "variable", label: "National healthcare number" },
};

export type BarcodeFormat = "gs1" | "gtin" | "unknown";

export type ParsedBarcode = {
  /** Exactly what the scanner handed us, before any cleanup. */
  raw: string;
  /** The camera's symbology name, e.g. "ean13" or "datamatrix". */
  symbology: string;
  format: BarcodeFormat;
  /** Normalised to 14 digits, which is how product databases are keyed. */
  gtin?: string;
  batchNumber?: string;
  /** DD/MM/YYYY, or MM/YYYY when the barcode only pins down the month. */
  expDate?: string;
  mfdDate?: string;
  serial?: string;
  /** True when the GTIN check digit is valid. Undefined when there is no GTIN. */
  gtinValid?: boolean;
  /** Every AI that was decoded, for display and debugging. */
  elements: Record<string, string>;
};

const stripPrefix = (value: string) => {
  for (const prefix of SYMBOLOGY_PREFIXES) {
    if (value.startsWith(prefix)) return value.slice(prefix.length);
  }
  return value;
};

/** Finds the AI starting at `index`, trying the 2, 3 then 4 character forms. */
const matchAi = (data: string, index: number): string | null => {
  for (const size of [2, 3, 4]) {
    const candidate = data.slice(index, index + size);
    if (candidate.length === size && AI_TABLE[candidate]) return candidate;
  }
  return null;
};

/** Parses the bracketed human-readable form, e.g. `(01)0950...(10)ABC123`. */
const parseBracketed = (data: string): Record<string, string> => {
  const elements: Record<string, string> = {};
  const pattern = /\((\d{2,4})\)([^(]*)/g;

  let match: RegExpExecArray | null;
  while ((match = pattern.exec(data)) !== null) {
    const [, ai, value] = match;
    if (value) elements[ai] = value.trim();
  }
  return elements;
};

/** Parses the concatenated transmission form, using FNC1 to end variable AIs. */
const parseConcatenated = (data: string): Record<string, string> => {
  const elements: Record<string, string> = {};
  let index = 0;

  while (index < data.length) {
    if (data[index] === GS) {
      index += 1;
      continue;
    }

    const ai = matchAi(data, index);
    // An unknown AI means we no longer know where the next field starts, so
    // stop rather than mis-slice everything that follows.
    if (!ai) break;

    index += ai.length;
    const spec = AI_TABLE[ai];

    if (spec.length === "variable") {
      const separator = data.indexOf(GS, index);
      const end = separator === -1 ? data.length : separator;
      elements[ai] = data.slice(index, end);
      index = end;
    } else {
      elements[ai] = data.slice(index, index + spec.length);
      index += spec.length;
    }
  }

  return elements;
};

/** Standard GS1 mod-10 check digit, used by GTIN-8/12/13/14. */
export function isValidGtin(gtin: string): boolean {
  if (!/^\d{8}$|^\d{12,14}$/.test(gtin)) return false;

  const digits = gtin.split("").map(Number);
  const check = digits.pop() as number;

  // Weights alternate 3/1 from the right-hand end of the payload.
  const sum = digits
    .reverse()
    .reduce((total, digit, i) => total + digit * (i % 2 === 0 ? 3 : 1), 0);

  return (10 - (sum % 10)) % 10 === check;
}

/** GTINs are compared as 14 digits, zero-padded on the left. */
const normaliseGtin = (gtin: string) => gtin.padStart(14, "0");

/**
 * Converts a GS1 `YYMMDD` date. Per the specification the year window is
 * 2000-2049 for `00-49` and 1950-1999 for `50-99`, and a day of `00` means
 * "end of this month" - in which case we only report the month.
 */
export function formatGs1Date(value: string): string {
  if (!/^\d{6}$/.test(value)) return "";

  const yy = Number(value.slice(0, 2));
  const mm = value.slice(2, 4);
  const dd = value.slice(4, 6);

  const month = Number(mm);
  if (month < 1 || month > 12) return "";

  const year = yy <= 49 ? 2000 + yy : 1900 + yy;
  return dd === "00" ? `${mm}/${year}` : `${dd}/${mm}/${year}`;
}

/**
 * Turns a scanned payload into structured fields. Never throws - an
 * unrecognised payload comes back with `format: "unknown"` and the raw value.
 */
export function parseBarcode(raw: string, symbology: string): ParsedBarcode {
  const data = stripPrefix(raw.trim());

  const result: ParsedBarcode = {
    raw,
    symbology,
    format: "unknown",
    elements: {},
  };

  if (!data) return result;

  // A bare product code: digits only, and a length a GTIN actually uses.
  if (/^\d+$/.test(data) && [8, 12, 13, 14].includes(data.length)) {
    result.format = "gtin";
    result.gtin = normaliseGtin(data);
    result.gtinValid = isValidGtin(data);
    result.elements = { "01": result.gtin };
    return result;
  }

  const elements = data.includes("(")
    ? parseBracketed(data)
    : parseConcatenated(data);

  if (!Object.keys(elements).length) return result;

  result.format = "gs1";
  result.elements = elements;

  if (elements["01"]) {
    result.gtin = normaliseGtin(elements["01"]);
    result.gtinValid = isValidGtin(elements["01"]);
  }
  if (elements["10"]) result.batchNumber = elements["10"];
  if (elements["21"]) result.serial = elements["21"];

  // 17 is the real expiry; 15 (best before) is the usual fallback.
  const expiry = elements["17"] ?? elements["15"];
  if (expiry) result.expDate = formatGs1Date(expiry);
  if (elements["11"]) result.mfdDate = formatGs1Date(elements["11"]);

  return result;
}

/** Human-readable name for an AI, used when showing what was decoded. */
export const aiLabel = (ai: string) => AI_TABLE[ai]?.label ?? `AI ${ai}`;
