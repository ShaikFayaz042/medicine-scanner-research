/**
 * Turning an API failure into something the user can act on.
 *
 * A 401 mid-scan means the session lapsed. Showing "your session expired" on
 * the scanner and leaving the user there is a dead end - every subsequent tap
 * fails the same way. Send them to sign in instead.
 */

import { type useRouter } from "expo-router";

import { ApiError } from "./api";
import { signOut } from "./auth";

export type FailureHandling =
  | { kind: "message"; message: string }
  | { kind: "signed-out" };

export async function describeFailure(
  error: unknown,
  router: ReturnType<typeof useRouter>,
  fallback: string,
): Promise<FailureHandling> {
  if (error instanceof ApiError && error.isUnauthorized) {
    await signOut();
    router.replace("/(auth)/login");
    return { kind: "signed-out" };
  }

  return {
    kind: "message",
    message: error instanceof Error ? error.message : fallback,
  };
}
