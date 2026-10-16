import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { ScreenHeader } from "../../components/ScreenHeader";
import { ApiError } from "../../services/api";
import {
  fetchScanHistory,
  fetchScanResult,
  toResultParams,
  type ScanHistoryEntry,
} from "../../services/medicine";
import { colors, radius, shadow, spacing, typography } from "../../theme";

const STATUS_META = {
  safe: {
    label: "Safe",
    icon: "shield-checkmark" as const,
    tint: colors.successText,
    surface: colors.successSurface,
    border: colors.successBorder,
  },
  unsafe: {
    label: "Flagged",
    icon: "alert-circle" as const,
    tint: colors.dangerText,
    surface: colors.dangerSurface,
    border: colors.dangerBorder,
  },
  unknown: {
    label: "Unverified",
    icon: "help-circle" as const,
    tint: colors.warningText,
    surface: colors.warningSurface,
    border: colors.warningBorder,
  },
};

const formatDate = (iso: string) => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
};

export default function HistoryScreen() {
  const router = useRouter();

  const [entries, setEntries] = useState<ScanHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openingId, setOpeningId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setEntries(await fetchScanHistory());
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not load your scan history.",
      );
    }
  }, []);

  // Refetch on focus so a scan just completed appears without a manual pull.
  useFocusEffect(
    useCallback(() => {
      let cancelled = false;
      (async () => {
        await load();
        if (!cancelled) setLoading(false);
      })();
      return () => {
        cancelled = true;
      };
    }, [load]),
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const openResult = async (item: ScanHistoryEntry) => {
    setOpeningId(item.id);
    try {
      const result = await fetchScanResult(item.id);
      router.push({
        pathname: "/result",
        params: toResultParams(result, { location: null }),
      });
    } catch (err) {
      Alert.alert(
        "Unable to load result",
        err instanceof ApiError ? err.message : "Please try opening this scan again.",
      );
    } finally {
      setOpeningId(null);
    }
  };

  const renderItem = ({ item }: { item: ScanHistoryEntry }) => {
    const meta = STATUS_META[item.status];
    const isOpening = openingId === item.id;

    return (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`Open results for ${item.name}`}
        accessibilityHint="Rechecks this scan against current regulatory records"
        disabled={openingId !== null}
        onPress={() => void openResult(item)}
        style={({ pressed }) => [styles.card, pressed && styles.cardPressed]}
      >
        <View
          style={[
            styles.statusStripe,
            { backgroundColor: meta.tint },
          ]}
        />
        <View style={styles.cardBody}>
          <View style={styles.cardHeader}>
            <Text style={styles.medicineName} numberOfLines={1}>
              {item.name}
              {item.dose ? (
                <Text style={styles.dose}>{`  ${item.dose}`}</Text>
              ) : null}
            </Text>
            <View
              style={[
                styles.badge,
                { backgroundColor: meta.surface, borderColor: meta.border },
              ]}
            >
              <Ionicons name={meta.icon} size={12} color={meta.tint} />
              <Text style={[styles.badgeText, { color: meta.tint }]}>
                {meta.label}
              </Text>
            </View>
          </View>

          <View style={styles.metaRow}>
            <Ionicons
              name="barcode-outline"
              size={14}
              color={colors.textMuted}
            />
            <Text style={styles.metaText}>{item.batchNumber}</Text>
          </View>
          <View style={styles.metaRow}>
            <Ionicons
              name="calendar-outline"
              size={14}
              color={colors.textMuted}
            />
            <Text style={styles.metaText}>{formatDate(item.scannedAt)}</Text>
          </View>
          <View style={styles.cardAction}>
            <Text style={styles.cardActionText}>
              {isOpening ? "Loading results..." : "View results"}
            </Text>
            {isOpening ? (
              <ActivityIndicator size="small" color={colors.primary} />
            ) : (
              <Ionicons name="chevron-forward" size={18} color={colors.primary} />
            )}
          </View>
        </View>
      </Pressable>
    );
  };

  return (
    <View style={styles.container}>
      <ScreenHeader
        title="History"
        subtitle={
          loading
            ? "Loading your scans..."
            : `${entries.length} ${entries.length === 1 ? "scan" : "scans"} on record`
        }
      />

      {loading ? (
        <View style={styles.centred}>
          <ActivityIndicator size="large" color={colors.primary} />
        </View>
      ) : (
        <FlatList
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
        data={entries}
        keyExtractor={(item) => item.id}
        renderItem={renderItem}
        contentContainerStyle={styles.listContent}
        showsVerticalScrollIndicator={false}
        ListEmptyComponent={
          <View style={styles.empty}>
            <View style={styles.emptyIcon}>
              <Ionicons
                name={error ? "cloud-offline-outline" : "time-outline"}
                size={32}
                color={colors.textMuted}
              />
            </View>
            <Text style={styles.emptyTitle}>
              {error ? "History unavailable" : "No scans yet"}
            </Text>
            <Text style={styles.emptyBody}>
              {error ??
                "Medicines you verify will show up here so you can look them up later."}
            </Text>
            <Pressable
              accessibilityRole="button"
              onPress={() => router.push("/(tabs)/scan")}
              style={styles.emptyAction}
            >
              <Text style={styles.emptyActionText}>Scan a medicine</Text>
            </Pressable>
          </View>
          }
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  listContent: { padding: spacing.xl, flexGrow: 1 },
  centred: { flex: 1, alignItems: "center", justifyContent: "center" },

  card: {
    flexDirection: "row",
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
    ...shadow.card,
  },
  cardPressed: { opacity: 0.78 },
  statusStripe: { width: 4 },
  cardBody: { flex: 1, padding: spacing.lg },
  cardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: spacing.md,
  },
  medicineName: {
    ...typography.heading,
    fontSize: 16,
    color: colors.text,
    flex: 1,
    paddingRight: spacing.md,
  },
  dose: { ...typography.caption, color: colors.textMuted, fontWeight: "500" },
  badge: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: radius.pill,
    borderWidth: 1,
  },
  badgeText: {
    ...typography.caption,
    fontSize: 11,
    marginLeft: 4,
    fontWeight: "700",
  },
  metaRow: { flexDirection: "row", alignItems: "center", marginTop: 2 },
  metaText: {
    ...typography.caption,
    color: colors.textSecondary,
    marginLeft: spacing.sm,
  },
  cardAction: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-end",
    marginTop: spacing.md,
    gap: spacing.xs,
  },
  cardActionText: { ...typography.caption, color: colors.primary, fontWeight: "700" },

  empty: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.xl,
  },
  emptyIcon: {
    width: 72,
    height: 72,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceMuted,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.lg,
  },
  emptyTitle: { ...typography.title, color: colors.text },
  emptyBody: {
    ...typography.body,
    color: colors.textSecondary,
    textAlign: "center",
    lineHeight: 22,
    marginTop: spacing.sm,
  },
  emptyAction: { marginTop: spacing.lg, padding: spacing.md },
  emptyActionText: { ...typography.heading, fontSize: 15, color: colors.primary },
});
