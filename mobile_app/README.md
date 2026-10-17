# MediCheck Mobile App

## Local setup

```powershell
npm ci
Copy-Item .env.example .env
npm run start
```

Set `EXPO_PUBLIC_API_URL` in `.env` to the backend URL reachable from the device. For a physical device, use the computer's LAN address rather than `localhost`. Local HTTP is enabled only when this URL uses `http://`; release builds should use HTTPS.

The local `.env` value is for development only. Production Android builds use the Render HTTPS URL configured in the EAS production profile.

## EAS builds

Install and authenticate the EAS CLI:

```powershell
npm install --global eas-cli
eas login
```

In the Expo project's EAS environment settings, configure these public build-time variables for the environments where they are used:

- `EXPO_PUBLIC_API_URL`: a development backend URL reachable from the installed development APK; use your computer's LAN address when testing a local server. The production profile sets the deployed Render URL.
- `EXPO_PUBLIC_API_URL_WEB`: the backend URL used by the web build
- `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID`: Google web OAuth client ID
- `EXPO_PUBLIC_GOOGLE_ANDROID_CLIENT_ID`: Google Android OAuth client ID
- `EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID`: Google iOS OAuth client ID

These `EXPO_PUBLIC_*` values are embedded in the application and must not contain secrets. Configure the backend's Google OAuth settings separately. Register the EAS Android signing certificate with Google OAuth before enabling native Google sign-in.

Build from this directory:

```powershell
npm run build:development:apk
npm run build:production:apk
npm run build:development
npm run build:preview
npm run build:production
```

The Android APK commands create installable development-client and production APKs. The production profile uses the EAS `production` environment and automatically increments the remote app version. The app is linked to its EAS project in `app.json`; its iOS bundle identifier and Android package are both `com.fayaz.medicheck`.

## Store submission

Before submission, configure the Apple App Store Connect and Google Play credentials with EAS, complete each store's listing and privacy requirements, and verify the production API and OAuth configuration. Then run:

```powershell
npm run submit:production
```

Validate changes locally with `npm run lint` and `npx expo-doctor` before building.
