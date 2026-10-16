import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
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
import { AppButton } from "../../components/ui/AppButton";
import { ScreenHeader } from "../../components/ScreenHeader";
import { TextField } from "../../components/ui/TextField";
import { describeFailure } from "../../services/session-errors";
import {
  EMPTY_FIELDS,
  toResultParams,
  verifyManualEntry,
  type MedicineFields,
  type ScanMethod,
} from "../../services/medicine";
import { colors, radius, spacing, typography } from "../../theme";

/** Route params arrive as `string | string[]`; collapse them to a single value. */
const asText = (value: string | string[] | undefined) =>
  (Array.isArray(value) ? value[0] : value) ?? "";

export default function ManualEntryScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();

  const rawText = asText(params.rawText as string | string[] | undefined);

  const incomingMethod = asText(
    params.method as string | string[] | undefined,
  );
  const gtin = asText(params.gtin as string | string[] | undefined);
  const serial = asText(params.serial as string | string[] | undefined);
  const barcode = asText(params.barcode as string | string[] | undefined);

  // We only land here when the backend reported it needed more information.
  const isPartialBarcode = incomingMethod === "barcode";
  const isPartialScan = incomingMethod === "ocr";

  const submittedMethod: ScanMethod = isPartialBarcode
    ? "barcode_corrected"
    : rawText
      ? "ocr_corrected"
      : "manual";

  const prefill: MedicineFields = useMemo(
    () => ({
      name: asText(params.name as string | string[] | undefined),
      salt: asText(params.salt as string | string[] | undefined),
      batchNumber: asText(params.batchNumber as string | string[] | undefined),
      mfdDate: asText(params.mfdDate as string | string[] | undefined),
      expDate: asText(params.expDate as string | string[] | undefined),
      dose: asText(params.dose as string | string[] | undefined),
    }),
    [
      params.name,
      params.salt,
      params.batchNumber,
      params.mfdDate,
      params.expDate,
      params.dose,
    ],
  );

  // Keying the form on the incoming params means a fresh scan resets the fields
  // without an effect that could clobber what the user is currently typing.
  const [formKey, setFormKey] = useState(() => JSON.stringify(prefill));
  const [fields, setFields] = useState<MedicineFields>(prefill);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [showRawText, setShowRawText] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const incomingKey = JSON.stringify(prefill);
  if (incomingKey !== formKey) {
    setFormKey(incomingKey);
    setFields(prefill);
    setBatchError(null);
    setShowRawText(true);
  }

  const update = useCallback(
    (key: keyof MedicineFields) => (value: string) => {
      setFields((current) => ({ ...current, [key]: value }));
      if (key === "batchNumber") setBatchError(null);
    },
    [],
  );

  const handleSubmit = useCallback(async () => {
    if (submitting) return;

    if (!fields.batchNumber.trim()) {
      setBatchError("A batch number is needed to check the register.");
      return;
    }

    setSubmitting(true);
    try {
      // One call: nothing to extract here, so the backend only looks the batch
      // up and returns the verdict.
      // method and serial are passed through so the server records how the
      // details actually got here, not just "manual".
      const result = await verifyManualEntry(
        fields,
        null,
        gtin || undefined,
        serial || undefined,
        submittedMethod,
      );

      router.push({
        pathname: "/result",
        params: {
          ...toResultParams(result, {
            method: submittedMethod,
            location: null,
            barcode,
          }),
          // Carried over from the barcode scan being corrected, so it survives
          // the round trip through this form.
          serial: result.serial || serial,
        },
      });
    } catch (error) {
      const outcome = await describeFailure(
        error,
        router,
        "Something went wrong while checking the register.",
      );
      if (outcome.kind === "message") {
        Alert.alert("Could not verify", outcome.message);
      }
    } finally {
      setSubmitting(false);
    }
  }, [barcode, fields, gtin, router, serial, submitting, submittedMethod]);

  const handleClear = useCallback(() => {
    setFields(EMPTY_FIELDS);
    setBatchError(null);
  }, []);

  return (
    <View style={styles.container}>
      <ScreenHeader
        title="Enter details"
        subtitle={
          isPartialBarcode
            ? "The barcode identified the product but carries no batch number - add it below."
            : isPartialScan
              ? "We read part of the label - fill in the rest."
              : "Type the details printed on the pack."
        }
      />

      <KeyboardAvoidingView
        style={styles.fill}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="on-drag"
        >
          {showRawText && rawText ? (
            <View style={styles.helperBox}>
              <View style={styles.helperHeader}>
                <View style={styles.helperTitleRow}>
                  <Ionicons
                    name="scan-outline"
                    size={16}
                    color={colors.primary}
                  />
                  <Text style={styles.helperTitle}>Text we read</Text>
                </View>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Dismiss the scanned text"
                  hitSlop={8}
                  onPress={() => setShowRawText(false)}
                >
                  <Ionicons name="close" size={20} color={colors.textMuted} />
                </Pressable>
              </View>
              <Text style={styles.helperText} selectable>
                {rawText}
              </Text>
              <Text style={styles.helperInstruction}>
                Copy the missing details from here into the fields below.
              </Text>
            </View>
          ) : null}

          <TextField
            label="Medicine name"
            placeholder="e.g. Tylenol"
            icon="medkit-outline"
            value={fields.name}
            onChangeText={update("name")}
            autoCapitalize="words"
            returnKeyType="next"
          />

          <TextField
            label="Active ingredient"
            placeholder="e.g. Paracetamol"
            icon="flask-outline"
            value={fields.salt}
            onChangeText={update("salt")}
            autoCapitalize="words"
            returnKeyType="next"
          />

          <TextField
            label="Batch number"
            required
            error={batchError}
            hint="Usually printed near the expiry date as B.NO. or LOT."
            placeholder="e.g. B.NO.12345"
            icon="barcode-outline"
            value={fields.batchNumber}
            onChangeText={update("batchNumber")}
            autoCapitalize="characters"
            autoCorrect={false}
            returnKeyType="next"
          />

          <View style={styles.row}>
            <View style={styles.rowItem}>
              <TextField
                label="Manufactured"
                placeholder="MM/YYYY"
                value={fields.mfdDate}
                onChangeText={update("mfdDate")}
                keyboardType="numbers-and-punctuation"
                returnKeyType="next"
              />
            </View>
            <View style={styles.rowSpacer} />
            <View style={styles.rowItem}>
              <TextField
                label="Expires"
                placeholder="MM/YYYY"
                value={fields.expDate}
                onChangeText={update("expDate")}
                keyboardType="numbers-and-punctuation"
                returnKeyType="next"
              />
            </View>
          </View>

          <TextField
            label="Dose"
            placeholder="e.g. 500mg"
            icon="beaker-outline"
            value={fields.dose}
            onChangeText={update("dose")}
            autoCapitalize="none"
            returnKeyType="done"
            onSubmitEditing={handleSubmit}
          />

          <AppButton
            label="Verify medicine"
            icon="shield-checkmark-outline"
            loading={submitting}
            onPress={handleSubmit}
            style={styles.submit}
          />

          <AppButton
            label="Clear form"
            variant="ghost"
            disabled={submitting}
            onPress={handleClear}
            style={styles.clear}
          />
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  fill: { flex: 1 },
  scrollContent: {
    padding: spacing.xl,
    paddingBottom: spacing.xxl,
  },
  helperBox: {
    backgroundColor: colors.primarySurface,
    padding: spacing.lg,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: "#bfdbfe",
    marginBottom: spacing.xl,
  },
  helperHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: spacing.md,
  },
  helperTitleRow: { flexDirection: "row", alignItems: "center" },
  helperTitle: {
    ...typography.label,
    color: colors.primaryDark,
    marginLeft: spacing.sm,
  },
  helperText: {
    ...typography.mono,
    color: colors.text,
    lineHeight: 19,
    marginBottom: spacing.md,
  },
  helperInstruction: {
    ...typography.caption,
    color: colors.primaryDark,
  },
  row: { flexDirection: "row" },
  rowItem: { flex: 1 },
  rowSpacer: { width: spacing.md },
  submit: { marginTop: spacing.sm },
  clear: { marginTop: spacing.sm },
});
