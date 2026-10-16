import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef } from "react";
import { ActivityIndicator, Alert, StyleSheet, Text, View } from "react-native";
import {
  ONBOARDING_KEY,
  consumeGoogleWebSession,
} from "../../services/auth";
import { ApiError } from "../../services/api";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { colors, spacing, typography } from "../../theme";

export default function GoogleOAuthReturn() {
  const router = useRouter();
  const { google_oauth: result } = useLocalSearchParams<{ google_oauth?: string }>();
  const handled = useRef(false);

  useEffect(() => {
    if (!result || handled.current) return;
    handled.current = true;

    const finish = async () => {
      if (result === "cancelled") {
        router.replace("/(auth)/login");
        return;
      }
      if (result !== "complete") {
        Alert.alert("Could not sign in with Google", "Please try again.");
        router.replace("/(auth)/login");
        return;
      }

      try {
        await consumeGoogleWebSession();
        const hasSeenOnboarding = await AsyncStorage.getItem(ONBOARDING_KEY);
        router.replace(hasSeenOnboarding ? "/(tabs)/home" : "/instructions");
      } catch (error) {
        Alert.alert(
          "Could not sign in with Google",
          error instanceof ApiError ? error.message : "Please try again.",
        );
        router.replace("/(auth)/login");
      }
    };

    void finish();
  }, [result, router]);

  return (
    <View style={styles.container}>
      <ActivityIndicator color={colors.primary} />
      <Text style={styles.label}>Completing sign-in...</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.md,
    backgroundColor: colors.background,
  },
  label: { ...typography.body, color: colors.textSecondary },
});