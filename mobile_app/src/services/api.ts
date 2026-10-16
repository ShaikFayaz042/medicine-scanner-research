/**
 * The app's only route to the backend.
 *
 * One place owns the base URL, the auth header, timeouts and error shaping, so
 * no screen has to think about any of it. Everything here returns parsed JSON
 * or throws an `ApiError` whose `message` is safe to show the user - the server
 * authors those strings deliberately.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { Platform } from "react-native";

/**
 * Must be a static `process.env.X` reference: Expo inlines these at build time
 * and will not pick the value up through destructuring or bracket access.
 *
 * Set it in `mobile_app/.env`, pointing at your machine's LAN address (not
 * localhost - on the phone that means the phone). Production must use HTTPS:
 *   EXPO_PUBLIC_API_URL=http://192.168.1.x:8000
 */
const BASE_URL = (
  Platform.OS === "web"
    ? process.env.EXPO_PUBLIC_API_URL_WEB ?? "http://localhost:8000"
    : process.env.EXPO_PUBLIC_API_URL ?? ""
).replace(/\/+$/, "");

export const TOKEN_KEY = "userToken";

/** Mobile networks stall rather than fail, so requests need their own deadline. */
const REQUEST_TIMEOUT_MS = 20000;

export class ApiError extends Error {
  readonly status: number;
  /** Correlates with the server log line for the same request. */
  readonly requestId?: string;

  constructor(message: string, status: number, requestId?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.requestId = requestId;
  }

  /** True when the session is gone and the user has to sign in again. */
  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

export const isApiConfigured = BASE_URL.length > 0;

type RequestOptions = {
  method?: "GET" | "POST";
  body?: unknown;
  /** Skip the Authorization header (login and register). */
  anonymous?: boolean;
  /** Use a captured token for best-effort session revocation after local logout. */
  token?: string;
  /** Include the short-lived HttpOnly cookie used only during web OAuth handoff. */
  credentials?: RequestCredentials;
  query?: Record<string, string | number | undefined>;
};

async function authHeader(): Promise<Record<string, string>> {
  try {
    const token = await AsyncStorage.getItem(TOKEN_KEY);
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    // A storage failure must not stop an unauthenticated call going out.
    return {};
  }
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = `${BASE_URL}${path}`;
  if (!query) return url;

  const params = Object.entries(query)
    .filter(([, value]) => value !== undefined)
    .map(
      ([key, value]) =>
        `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`,
    );

  return params.length ? `${url}?${params.join("&")}` : url;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  if (!isApiConfigured) {
    throw new ApiError(
      "The app is not configured to reach the server. Set EXPO_PUBLIC_API_URL.",
      0,
    );
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method: options.method ?? "GET",
      headers: {
        Accept: "application/json",
        ...(options.body === undefined
          ? {}
          : { "Content-Type": "application/json" }),
        ...(options.anonymous
          ? {}
          : options.token !== undefined
            ? { Authorization: `Bearer ${options.token}` }
            : await authHeader()),
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: options.credentials,
      signal: controller.signal,
    });
  } catch (error) {
    const aborted = error instanceof Error && error.name === "AbortError";
    throw new ApiError(
      aborted
        ? "The server took too long to respond. Please try again."
        : "Could not reach the server. Check your connection and try again.",
      0,
    );
  } finally {
    clearTimeout(timeout);
  }

  // 204 and friends have no body to parse.
  const text = await response.text().catch(() => "");
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const detail =
      payload &&
      typeof payload === "object" &&
      typeof (payload as { detail?: unknown }).detail === "string"
        ? (payload as { detail: string }).detail
        : `The server responded with ${response.status}.`;
    const requestId =
      payload && typeof payload === "object"
        ? (payload as { requestId?: string }).requestId
        : undefined;
    throw new ApiError(detail, response.status, requestId);
  }

  return payload as T;
}

export const api = {
  get: <T>(path: string, query?: RequestOptions["query"]) =>
    request<T>(path, { method: "GET", query }),
  post: <T>(
    path: string,
    body?: unknown,
    opts?: {
      anonymous?: boolean;
      credentials?: RequestCredentials;
      token?: string;
    },
  ) =>
    request<T>(path, {
      method: "POST",
      body,
      anonymous: opts?.anonymous,
      credentials: opts?.credentials,
      token: opts?.token,
    }),
  redirect: (path: string) => {
    if (!isApiConfigured || Platform.OS !== "web") {
      throw new ApiError("The web sign-in endpoint is not configured.", 0);
    }
    window.location.assign(`${BASE_URL}${path}`);
  },
};
