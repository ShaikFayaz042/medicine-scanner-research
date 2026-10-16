import { Platform, TextStyle, ViewStyle } from "react-native";

/**
 * Single source of truth for the app's visual language.
 * Screens should pull from here instead of hard-coding hex values so that the
 * scanner, forms and result screens stay visually consistent.
 */
export const colors = {
  // Brand
  primary: "#2563eb",
  primaryDark: "#1d4ed8",
  primaryLight: "#60a5fa",
  primarySurface: "#eff6ff",

  // Neutrals
  background: "#f6f8fb",
  surface: "#ffffff",
  surfaceMuted: "#f1f5f9",
  border: "#e2e8f0",
  borderStrong: "#cbd5e1",

  // Text
  text: "#0f172a",
  textSecondary: "#475569",
  textMuted: "#94a3b8",
  textInverse: "#ffffff",

  // Semantic
  success: "#16a34a",
  successSurface: "#f0fdf4",
  successBorder: "#bbf7d0",
  successText: "#15803d",

  danger: "#dc2626",
  dangerSurface: "#fef2f2",
  dangerBorder: "#fecaca",
  dangerText: "#b91c1c",

  warning: "#d97706",
  warningSurface: "#fffbeb",
  warningBorder: "#fde68a",
  warningText: "#b45309",

  // Camera overlay
  scrim: "rgba(8, 15, 30, 0.62)",
  scrimSoft: "rgba(8, 15, 30, 0.35)",
  frame: "#60a5fa",
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  pill: 999,
} as const;

export const typography = {
  display: { fontSize: 30, fontWeight: "700", letterSpacing: -0.5 } as TextStyle,
  title: { fontSize: 22, fontWeight: "700", letterSpacing: -0.2 } as TextStyle,
  heading: { fontSize: 17, fontWeight: "700" } as TextStyle,
  body: { fontSize: 15, fontWeight: "400" } as TextStyle,
  label: { fontSize: 13, fontWeight: "600", letterSpacing: 0.1 } as TextStyle,
  caption: { fontSize: 12, fontWeight: "500" } as TextStyle,
  mono: {
    fontSize: 13,
    fontFamily: Platform.select({ ios: "Menlo", default: "monospace" }),
  } as TextStyle,
} as const;

/** Cross-platform elevation. iOS needs shadow*, Android needs elevation. */
export const shadow = {
  card: Platform.select<ViewStyle>({
    ios: {
      shadowColor: "#0f172a",
      shadowOpacity: 0.06,
      shadowRadius: 12,
      shadowOffset: { width: 0, height: 4 },
    },
    default: { elevation: 2 },
  }) as ViewStyle,
  raised: Platform.select<ViewStyle>({
    ios: {
      shadowColor: "#0f172a",
      shadowOpacity: 0.16,
      shadowRadius: 20,
      shadowOffset: { width: 0, height: 8 },
    },
    default: { elevation: 6 },
  }) as ViewStyle,
} as const;
