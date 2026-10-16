import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { ScreenHeader } from "../../components/ScreenHeader";
import { colors, radius, spacing, typography } from "../../theme";

export default function HomeScreen() {
  const router = useRouter();

  return (
    <View style={styles.container}>
      <ScreenHeader
        title="MediCheck"
        subtitle="Check a medicine before you take it."
      />
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.intro}>
          <View style={styles.introIcon}>
            <Ionicons name="shield-checkmark" size={30} color={colors.primary} />
          </View>
          <Text style={styles.title}>Verify with confidence</Text>
          <Text style={styles.body}>
            Scan a pack or enter its batch number to check available regulatory
            and quality records.
          </Text>
          <Pressable
            accessibilityRole="button"
            onPress={() => router.navigate("/(tabs)/scan")}
            style={({ pressed }) => [styles.scanButton, pressed && styles.pressed]}
          >
            <Ionicons name="scan-outline" size={20} color={colors.textInverse} />
            <Text style={styles.scanButtonText}>Scan a medicine</Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            onPress={() => router.navigate("/(tabs)/manual-entry")}
            style={({ pressed }) => [styles.manualButton, pressed && styles.pressed]}
          >
            <Text style={styles.manualButtonText}>Enter batch details</Text>
            <Ionicons name="arrow-forward" size={18} color={colors.primary} />
          </Pressable>
        </View>

        <Pressable
          accessibilityRole="button"
          onPress={() => router.navigate("/(tabs)/history")}
          style={({ pressed }) => [styles.historyRow, pressed && styles.pressed]}
        >
          <View style={styles.historyIcon}>
            <Ionicons name="time-outline" size={22} color={colors.primary} />
          </View>
          <View style={styles.historyText}>
            <Text style={styles.historyTitle}>Search & scan history</Text>
            <Text style={styles.historyBody}>Review previous checks</Text>
          </View>
          <Ionicons name="chevron-forward" size={20} color={colors.textMuted} />
        </Pressable>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  content: { padding: spacing.xl, flexGrow: 1 },
  intro: {
    alignItems: "flex-start",
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderColor: colors.border,
    borderWidth: 1,
    padding: spacing.xl,
  },
  introIcon: {
    width: 58,
    height: 58,
    borderRadius: radius.md,
    backgroundColor: colors.primarySurface,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.lg,
  },
  title: { ...typography.title, color: colors.text },
  body: {
    ...typography.body,
    color: colors.textSecondary,
    lineHeight: 23,
    marginTop: spacing.sm,
  },
  scanButton: {
    alignSelf: "stretch",
    minHeight: 52,
    marginTop: spacing.xl,
    borderRadius: radius.sm,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: spacing.sm,
  },
  scanButtonText: { ...typography.heading, color: colors.textInverse },
  manualButton: {
    minHeight: 48,
    alignSelf: "stretch",
    justifyContent: "center",
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginTop: spacing.xs,
  },
  manualButtonText: { ...typography.body, color: colors.primary, fontWeight: "600" },
  historyRow: {
    minHeight: 78,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.borderStrong,
    marginTop: spacing.xl,
    paddingHorizontal: spacing.sm,
  },
  historyIcon: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  historyText: { flex: 1, marginLeft: spacing.md },
  historyTitle: { ...typography.heading, color: colors.text },
  historyBody: { ...typography.caption, color: colors.textMuted, marginTop: 3 },
  pressed: { opacity: 0.76 },
});