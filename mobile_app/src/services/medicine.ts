/**
 * Medicine verification.
 *
 * Each scan path makes exactly ONE call and gets back everything the result
 * screen needs - the extracted fields *and* the verdict. The client never
 * parses a label or decides whether a batch is genuine: both happen server-side,
 * where they can be fixed without an app release and cannot be forged.
 *
 * Transport lives in `api.ts`.
 */

import { api } from "./api";

// ---------------------------------------------------------------------------
// Types - these mirror the FastAPI schemas in server/src/schemas/scan_schema.py
// ---------------------------------------------------------------------------

export type MedicineFields = {
  name: string;
  salt: string;
  batchNumber: string;
  mfdDate: string;
  expDate: string;
  dose: string;
};

export const EMPTY_FIELDS: MedicineFields = {
  name: "",
  salt: "",
  batchNumber: "",
  mfdDate: "",
  expDate: "",
  dose: "",
};

export type VerificationStatus = "safe" | "unsafe" | "unknown";

/** How the details were obtained. Recorded with the scan, shown on the result. */
export type ScanMethod =
  | "barcode"
  | "barcode_corrected"
  | "ocr"
  | "ocr_corrected"
  | "manual";

export type Coordinates = { latitude: number; longitude: number };

/** Everything the result screen renders. Returned by all three scan endpoints. */
export type MedicineResult = {
  fields: MedicineFields;
  /** The verdict. The client does not compute this.  */
  status: VerificationStatus;
  /** Headline for the status card, authored by the backend. */
  title: string;
  message: string;
  gtin: string;
  serial: string;
};

export type ScanHistoryEntry = {
  id: string;
  name: string;
  dose: string;
  batchNumber: string;
  /** ISO 8601 timestamp. */
  scannedAt: string;
  status: VerificationStatus;
};

// ---------------------------------------------------------------------------
// Backend calls
// ---------------------------------------------------------------------------

/**
 * OCR path. The text recognised on-device is sent as-is; the backend does the
 * whole job in this one call: LLM extraction, then the register lookup.
 */
export function verifyScannedText(
  rawText: string,
  location: Coordinates | null,
): Promise<MedicineResult> {
  return api.post<MedicineResult>("/scans/text", {
    rawText,
    location,
    method: "ocr",
  });
}

/**
 * Barcode path. The payload is sent **undecoded**: the client decodes a copy
 * for its on-screen hint, but the verdict is only trustworthy if the server
 * derives the batch number itself. No LLM is involved on this path.
 */
export function verifyScannedBarcode(
  raw: string,
  symbology: string,
  location: Coordinates | null,
): Promise<MedicineResult> {
  return api.post<MedicineResult>("/scans/barcode", {
    raw,
    symbology,
    location,
    method: "barcode",
  });
}

/** Manual entry path. Nothing to extract - the backend looks the batch up. */
export function verifyManualEntry(
  fields: MedicineFields,
  location: Coordinates | null,
  gtin?: string,
  serial?: string,
  method: ScanMethod = "manual",
): Promise<MedicineResult> {
  return api.post<MedicineResult>("/scans/manual", {
    fields,
    gtin: gtin ?? "",
    serial: serial ?? "",
    location,
    method,
  });
}

/** The signed-in user's previous scans, newest first. */
export function fetchScanHistory(limit = 50): Promise<ScanHistoryEntry[]> {
  // The user is taken from the bearer token server-side, never from the URL.
  return api.get<ScanHistoryEntry[]>("/scans", { limit });
}

/** Recheck a saved scan against the currently indexed regulatory records. */
export function fetchScanResult(scanId: string): Promise<MedicineResult> {
  return api.get<MedicineResult>(`/scans/${encodeURIComponent(scanId)}`);
}

// ---------------------------------------------------------------------------
// Helpers used by the screens
// ---------------------------------------------------------------------------

/**
 * Flattens a result into route params for the result screen. Route params are
 * strings, so the stringifying happens here rather than at each call site.
 */
export function toResultParams(
  result: MedicineResult,
  context: {
    method?: ScanMethod;
    location: Coordinates | null;
    barcode?: string;
  },
): Record<string, string> {
  const matches = (result as MedicineResult & { matches?: unknown[] }).matches;

  return {
    ...result.fields,
    status: result.status,
    title: result.title,
    message: result.message,
    gtin: result.gtin,
    serial: result.serial,
    matches: JSON.stringify(matches ?? []),
    barcode: context.barcode ?? "",
    method: context.method ?? "",
    lat: context.location ? String(context.location.latitude) : "",
    lng: context.location ? String(context.location.longitude) : "",
  };
}

/**
 * True when the backend could not verify because the input was incomplete, as
 * opposed to the batch genuinely not being in the register. An empty batch
 * number is the server's signal that the user must supply more.
 */
export function needsManualEntry(result: MedicineResult): boolean {
  return !result.fields.batchNumber;
}
