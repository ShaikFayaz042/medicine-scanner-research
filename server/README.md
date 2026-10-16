# Server

This module contains the application backend for the medicine scanner system.

It is responsible for:
- FastAPI API routes
- database access and models
- scheduler configuration
- user-facing application controls

The actual scraping worker is separated under the cloud package.

The server does not automatically fall back to local SQLite. Configure its databases with PostgreSQL connection URLs or PostgreSQL host credentials.

## Deployment

Build the standalone API image from the repository root:

```sh
docker build -f server/Dockerfile -t medicine-scanner-api server
```

Run the image with `PORT` and the required database/authentication settings supplied by the deployment platform. At minimum, set `APP_ENV=production`, `MEDICINE_DB_URI`, `SCRAPER_DB_URI` (or the `SCRAPER_DB_*` connection values), `JWT_SECRET_KEY`, and `ALLOWED_HOSTS` to the API's deployed hostname(s). Set `CORS_ORIGINS` to the deployed frontend origins. Configure AWS credentials and the required S3/SQS settings when using document storage or workflow processing. Do not copy local `.env` files into the image; the Docker build excludes them.

Use `/health` as the platform health-check path. The root path serves the built client when `client/dist` is present, and otherwise returns API service information with a link to `/docs`.

## Google sign-in

Browser sign-in uses Google's Web application OAuth client with the backend-managed Authorization Code flow and PKCE. The backend validates OAuth state, exchanges the code, verifies Google's signed ID token (issuer, audience, expiry, nonce, and verified email), and issues the same MediCheck JWT session used by password sign-in. The client secret and OAuth state-signing secret belong only in the backend environment.

For local development, configure:

- `GOOGLE_WEB_CLIENT_ID`: the Web application client ID; use the exact same value as `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID`.
- `GOOGLE_ANDROID_CLIENT_ID`: the Android application client ID; use the exact same value as `EXPO_PUBLIC_GOOGLE_ANDROID_CLIENT_ID`.
- `GOOGLE_IOS_CLIENT_ID`: the iOS application client ID; use the exact same value as `EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID` when iOS is enabled.
- `GOOGLE_WEB_CLIENT_SECRET`: the secret for the Web application client, backend only.
- `GOOGLE_WEB_OAUTH_STATE_SECRET`: a separate random secret of at least 32 characters.
- `GOOGLE_WEB_REDIRECT_URI=http://localhost:8000/auth/google/callback`
- `GOOGLE_WEB_APP_CALLBACK_URI=http://localhost:8081/auth/google`
- `GOOGLE_WEB_OAUTH_COOKIE_SAMESITE=lax`
- `EXPO_PUBLIC_API_URL_WEB=http://localhost:8000`
- `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID`: the same Web application client ID.

Android native Google Sign-In uses `@react-native-google-signin/google-signin` in an Expo development build, not Expo Go. Configure the native library with `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID` so it returns an ID token whose audience is the Web client ID expected by `/auth/google`. The Android OAuth client is registered in Google Cloud with package `com.fayaz.medicheck` and the SHA-1 fingerprint for each signing certificate used (development and production); it identifies/validates the installed Android app and is not the backend ID-token audience. No Expo AuthSession redirect URI is used by this native Android flow. The web browser flow remains backend-managed and continues to use `GOOGLE_WEB_REDIRECT_URI` and `GOOGLE_WEB_APP_CALLBACK_URI` below.

For physical Android devices, set `EXPO_PUBLIC_API_URL` to the development computer's reachable LAN address, not `localhost` or `127.0.0.1`. Start the API listening on `0.0.0.0` and allow the phone to reach the port. The app's development HTTP configuration allows LAN testing; use HTTPS for deployed environments.

In Google Cloud Console, create or use an OAuth client whose application type is **Web application**. Add exactly `http://localhost:8000/auth/google/callback` under **Authorized redirect URIs**. This server-side flow does not require an Authorized JavaScript origin. For production, set `GOOGLE_WEB_REDIRECT_URI` to the deployed HTTPS API URL ending in `/auth/google/callback`, register that exact URI under **Authorized redirect URIs**, and set `GOOGLE_WEB_APP_CALLBACK_URI` to the deployed HTTPS Expo web route ending in `/auth/google`. Add the frontend origin to backend `CORS_ORIGINS`; use `EXPO_PUBLIC_API_URL_WEB` for the matching API URL. Keep the frontend and API on the same site for the default `lax` OAuth cookies. If they must be cross-site, set `GOOGLE_WEB_OAUTH_COOKIE_SAMESITE=none` and use HTTPS for both.

Never put `GOOGLE_WEB_CLIENT_SECRET` or `GOOGLE_WEB_OAUTH_STATE_SECRET` in `mobile_app/.env`, any `EXPO_PUBLIC_*` variable, or a client build.

## OCR medicine-field mapping

`POST /scans/text` sends the on-device OCR text to Gemini when the server has `GEMINI_API_KEY` configured. Gemini maps the text to `name`, `salt`, `batch_number`, `mfd_date`, `exp_date`, and `dose`; values not explicitly present in the OCR text are discarded. The deterministic parser supplies fallback values when Gemini is not configured or extraction fails. Transient provider errors are retried, and each attempt is bounded by `GEMINI_TIMEOUT_SECONDS` (default `15`). Set `GEMINI_MODEL` to select the model. Keep the API key in the server environment only; never add it to Expo or any `EXPO_PUBLIC_*` setting.

Gemini only extracts text fields. Product matching and regulatory status continue to come from the server's indexed records; Gemini output is not a safety or authenticity verdict.

## Backend organization

The canonical workflow implementation lives in `routes/workflow.py`, `services/workflow_*.py`, and `repositories/workflow_repository.py`. Admin behavior is split between `routes/admin.py` and `services/admin_service.py`.

`pipeline/` and `controllers/` retain compatibility imports for older callers and tests. New server code should import from `routes/`, `services/`, and `repositories/` directly. These compatibility modules are intentional and should not be removed until their import paths are no longer supported.
