const GOOGLE_WEB_CLIENT_ID = process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID ?? "";

export async function signInWithGoogleNative(): Promise<string | null> {
  if (!GOOGLE_WEB_CLIENT_ID) {
    throw new Error(
      "Google sign-in is not configured in this build. Add EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID to the EAS build environment and rebuild the app.",
    );
  }

  let googleSignInModule: typeof import("@react-native-google-signin/google-signin");
  try {
    googleSignInModule = await import("@react-native-google-signin/google-signin");
  } catch {
    throw new Error(
      "Native Google Sign-In is unavailable in Expo Go. Install the EAS development build to use Google sign-in.",
    );
  }

  const { GoogleSignin } = googleSignInModule;
  GoogleSignin.configure({ webClientId: GOOGLE_WEB_CLIENT_ID });
  await GoogleSignin.hasPlayServices({ showPlayServicesUpdateDialog: true });
  await GoogleSignin.signOut();

  const result = await GoogleSignin.signIn();
  if (result.type === "cancelled") return null;

  const idToken = result.data.idToken;
  if (!idToken) {
    throw new Error(
      "Google did not return an ID token. Check the Web OAuth client configuration.",
    );
  }

  return idToken;
}