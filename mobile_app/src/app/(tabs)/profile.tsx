import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AuthUser, signOut, verifyStoredSession } from "../../services/auth";
import { colors, radius, spacing, typography } from "../../theme";

type ProfileRowProps = {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  detail?: string;
  onPress: () => void;
};

function ProfileRow({ icon, title, detail, onPress }: ProfileRowProps) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
    >
      <Ionicons name={icon} size={25} color={colors.text} style={styles.rowIcon} />
      <View style={styles.rowCopy}>
        <Text style={styles.rowTitle}>{title}</Text>
        {detail ? <Text style={styles.rowDetail}>{detail}</Text> : null}
      </View>
      <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
    </Pressable>
  );
}

export default function ProfileScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [signingOut, setSigningOut] = useState(false);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      verifyStoredSession()
        .then((signedInUser) => {
          if (!active) return;
          setUser(signedInUser);
        })
        .catch(() => {
          if (active) setUser(null);
        })
        .finally(() => {
          if (active) setLoading(false);
        });
      return () => {
        active = false;
      };
    }, []),
  );

  const performSignOut = async () => {
    setSigningOut(true);
    try {
      await signOut();
      router.replace("/(auth)/login");
    } catch {
      setSigningOut(false);
      if (Platform.OS === "web") {
        window.alert("Could not log out. Please try again.");
      } else {
        Alert.alert("Could not log out", "Please try again.");
      }
    }
  };

  const confirmSignOut = () => {
    if (Platform.OS === "web") {
      if (window.confirm("Log out? You will need to sign in again to use your account.")) {
        void performSignOut();
      }
      return;
    }

    Alert.alert("Log out", "You will need to sign in again to use your account.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Log out",
        style: "destructive",
        onPress: () => void performSignOut(),
      },
    ]);
  };

  return (
    <View style={styles.container}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.sm }]}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Back to home"
          hitSlop={8}
          onPress={() => router.navigate("/(tabs)/home")}
          style={styles.backButton}
        >
          <Ionicons name="arrow-back" size={25} color={colors.text} />
          <Text style={styles.backText}>Back</Text>
        </Pressable>
        <Text style={styles.headerTitle}>Profile</Text>
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.identity}>
          <View style={styles.avatar}>
            {loading ? (
              <ActivityIndicator color={colors.textSecondary} />
            ) : (
              <Ionicons name="person-outline" size={37} color={colors.textSecondary} />
            )}
          </View>
          <View style={styles.identityCopy}>
            <Text style={styles.name}>{user?.name ?? "Account"}</Text>
            <Text style={styles.status}>{user ? "Active User" : "Sign-in required"}</Text>
            {user?.email ? <Text style={styles.email}>{user.email}</Text> : null}
          </View>
        </View>

        <View style={styles.aboutBox}>
          <Text style={styles.aboutTitle}>About this app</Text>
          <Text style={styles.aboutText}>
            <Text style={styles.aboutEmphasis}>MediCheck</Text> helps you
            search and scan for indexed regulatory alerts, quality issues, and
            official drug notices from verified healthcare databases. This app
            is for informational purposes and does not provide medical advice.
          </Text>
        </View>

        <View style={styles.rows}>
          <ProfileRow
            icon="language-outline"
            title="Language"
            detail="English"
            onPress={() =>
              Alert.alert("Language", "MediCheck is currently available in English.")
            }
          />
          <ProfileRow
            icon="time-outline"
            title="Search & scan history"
            onPress={() => router.navigate("/(tabs)/history")}
          />
          <ProfileRow
            icon="server-outline"
            title="Official data sources"
            onPress={() =>
              Alert.alert(
                "Official data sources",
                "MediCheck indexes public regulatory alerts and quality notices. Always confirm a notice with the issuing healthcare authority.",
              )
            }
          />
          <ProfileRow
            icon="document-text-outline"
            title="Terms & disclaimer"
            onPress={() =>
              Alert.alert(
                "Terms & disclaimer",
                "Information is provided for general reference only, may be incomplete or delayed, and is not medical advice. Consult a licensed healthcare professional before making treatment decisions.",
              )
            }
          />
          <ProfileRow
            icon="information-circle-outline"
            title="About MediCheck"
            onPress={() =>
              Alert.alert(
                "MediCheck",
                "A medicine verification tool for searching indexed regulatory and quality records.",
              )
            }
          />
        </View>

        <Pressable
          accessibilityRole="button"
          disabled={signingOut}
          onPress={confirmSignOut}
          style={({ pressed }) => [styles.logout, pressed && styles.rowPressed]}
        >
          {signingOut ? (
            <ActivityIndicator color={colors.textSecondary} />
          ) : (
            <Text style={styles.logoutText}>Log out</Text>
          )}
        </Pressable>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  header: {
    backgroundColor: colors.surface,
    minHeight: 62,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.md,
    flexDirection: "row",
    alignItems: "center",
  },
  backButton: { flexDirection: "row", alignItems: "center", marginRight: spacing.lg },
  backText: { ...typography.heading, fontSize: 16, color: colors.text, marginLeft: spacing.sm },
  headerTitle: { ...typography.title, fontSize: 20, color: colors.text },
  content: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xl },
  identity: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xl,
  },
  avatar: {
    width: 78,
    height: 78,
    borderRadius: 39,
    borderWidth: 1.5,
    borderColor: colors.borderStrong,
    backgroundColor: colors.surfaceMuted,
    alignItems: "center",
    justifyContent: "center",
  },
  identityCopy: { flex: 1, marginLeft: spacing.lg },
  name: { ...typography.title, fontSize: 21, color: colors.text },
  status: { ...typography.body, color: colors.textSecondary, marginTop: 2 },
  email: { ...typography.caption, color: colors.textMuted, marginTop: 2 },
  aboutBox: {
    backgroundColor: colors.surfaceMuted,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.md,
    padding: spacing.lg,
  },
  aboutTitle: { ...typography.heading, fontSize: 19, color: colors.text },
  aboutText: {
    ...typography.body,
    color: colors.text,
    fontSize: 15,
    lineHeight: 21,
    marginTop: spacing.sm,
  },
  aboutEmphasis: { fontWeight: "700" },
  rows: { marginTop: spacing.xl },
  row: {
    minHeight: 70,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.borderStrong,
    paddingHorizontal: spacing.md,
  },
  rowIcon: { width: 42 },
  rowCopy: { flex: 1, paddingVertical: spacing.sm },
  rowTitle: { ...typography.heading, fontSize: 16, color: colors.text },
  rowDetail: { ...typography.caption, color: colors.textSecondary, marginTop: 3 },
  rowPressed: { opacity: 0.68 },
  logout: { minHeight: 64, alignItems: "center", justifyContent: "center" },
  logoutText: { ...typography.heading, fontSize: 17, color: colors.textSecondary },
});