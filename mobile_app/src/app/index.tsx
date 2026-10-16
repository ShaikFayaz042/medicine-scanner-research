import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useRouter } from "expo-router";
import { useEffect } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import {
  ONBOARDING_KEY,
  getStoredToken,
  verifyStoredSession,
} from "../services/auth";
import { colors, radius, spacing, typography } from "../theme";

export default function Index() {
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;

    const route = async () => {
      let destination: "/(auth)/login" | "/instructions" | "/(tabs)/home" =
        "/(auth)/login";

      try {
        const token = await getStoredToken();

        if (token) {
          // A token can be structurally valid but useless - expired, or for a
          // deleted account. Ask the server before dropping the user into the
          // scanner, where every call would then fail with a 401.
          const user = await verifyStoredSession();

          if (user) {
            const hasSeenOnboarding =
              await AsyncStorage.getItem(ONBOARDING_KEY);
            destination = hasSeenOnboarding ? "/(tabs)/home" : "/instructions";
          } else {
            // Either the session was rejected (and has been cleared), or we are
            // offline. Both mean the safe landing place is the login screen.
            destination = "/(auth)/login";
          }
        }
      } catch (error) {
        console.error("Session check failed:", error);
      }

      if (!cancelled) router.replace(destination);
    };

    route();
    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <View style={styles.container}>
      <View style={styles.logo}>
        <Ionicons name="shield-checkmark" size={44} color={colors.primary} />
      </View>
      <Text style={styles.title}>MediCheck</Text>
      <Text style={styles.tagline}>Scan. Verify. Take with confidence.</Text>
      <ActivityIndicator
        size="small"
        color={colors.primary}
        style={styles.spinner}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: colors.background,
    padding: spacing.xl,
  },
  logo: {
    width: 92,
    height: 92,
    borderRadius: radius.xl,
    backgroundColor: colors.primarySurface,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.xl,
  },
  title: { ...typography.display, color: colors.text },
  tagline: {
    ...typography.body,
    color: colors.textSecondary,
    marginTop: spacing.sm,
  },
  spinner: { marginTop: spacing.xxl },
});
