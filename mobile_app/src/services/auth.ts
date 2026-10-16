/**
 * Authentication.
 *
 * The token is the only thing persisted. Everything user-scoped on the server
 * is derived from it, so there is no user id to keep in sync on the device.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";

import { ApiError, TOKEN_KEY, api } from "./api";

export const ONBOARDING_KEY = "hasSeenOnboarding";

export type AuthUser = {
  id: string;
  name: string;
  email: string;
};

export type AuthSession = {
  token: string;
  /** Seconds until the token expires. */
  expiresIn: number;
  user: AuthUser;
};

async function persist(session: AuthSession): Promise<AuthSession> {
  await AsyncStorage.setItem(TOKEN_KEY, session.token);
  return session;
}

export async function login(
  email: string,
  password: string,
): Promise<AuthSession> {
  const session = await api.post<AuthSession>(
    "/auth/login",
    { email, password },
    { anonymous: true },
  );
  return persist(session);
}

export async function register(
  name: string,
  email: string,
  password: string,
): Promise<AuthSession> {
  const session = await api.post<AuthSession>(
    "/auth/register",
    { name, email, password },
    { anonymous: true },
  );
  return persist(session);
}

/**
 * Starts the backend-managed Google Authorization Code + PKCE flow in a browser.
 */
export function startGoogleWebLogin(): void {
  api.redirect("/auth/google/start");
}

/** Consumes the short-lived HttpOnly OAuth handoff and persists MediCheck's JWT. */
export async function consumeGoogleWebSession(): Promise<AuthSession> {
  const session = await api.post<AuthSession>(
    "/auth/google/session",
    undefined,
    { anonymous: true, credentials: "include" },
  );
  return persist(session);
}

/** Exchanges a Google ID token for a MediCheck session on native platforms. */
export async function loginWithGoogle(idToken: string): Promise<AuthSession> {
  const session = await api.post<AuthSession>(
    "/auth/google",
    { idToken },
    { anonymous: true },
  );
  return persist(session);
}

export async function signOut(): Promise<void> {
  const token = await getStoredToken();
  await AsyncStorage.removeItem(TOKEN_KEY);
  if (token) {
    void api.post<void>("/auth/logout", undefined, { token }).catch(() => undefined);
  }
}

export async function getStoredToken(): Promise<string | null> {
  try {
    return await AsyncStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

/**
 * Checks a stored token against the server on launch.
 *
 * A token can be structurally valid but useless - expired, signed with a key
 * that has since rotated, or belonging to a deleted account. Asking the server
 * is the only way to know before dropping the user into the scanner.
 */
export async function verifyStoredSession(): Promise<AuthUser | null> {
  const token = await getStoredToken();
  if (!token) return null;

  try {
    return await api.get<AuthUser>("/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.isUnauthorized) {
      await signOut();
      return null;
    }
    // Offline or the server is down. Keep the token: the session may well
    // still be good, and forcing a sign-out over a dropped connection is worse
    // than letting the next real request fail.
    return null;
  }
}
