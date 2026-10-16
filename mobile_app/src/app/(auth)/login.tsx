import { FontAwesome5, Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Google from "expo-auth-session/providers/google";
import { useRouter } from "expo-router";
import { useCallback, useState } from "react";
import {
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import * as WebBrowser from "expo-web-browser";
import { AppButton } from "../../components/ui/AppButton";
import { TextField } from "../../components/ui/TextField";
import { ApiError } from "../../services/api";
import {
  ONBOARDING_KEY,
  login,
  loginWithGoogle,
  startGoogleWebLogin,
} from "../../services/auth";
import { signInWithGoogleNative } from "../../services/googleSignIn";
import { colors, radius, shadow, spacing, typography } from "../../theme";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const GOOGLE_CLIENT_ID_PLACEHOLDER = "google-client-id-not-configured";
const GOOGLE_WEB_CLIENT_ID = process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID ?? "";
const GOOGLE_ANDROID_CLIENT_ID =
  process.env.EXPO_PUBLIC_GOOGLE_ANDROID_CLIENT_ID ?? "";
const GOOGLE_IOS_CLIENT_ID = process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID ?? "";

WebBrowser.maybeCompleteAuthSession();

export default function LoginScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string; password?: string }>(
    {},
  );
  const [submitting, setSubmitting] = useState(false);

  const signIn = useCallback(
    async (authenticate: () => Promise<unknown>) => {
      setSubmitting(true);
      try {
        // The session token is persisted by the auth service.
        await authenticate();

        const hasSeenOnboarding = await AsyncStorage.getItem(ONBOARDING_KEY);
        router.replace(hasSeenOnboarding ? "/(tabs)/home" : "/instructions");
      } catch (error) {
        Alert.alert(
          "Could not sign in",
          error instanceof ApiError
            ? error.message
            : "Something went wrong signing you in. Please try again.",
        );
      } finally {
        setSubmitting(false);
      }
    },
    [router],
  );

  const handleLogin = useCallback(() => {
    const nextErrors: { email?: string; password?: string } = {};
    if (!email.trim()) nextErrors.email = "Enter your email address.";
    else if (!EMAIL_RE.test(email.trim()))
      nextErrors.email = "That does not look like a valid email address.";
    if (!password) nextErrors.password = "Enter your password.";

    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    signIn(() => login(email.trim(), password));
  }, [email, password, signIn]);

  const handleGoogleWebLogin = useCallback(() => {
    try {
      setSubmitting(true);
      startGoogleWebLogin();
    } catch (error) {
      Alert.alert(
        "Could not sign in with Google",
        error instanceof Error
          ? error.message
          : "The sign-in service is unavailable.",
      );
      setSubmitting(false);
    }
  }, []);

  const handleSocialLogin = useCallback(
    (provider: string) => {
      Alert.alert(
        "Not available yet",
        `${provider} sign-in has not been set up for this app.`,
      );
    },
    [],
  );

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      style={styles.container}
    >
      <ScrollView
        contentContainerStyle={[
          styles.content,
          {
            paddingTop: insets.top + spacing.xxl,
            paddingBottom: insets.bottom + spacing.xxl,
          },
        ]}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.logo}>
          <Ionicons name="shield-checkmark" size={32} color={colors.primary} />
        </View>

        <Text style={styles.title}>Welcome back</Text>
        <Text style={styles.subtitle}>
          Sign in to verify medicines and keep your scan history.
        </Text>

        <View style={styles.form}>
          <TextField
            label="Email"
            placeholder="you@example.com"
            icon="mail-outline"
            value={email}
            onChangeText={(value) => {
              setEmail(value);
              if (errors.email) setErrors((e) => ({ ...e, email: undefined }));
            }}
            error={errors.email}
            keyboardType="email-address"
            autoCapitalize="none"
            autoComplete="email"
            textContentType="emailAddress"
            returnKeyType="next"
          />

          <TextField
            label="Password"
            placeholder="Your password"
            icon="lock-closed-outline"
            secure
            value={password}
            onChangeText={(value) => {
              setPassword(value);
              if (errors.password)
                setErrors((e) => ({ ...e, password: undefined }));
            }}
            error={errors.password}
            autoComplete="current-password"
            textContentType="password"
            returnKeyType="go"
            onSubmitEditing={handleLogin}
          />

          <AppButton
            label="Log in"
            onPress={handleLogin}
            loading={submitting}
            style={styles.submit}
          />
        </View>

        <View style={styles.divider}>
          <View style={styles.dividerLine} />
          <Text style={styles.dividerText}>or continue with</Text>
          <View style={styles.dividerLine} />
        </View>

        {Platform.OS === "web" ? (
          <GoogleButton
            disabled={submitting}
            onPress={handleGoogleWebLogin}
          />
        ) : Platform.OS === "android" ? (
          <AndroidGoogleButton
            disabled={submitting}
            onSignIn={(idToken) => signIn(() => loginWithGoogle(idToken))}
          />
        ) : (
          <IosGoogleButton
            disabled={submitting}
            onSignIn={(idToken) => signIn(() => loginWithGoogle(idToken))}
          />
        )}

        <Pressable
          accessibilityRole="button"
          disabled={submitting}
          onPress={() => handleSocialLogin("Apple")}
          style={({ pressed }) => [
            styles.socialButton,
            pressed && styles.pressed,
          ]}
        >
          <FontAwesome5 name="apple" size={20} color={colors.text} />
          <Text style={styles.socialText}>Continue with Apple</Text>
        </Pressable>

        <View style={styles.footer}>
          <Text style={styles.footerText}>New to MediCheck? </Text>
          <Pressable
            accessibilityRole="link"
            hitSlop={8}
            onPress={() => router.push("/(auth)/register")}
          >
            <Text style={styles.footerLink}>Create an account</Text>
          </Pressable>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function GoogleButton({
  disabled,
  onPress,
}: {
  disabled: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [styles.socialButton, pressed && styles.pressed]}
    >
      <FontAwesome5 name="google" size={18} color="#db4437" />
      <Text style={styles.socialText}>Continue with Google</Text>
    </Pressable>
  );
}

