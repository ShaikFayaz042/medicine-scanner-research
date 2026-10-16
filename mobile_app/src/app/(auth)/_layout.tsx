import { Stack } from "expo-router";
import { colors } from "../../theme";

export default function AuthLayout() {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.background },
      }}
    >
      <Stack.Screen name="login" options={{ animation: "slide_from_right" }} />
      <Stack.Screen
        name="register"
        options={{ animation: "slide_from_right" }}
      />
    </Stack>
  );
}
