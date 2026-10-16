import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { colors, typography } from "../theme";

export default function RootLayout() {
  return (
    // No SafeAreaView here on purpose: the scanner needs to run edge to edge,
    // and each screen (plus the tab bar) applies the insets it actually needs.
    <SafeAreaProvider>
      <StatusBar style="dark" />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: colors.background },
        }}
      >
        {/* Main Tab Navigator */}
        <Stack.Screen name="(tabs)" />

        {/* Authentication Flow */}
        <Stack.Screen name="(auth)" />

        {/* Onboarding */}
        <Stack.Screen
          name="instructions"
          options={{ animation: "slide_from_bottom" }}
        />

        {/* Results Screen */}
        <Stack.Screen
          name="result"
          options={{
            headerShown: false,
          }}
        />
      </Stack>
    </SafeAreaProvider>
  );
}