function AndroidGoogleButton({
  disabled,
  onSignIn,
}: {
  disabled: boolean;
  onSignIn: (idToken: string) => Promise<void>;
}) {
  const handlePress = async () => {
    try {
      const idToken = await signInWithGoogleNative();
      if (idToken) await onSignIn(idToken);
    } catch (error) {
      Alert.alert(
        "Could not sign in with Google",
        error instanceof Error
          ? error.message
          : "Something went wrong signing you in. Please try again.",
      );
    }
  };

  return <GoogleButton disabled={disabled} onPress={() => void handlePress()} />;
}

function IosGoogleButton({
  disabled,
  onSignIn,
}: {
  disabled: boolean;
  onSignIn: (idToken: string) => Promise<void>;
}) {
  const [request, , promptGoogleAsync] = Google.useIdTokenAuthRequest(
    {
      webClientId: GOOGLE_WEB_CLIENT_ID || GOOGLE_CLIENT_ID_PLACEHOLDER,
      androidClientId:
        GOOGLE_ANDROID_CLIENT_ID || GOOGLE_CLIENT_ID_PLACEHOLDER,
      iosClientId: GOOGLE_IOS_CLIENT_ID || GOOGLE_CLIENT_ID_PLACEHOLDER,
    },
    { scheme: "medicheck" },
  );
  const clientId =
    Platform.OS === "ios" ? GOOGLE_IOS_CLIENT_ID : GOOGLE_ANDROID_CLIENT_ID;

  const handlePress = async () => {
    if (!clientId) {
      const platform = Platform.OS.toUpperCase();
      Alert.alert(
        "Google sign-in isn't configured",
        `Set EXPO_PUBLIC_GOOGLE_${platform}_CLIENT_ID in mobile_app/.env and restart Expo.`,
      );
      return;
    }
    if (!request) return;

    try {
      const result = await promptGoogleAsync();
      if (result.type === "cancel" || result.type === "dismiss") return;
      if (result.type === "error") {
        throw new Error(
          result.error?.message ??
            result.params.error_description ??
            "Google sign-in could not be completed.",
        );
      }
      if (result.type !== "success") return;

      const idToken = result.authentication?.idToken ?? result.params.id_token;
      if (!idToken) {
        throw new Error(
          "Google did not return an ID token. Check the OAuth client and redirect URI configuration.",
        );
      }

      await onSignIn(idToken);
    } catch (error) {
      Alert.alert(
        "Could not sign in with Google",
        error instanceof Error
          ? error.message
          : "Something went wrong signing you in. Please try again.",
      );
    }
  };

  return <GoogleButton disabled={disabled} onPress={() => void handlePress()} />;
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  content: { paddingHorizontal: spacing.xl, flexGrow: 1 },
  logo: {
    width: 64,
    height: 64,
    borderRadius: radius.lg,
    backgroundColor: colors.primarySurface,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.xl,
  },
  title: { ...typography.display, color: colors.text },
  subtitle: {
    ...typography.body,
    color: colors.textSecondary,
    marginTop: spacing.sm,
    marginBottom: spacing.xxl,
    lineHeight: 22,
  },
  form: { marginBottom: spacing.sm },
  submit: { marginTop: spacing.sm },

  divider: {
    flexDirection: "row",
    alignItems: "center",
    marginVertical: spacing.xl,
  },
  dividerLine: { flex: 1, height: 1, backgroundColor: colors.border },
  dividerText: {
    ...typography.caption,
    color: colors.textMuted,
    marginHorizontal: spacing.md,
  },

  socialButton: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    minHeight: 52,
    borderRadius: radius.md,
    marginBottom: spacing.md,
    ...shadow.card,
  },
  pressed: { opacity: 0.85 },
  socialText: {
    ...typography.heading,
    fontSize: 15,
    color: colors.text,
    marginLeft: spacing.md,
  },

  footer: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    marginTop: spacing.xl,
  },
  footerText: { ...typography.body, color: colors.textSecondary },
  footerLink: { ...typography.body, color: colors.primary, fontWeight: "700" },
});
