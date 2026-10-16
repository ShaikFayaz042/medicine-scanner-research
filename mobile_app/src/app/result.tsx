import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useMemo, useState } from "react";
import {
  Alert,
  Linking,
  Pressable,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import type { VerificationStatus } from "../services/medicine";
import { colors, radius, shadow, spacing, typography } from "../theme";

type JsonObject = Record<string, unknown>;
type Indicator = "RED" | "YELLOW" | "GREEN" | "UNKNOWN";

const asText = (value: string | string[] | undefined) =>
  (Array.isArray(value) ? value[0] : value) ?? "";

const asString = (value: unknown) =>
  typeof value === "string" || typeof value === "number" ? String(value) : "";

const asObject = (value: unknown): JsonObject | null =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : null;

const isStatus = (value: string): value is VerificationStatus =>
  value === "safe" || value === "unsafe" || value === "unknown";

const INDICATOR_STYLES: Record<
  Indicator,
  { label: string; title: string; tint: string; surface: string; icon: keyof typeof Ionicons.glyphMap }
> = {
  RED: {
    label: "RED",
    title: "Regulatory restriction recorded",
    tint: colors.dangerText,
    surface: colors.dangerSurface,
    icon: "alert-circle",
  },
  YELLOW: {
    label: "YELLOW",
    title: "Caution / quality alert",
    tint: colors.warningText,
    surface: colors.warningSurface,
    icon: "alert-circle",
  },
  GREEN: {
    label: "GREEN",
    title: "No indexed alert found",
    tint: colors.successText,
    surface: colors.successSurface,
    icon: "checkmark-circle",
  },
  UNKNOWN: {
    label: "UNKNOWN",
    title: "Review regulatory records",
    tint: colors.textSecondary,
    surface: colors.surfaceMuted,
    icon: "help-circle",
  },
};

const NAV_ITEMS = [
  { label: "Scan", icon: "scan-outline" as const, route: "/(tabs)/scan" as const },
  { label: "Enter", icon: "create-outline" as const, route: "/(tabs)/manual-entry" as const },
  { label: "History", icon: "time-outline" as const, route: "/(tabs)/history" as const },
];

export default function ResultScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const insets = useSafeAreaInsets();
  const [expandedEvents, setExpandedEvents] = useState<Set<string>>(new Set());

  const matches = useMemo<JsonObject[]>(() => {
    try {
      const parsed: unknown = JSON.parse(asText(params.matches as string | string[] | undefined) || "[]");
      return Array.isArray(parsed)
        ? parsed.map(asObject).filter((item): item is JsonObject => item !== null)
        : [];
    } catch {
      return [];
    }
  }, [params.matches]);

  const fields = {
    name: asText(params.name as string | string[] | undefined),
    salt: asText(params.salt as string | string[] | undefined),
    dose: asText(params.dose as string | string[] | undefined),
    batchNumber: asText(params.batchNumber as string | string[] | undefined),
    mfdDate: asText(params.mfdDate as string | string[] | undefined),
    expDate: asText(params.expDate as string | string[] | undefined),
    gtin: asText(params.gtin as string | string[] | undefined),
    serial: asText(params.serial as string | string[] | undefined),
  };

  const firstMatch = matches[0];
  const product = asObject(firstMatch?.product);
  const assessment = asObject(firstMatch?.assessment);
  const statusParam = asText(params.status as string | string[] | undefined);
  const status: VerificationStatus = isStatus(statusParam) ? statusParam : "unknown";
  const rawIndicator = asString(assessment?.indicator).toUpperCase();
  const indicator: Indicator =
    rawIndicator === "RED" || rawIndicator === "YELLOW" || rawIndicator === "GREEN"
      ? rawIndicator
      : status === "unsafe"
        ? "RED"
        : "UNKNOWN";
  const visuals = INDICATOR_STYLES[indicator];
  const title = fields.name || asString(product?.name) || "Medicine scan results";
  const dose = fields.dose || asString(product?.strength);
  const heading = dose && !title.toLowerCase().includes(dose.toLowerCase())
    ? `${title} ${dose}`
    : title;
  const summary =
    asString(assessment?.summary) ||
    asText(params.message as string | string[] | undefined) ||
    "No regulatory assessment was returned for this scan.";
  const disclaimer =
    asString(assessment?.disclaimer) ||
    "Based on regulatory records currently available in the system. This is not medical advice. Consult your doctor.";

  const ingredients = Array.isArray(product?.ingredients)
    ? product.ingredients
        .map(asObject)
        .filter((item): item is JsonObject => item !== null)
        .map((item) => asString(item.name))
        .filter(Boolean)
        .join(", ")
    : "";
  const medicineDetails = [
    { label: "Brand / Name", value: asString(product?.brand_name) || asString(product?.name) || fields.name },
    { label: "Generic ingredient", value: asString(product?.generic_name) || ingredients || fields.salt },
    { label: "Strength", value: dose },
    { label: "Dosage form", value: asString(product?.dosage_form) },
    { label: "Manufacturer", value: asString(product?.manufacturer) },
  ].filter((item) => item.value);
  const packDetails = [
    { label: "Batch", value: fields.batchNumber },
    { label: "Manufactured", value: fields.mfdDate },
    { label: "Expires", value: fields.expDate },
    { label: "GTIN", value: fields.gtin },
    { label: "Serial", value: fields.serial },
  ].filter((item) => item.value);

  const events = matches.flatMap((match, matchIndex) => {
    const matchProduct = asObject(match.product);
    const eventList = Array.isArray(match.regulatory_events) ? match.regulatory_events : [];
    return eventList
      .map(asObject)
      .filter((event): event is JsonObject => event !== null)
      .map((event, eventIndex) => ({
        data: event,
        productName: asString(matchProduct?.name),
        key: asString(event.event_id) || `${matchIndex}-${eventIndex}`,
      }));
  });

  const toggleEvent = (key: string) => {
    setExpandedEvents((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const openSource = async (url: string) => {
    try {
      await Linking.openURL(url);
    } catch {
      Alert.alert("Unable to open source", "The official source link could not be opened.");
    }
  };

  const shareResult = () => {
    void Share.share({ message: `${heading}\n${visuals.label}: ${summary}` });
  };

  return (
    <View style={styles.container}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.xs }]}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Go back"
          hitSlop={10}
          onPress={() => router.back()}
          style={styles.headerAction}
        >
          <Ionicons name="arrow-back" size={24} color={colors.text} />
        </Pressable>
        <Text numberOfLines={1} style={styles.headerTitle}>{heading}</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Share scan result"
          hitSlop={10}
          onPress={shareResult}
          style={styles.headerAction}
        >
          <Ionicons name="share-outline" size={23} color={colors.text} />
        </Pressable>
      </View>

      <ScrollView
        contentContainerStyle={[
          styles.content,
          { paddingBottom: spacing.xl },
        ]}
        showsVerticalScrollIndicator={false}
      >
        <Text style={styles.sectionTitle}>Medicine Info</Text>
        <View style={styles.card}>
          <Text style={styles.medicineName}>{heading}</Text>
          {medicineDetails.map((item) => (
            <Text key={item.label} style={styles.detailLine}>
              <Text style={styles.detailLabel}>{item.label}: </Text>{item.value}
            </Text>
          ))}
          {medicineDetails.length === 0 ? (
            <Text style={styles.mutedText}>No medicine details were captured.</Text>
          ) : null}
          {packDetails.length ? (
            <View style={styles.packDetails}>
              <Text style={styles.subsectionTitle}>Pack details</Text>
              {packDetails.map((item) => (
                <Text key={item.label} style={styles.detailLine}>
                  <Text style={styles.detailLabel}>{item.label}: </Text>{item.value}
                </Text>
              ))}
            </View>
          ) : null}
        </View>

        <Text style={styles.sectionTitle}>Regulatory overview</Text>
        <View style={styles.card}>
          <View style={[styles.overviewTop, { backgroundColor: visuals.surface }]}>
            <View style={[styles.indicatorIcon, { backgroundColor: visuals.tint }]}>
              <Ionicons name={visuals.icon} size={31} color={colors.surface} />
            </View>
            <View style={styles.overviewCopy}>
              <Text style={[styles.indicatorLabel, { color: visuals.tint }]}>
                {visuals.label} - {visuals.title}
              </Text>
              <Text style={styles.summaryText}>{summary}</Text>
            </View>
          </View>
          <Text style={styles.overviewNote}>
            {events.length
              ? `${events.length} related regulatory ${events.length === 1 ? "record" : "records"} found in the indexed data.`
              : matches.length
                ? "No related regulatory events were returned for this matched product. This is not a guarantee of safety."
                : "No matching product was found in the indexed records. This does not establish whether the pack is authentic or safe."}
          </Text>
        </View>

        <View style={styles.recordsHeading}>
          <Text style={styles.sectionTitle}>Related regulatory records</Text>
          {events.length > 0 ? <Text style={styles.recordCount}>{events.length}</Text> : null}
        </View>

        {events.length ? events.map(({ data, productName, key }) => {
          const source = asObject(data.source);
          const sourceUrl = asString(source?.source_url);
          const expanded = expandedEvents.has(key);
          const eventTitle = asString(data.event_type) || "Regulatory record";
          const extraDetails = [
            { label: "Legal status", value: asString(data.legal_status) },
            { label: "Official record", value: asString(source?.title) },
            { label: "Published", value: asString(source?.publication_date) },
          ].filter((item) => item.value);

          return (
            <View key={key} style={styles.card}>
              {productName ? <Text style={styles.eventProduct}>{productName}</Text> : null}
              <Text style={styles.eventTitle}>{eventTitle.replaceAll("_", " ")}</Text>
              {data.batch_number ? (
                <Text style={styles.eventLine}>
                  <Text style={styles.detailLabel}>Affected batch: </Text>{asString(data.batch_number)}
                </Text>
              ) : null}
              {data.reason ? (
                <Text style={styles.eventLine}>
                  <Text style={styles.detailLabel}>Issue: </Text>{asString(data.reason)}
                </Text>
              ) : null}
              {data.scope ? (
                <Text style={styles.eventLine}>
                  <Text style={styles.detailLabel}>Event scope: </Text>{asString(data.scope).toLowerCase()}
                </Text>
              ) : null}
              {data.status ? (
                <Text style={styles.eventLine}>
                  <Text style={styles.detailLabel}>Status: </Text>{asString(data.status).replaceAll("_", " ")}
                </Text>
              ) : null}
              <View style={styles.eventActions}>
                <Pressable accessibilityRole="button" onPress={() => toggleEvent(key)}>
                  <Text style={styles.linkText}>{expanded ? "Less info" : "More info"}</Text>
                </Pressable>
                <Text style={styles.actionDot}>•</Text>
                {sourceUrl ? (
                  <Pressable accessibilityRole="link" onPress={() => void openSource(sourceUrl)}>
                    <Text style={styles.linkText}>View official source</Text>
                  </Pressable>
                ) : (
                  <Text style={styles.mutedText}>Source link unavailable</Text>
                )}
              </View>
              {expanded && extraDetails.length ? (
                <View style={styles.expandedDetails}>
                  {extraDetails.map((item) => (
                    <Text key={item.label} style={styles.eventLine}>
                      <Text style={styles.detailLabel}>{item.label}: </Text>{item.value}
                    </Text>
                  ))}
                </View>
              ) : null}
            </View>
          );
        }) : (
          <View style={styles.emptyRecords}>
            <Ionicons name="document-text-outline" size={21} color={colors.textMuted} />
            <Text style={styles.emptyRecordsText}>
              {matches.length
                ? "No related regulatory records are available for this result."
                : "Regulatory records are unavailable because no product match was found."}
            </Text>
          </View>
        )}

        <Text style={styles.disclaimer}>{disclaimer}</Text>
      </ScrollView>

      <View style={[styles.bottomNav, { paddingBottom: Math.max(insets.bottom, spacing.xs) }]}>
        {NAV_ITEMS.map((item) => (
          <Pressable
            key={item.label}
            accessibilityRole="button"
            accessibilityLabel={item.label}
            onPress={() => router.replace(item.route)}
            style={styles.navItem}
          >
            <Ionicons name={item.icon} size={23} color={colors.textMuted} />
            <Text style={styles.navLabel}>{item.label}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  header: {
    minHeight: 58,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.sm,
    backgroundColor: colors.surface,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
    ...shadow.card,
  },
  headerAction: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
  headerTitle: {
    ...typography.title,
    flex: 1,
    textAlign: "center",
    marginHorizontal: spacing.xs,
    fontSize: 19,
  },
  content: { paddingHorizontal: spacing.lg, paddingTop: spacing.xl },
  sectionTitle: {
    ...typography.title,
    color: colors.text,
    fontSize: 20,
    marginBottom: spacing.sm,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.lg,
    overflow: "hidden",
    ...shadow.card,
  },
  medicineName: {
    ...typography.title,
    color: colors.text,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.xs,
  },
  detailLine: {
    ...typography.body,
    color: colors.text,
    lineHeight: 23,
    paddingHorizontal: spacing.lg,
  },
  detailLabel: { fontWeight: "700", color: colors.text },
  packDetails: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    marginTop: spacing.md,
    paddingTop: spacing.md,
    paddingBottom: spacing.lg,
  },
  subsectionTitle: {
    ...typography.label,
    color: colors.textSecondary,
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.xs,
  },
  overviewTop: {
    flexDirection: "row",
    alignItems: "center",
    padding: spacing.lg,
  },
  indicatorIcon: {
    width: 58,
    height: 58,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
    marginRight: spacing.md,
  },
  overviewCopy: { flex: 1 },
  indicatorLabel: { ...typography.heading, marginBottom: spacing.xs },
  summaryText: { ...typography.body, color: colors.text, lineHeight: 21, fontWeight: "600" },
  overviewNote: {
    ...typography.body,
    color: colors.text,
    lineHeight: 21,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  recordsHeading: { flexDirection: "row", alignItems: "center", marginBottom: spacing.sm },
  recordCount: {
    ...typography.caption,
    color: colors.textSecondary,
    marginLeft: spacing.sm,
    marginBottom: spacing.sm,
  },
  eventProduct: {
    ...typography.caption,
    color: colors.textSecondary,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
  },
  eventTitle: {
    ...typography.heading,
    color: colors.text,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.xs,
    textTransform: "capitalize",
  },
  eventLine: {
    ...typography.body,
    color: colors.text,
    lineHeight: 22,
    paddingHorizontal: spacing.lg,
  },
  eventActions: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.lg,
  },
  linkText: { ...typography.body, color: "#176b70", fontWeight: "600" },
  actionDot: { color: colors.textMuted, marginHorizontal: spacing.sm },
  expandedDetails: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    paddingTop: spacing.md,
    paddingBottom: spacing.lg,
  },
  emptyRecords: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    marginBottom: spacing.lg,
  },
  emptyRecordsText: {
    ...typography.body,
    flex: 1,
    color: colors.textSecondary,
    lineHeight: 21,
    marginLeft: spacing.md,
  },
  mutedText: { ...typography.body, color: colors.textMuted, paddingHorizontal: spacing.lg, paddingBottom: spacing.lg },
  disclaimer: {
    ...typography.caption,
    color: colors.textSecondary,
    lineHeight: 18,
    paddingHorizontal: spacing.xs,
    paddingBottom: spacing.md,
  },
  bottomNav: {
    flexDirection: "row",
    justifyContent: "space-around",
    backgroundColor: colors.surface,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    paddingTop: spacing.sm,
  },
  navItem: { flex: 1, alignItems: "center", justifyContent: "center", minHeight: 48 },
  navLabel: { ...typography.caption, color: colors.textMuted, marginTop: 2 },
});