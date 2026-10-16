import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
} from "react-native";
import { colors, radius, spacing, typography } from "../../theme";

type Props = TextInputProps & {
  label: string;
  hint?: string;
  error?: string | null;
  required?: boolean;
  icon?: keyof typeof Ionicons.glyphMap;
  /** Renders a show/hide toggle and forces secure entry by default. */
  secure?: boolean;
};

export function TextField({
  label,
  hint,
  error,
  required,
  icon,
  secure,
  style,
  ...inputProps
}: Props) {
  const [focused, setFocused] = useState(false);
  const [revealed, setRevealed] = useState(false);

  return (
    <View style={styles.wrapper}>
      <View style={styles.labelRow}>
        <Text style={styles.label}>{label}</Text>
        {required ? <Text style={styles.required}>Required</Text> : null}
      </View>

      <View
        style={[
          styles.inputRow,
          focused && styles.inputRowFocused,
          !!error && styles.inputRowError,
        ]}
      >
        {icon ? (
          <Ionicons
            name={icon}
            size={18}
            color={focused ? colors.primary : colors.textMuted}
            style={styles.leadingIcon}
          />
        ) : null}

        <TextInput
          {...inputProps}
          style={[styles.input, style]}
          placeholderTextColor={colors.textMuted}
          secureTextEntry={secure ? !revealed : inputProps.secureTextEntry}
          onFocus={(e) => {
            setFocused(true);
            inputProps.onFocus?.(e);
          }}
          onBlur={(e) => {
            setFocused(false);
            inputProps.onBlur?.(e);
          }}
        />

        {secure ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={revealed ? "Hide password" : "Show password"}
            hitSlop={10}
            onPress={() => setRevealed((v) => !v)}
          >
            <Ionicons
              name={revealed ? "eye-off-outline" : "eye-outline"}
              size={20}
              color={colors.textMuted}
            />
          </Pressable>
        ) : null}
      </View>

      {error ? (
        <Text style={styles.error}>{error}</Text>
      ) : hint ? (
        <Text style={styles.hint}>{hint}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { marginBottom: spacing.lg },
  labelRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.sm,
  },
  label: { ...typography.label, color: colors.textSecondary },
  required: { ...typography.caption, color: colors.primary },
  inputRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
  },
  inputRowFocused: {
    borderColor: colors.primary,
    backgroundColor: colors.surface,
  },
  inputRowError: { borderColor: colors.danger },
  leadingIcon: { marginRight: spacing.md },
  input: {
    flex: 1,
    paddingVertical: 14,
    fontSize: 16,
    color: colors.text,
  },
  hint: {
    ...typography.caption,
    color: colors.textMuted,
    marginTop: spacing.xs,
  },
  error: {
    ...typography.caption,
    color: colors.dangerText,
    marginTop: spacing.xs,
  },
});
