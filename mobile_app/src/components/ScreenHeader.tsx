import { StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors, spacing, typography } from "../theme";

type Props = {
  title: string;
  subtitle?: string;
  /** Rendered on the trailing edge, e.g. a count badge or icon button. */
  trailing?: React.ReactNode;
};

/**
 * Large title header that respects the notch. Used by the tab screens, which
 * render without a navigation header.
 */
export function ScreenHeader({ title, subtitle, trailing }: Props) {
  const insets = useSafeAreaInsets();

  return (
    <View style={[styles.header, { paddingTop: insets.top + spacing.lg }]}>
      <View style={styles.row}>
        <View style={styles.titleGroup}>
          <Text style={styles.title}>{title}</Text>
          {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
        </View>
        {trailing}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    paddingHorizontal: spacing.xl,
    paddingBottom: spacing.lg,
    backgroundColor: colors.surface,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  row: {
    flexDirection: "row",
    alignItems: "flex-end",
    justifyContent: "space-between",
  },
  titleGroup: { flex: 1 },
  title: { ...typography.display, color: colors.text },
  subtitle: {
    ...typography.body,
    color: colors.textSecondary,
    marginTop: spacing.xs,
  },
});
