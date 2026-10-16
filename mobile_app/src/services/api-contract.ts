/**
 * Compile-time proof that the hand-written client types match the server.
 *
 * `api-types.d.ts` is generated from FastAPI's OpenAPI schema:
 *
 *   npx openapi-typescript http://localhost:8000/openapi.json \
 *     -o src/services/api-types.d.ts
 *
 * If the server renames a field, changes a type or adds a required one, this
 * file stops compiling and `npx tsc --noEmit` fails - instead of the app
 * silently reading `undefined` at runtime on someone's phone.
 *
 * Entirely type-level: nothing here is emitted into the bundle. The aliases
 * below are never referenced on purpose - the type checker evaluates them
 * anyway, which is the whole mechanism.
 */

/* eslint-disable @typescript-eslint/no-unused-vars */

import type { AuthSession } from "./auth";
import type { components } from "./api-types";
import type {
  MedicineFields,
  MedicineResult,
  ScanHistoryEntry,
  VerificationStatus,
} from "./medicine";

type Server = components["schemas"];

/** Bidirectional assignability, i.e. the two types are structurally identical. */
type Exact<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
type Expect<T extends true> = T;

type _MedicineFields = Expect<Exact<MedicineFields, Server["MedicineFields"]>>;
type _MedicineResult = Expect<Exact<MedicineResult, Server["MedicineResult"]>>;
type _HistoryEntry = Expect<Exact<ScanHistoryEntry, Server["ScanHistoryEntry"]>>;
type _Status = Expect<Exact<VerificationStatus, Server["VerificationStatus"]>>;
type _AuthSession = Expect<Exact<AuthSession, Server["AuthResponse"]>>;
