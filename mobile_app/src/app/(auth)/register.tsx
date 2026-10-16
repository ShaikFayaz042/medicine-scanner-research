import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
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
import { AppButton } from "../../components/ui/AppButton";
import { TextField } from "../../components/ui/TextField";
import { ApiError } from "../../services/api";
import { ONBOARDING_KEY, register } from "../../services/auth";
import { colors, radius, spacing, typography } from "../../theme";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MIN_PASSWORD_LENGTH = 8;

type Errors = Partial<
  Record<"name" | "email" | "password" | "confirmPassword", string>
>;

export default function RegisterScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [submitting, setSubmitting] = useState(false);

  const strength = useMemo(() => {
    if (!password) return 0;
    let score = 0;
    if (password.length >= MIN_PASSWORD_LENGTH) score += 1;
    if (/[A-Z]/.test(password) && /[a-z]/.test(password)) score += 1;
    if (/\d/.test(password)) score += 1;
    if (/[^A-Za-z0-9]/.test(password)) score += 1;
    return score;
  }, [password]);

  const strengthMeta = [
    { label: "Too short", color: colors.danger },
    { label: "Weak", color: colors.danger },
    { label: "Fair", color: colors.warning },
    { label: "Good", color: colors.primary },
    { label: "Strong", color: colors.success },
  ][strength];

  const clearError = useCallback(
    (key: keyof Errors) => setErrors((e) => ({ ...e, [key]: undefined })),
    [],
  );

  const handleRegister = useCallback(async () => {
    const nextErrors: Errors = {};

    if (!name.trim()) nextErrors.name = "Enter your name.";
    if (!email.trim()) nextErrors.email = "Enter your email address.";
    else if (!EMAIL_RE.test(email.trim()))
      nextErrors.email = "That does not look like a valid email address.";
    if (password.length < MIN_PASSWORD_LENGTH)
      nextErrors.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
    if (confirmPassword !== password)
      nextErrors.confirmPassword = "Passwords do not match.";

    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    setSubmitting(true);
    try {
      // Creates the account and persists the returned session token.
      await register(name.trim(), email.trim(), password);

      // A brand new account always sees the scanning guide first.
      await AsyncStorage.removeItem(ONBOARDING_KEY);
      router.replace("/instructions");
    } catch (error) {
      Alert.alert(
        "Could not create your account",
        error instanceof ApiError
          ? error.message
          : "Something went wrong creating your account. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }, [confirmPassword, email, name, password, router]);

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      style={styles.container}
    >
      <ScrollView
        contentContainerStyle={[
          styles.content,
          {
            paddingTop: insets.top + spacing.lg,
            paddingBottom: insets.bottom + spacing.xxl,
          },
        ]}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Go back"
          hitSlop={8}
          style={styles.backButton}
          onPress={() => router.back()}
        >
          <Ionicons name="arrow-back" size={22} color={colors.text} />
        </Pressable>

        <Text style={styles.title}>Create account</Text>
        <Text style={styles.subtitle}>
          Join MediCheck to verify medicines and keep a record of every scan.
        </Text>

        <TextField
          label="Full name"
          placeholder="e.g. Jane Doe"
          icon="person-outline"
          value={name}
          onChangeText={(value) => {
            setName(value);
            if (errors.name) clearError("name");
          }}
          error={errors.name}
          autoCapitalize="words"
          autoComplete="name"
          returnKeyType="next"
        />

        <TextField
          label="Email"
          placeholder="you@example.com"
          icon="mail-outline"
          value={email}
          onChangeText={(value) => {
            setEmail(value);
            if (errors.email) clearError("email");
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
          placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
          icon="lock-closed-outline"
          secure
          value={password}
          onChangeText={(value) => {
            setPassword(value);
            if (errors.password) clearError("password");
          }}
          error={errors.password}
          autoComplete="new-password"
          textContentType="newPassword"
          returnKeyType="next"
        />

        {password ? (
          <View style={styles.strength}>
            <View style={styles.strengthTrack}>
              <View
                style={[
                  styles.strengthFill,
                  {
                    width: `${(strength / 4) * 100}%`,
                    backgroundColor: strengthMeta.color,
                  },
                ]}
              />
            </View>
            <Text style={[styles.strengthLabel, { color: strengthMeta.color }]}>
              {strengthMeta.label}
            </Text>
          </View>
        ) : null}

        <TextField
          label="Confirm password"
          placeholder="Repeat your password"
          icon="lock-closed-outline"
          secure
          value={confirmPassword}
          onChangeText={(value) => {
            setConfirmPassword(value);
            if (errors.confirmPassword) clearError("confirmPassword");
          }}
          error={errors.confirmPassword}
          autoComplete="new-password"
          textContentType="newPassword"
          returnKeyType="go"
          onSubmitEditing={handleRegister}
        />

        <AppButton
          label="Sign up"
          onPress={handleRegister}
          loading={submitting}
          style={styles.submit}
        />

        <View style={styles.footer}>
          <Text style={styles.footerText}>Already have an account? </Text>
          <Pressable
            accessibilityRole="link"
            hitSlop={8}
            onPress={() => router.replace("/(auth)/login")}
          >
            <Text style={styles.footerLink}>Log in</Text>
          </Pressable>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  content: { paddingHorizontal: spacing.xl, flexGrow: 1 },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
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
  strength: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: -spacing.sm,
    marginBottom: spacing.lg,
  },
  strengthTrack: {
    flex: 1,
    height: 4,
    borderRadius: radius.pill,
    backgroundColor: colors.border,
    overflow: "hidden",
  },
  strengthFill: { height: "100%", borderRadius: radius.pill },
  strengthLabel: {
    ...typography.caption,
    marginLeft: spacing.md,
    minWidth: 62,
    textAlign: "right",
  },
  submit: { marginTop: spacing.sm },
  footer: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    marginTop: spacing.xl,
  },
  footerText: { ...typography.body, color: colors.textSecondary },
  footerLink: { ...typography.body, color: colors.primary, fontWeight: "700" },
});
