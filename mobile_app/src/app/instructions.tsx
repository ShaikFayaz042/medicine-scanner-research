import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useCameraPermissions } from "expo-camera";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { useCallback, useRef, useState } from "react";
import {
  LayoutChangeEvent,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AppButton } from "./../components/ui/AppButton";
import { colors, radius, shadow, spacing, typography } from "../theme";

const GUIDE_STEPS = [
  {
    key: "align",
    icon: "scan-outline" as const,
    title: "Line it up",
    desc: "Put the barcode or the printed label squarely inside the blue box. Only that area is read.",
    image: require("../../assets/instruction1.png"),
  },
  {
    key: "light",
    icon: "sunny-outline" as const,
    title: "Keep it lit",
    desc: "Avoid glare and shadows across the text. Use the torch button if the pack is dim.",
    image: require("../../assets/instruction2.png"),
  },
  {
    key: "text",
    icon: "text-outline" as const,
    title: "No barcode? Scan the text",
    desc: "Tap the round button to read the printed label instead. We will fill in what we find.",
    image: require("../../assets/instruction3.png"),
  },
];

export default function InstructionsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [permission, requestPermission] = useCameraPermissions();

  const scrollRef = useRef<ScrollView>(null);
  // Measured rather than taken from Dimensions: the carousel is inset by the
  // screen padding, so window width would put the paging maths out by 2x24px.
  const [pageWidth, setPageWidth] = useState(0);
  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  const onCarouselLayout = useCallback((event: LayoutChangeEvent) => {
    setPageWidth(event.nativeEvent.layout.width);
  }, []);

  const onMomentumScrollEnd = useCallback(
    (event: NativeSyntheticEvent<NativeScrollEvent>) => {
      if (pageWidth <= 0) return;
      const index = Math.round(event.nativeEvent.contentOffset.x / pageWidth);
      setStep(Math.min(Math.max(index, 0), GUIDE_STEPS.length - 1));
    },
    [pageWidth],
  );

  const isLastStep = step === GUIDE_STEPS.length - 1;

  const goToStep = useCallback(
    (index: number) => {
      scrollRef.current?.scrollTo({ x: index * pageWidth, animated: true });
      setStep(index);
    },
    [pageWidth],
  );

  const finish = useCallback(async () => {
    setSubmitting(true);
    try {
      await AsyncStorage.setItem("hasSeenOnboarding", "true");

      if (!permission?.granted && permission?.canAskAgain !== false) {
        await requestPermission();
      }
    } catch (error) {
      // Never block entry to the app on a storage or permission hiccup - the
      // scanner screen asks for camera access again if it is still missing.
      console.error("Onboarding completion failed:", error);
    } finally {
      setSubmitting(false);
      router.replace("/(tabs)/home");
    }
  }, [permission, requestPermission, router]);

  const handlePrimaryPress = useCallback(() => {
    if (isLastStep) {
      finish();
    } else {
      goToStep(step + 1);
    }
  }, [finish, goToStep, isLastStep, step]);

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Text style={styles.eyebrow}>Getting started</Text>
        <Text style={styles.title}>How to scan a pack</Text>
      </View>

      <View style={styles.carousel} onLayout={onCarouselLayout}>
        {pageWidth > 0 ? (
          <ScrollView
            ref={scrollRef}
            horizontal
            pagingEnabled
            showsHorizontalScrollIndicator={false}
            onMomentumScrollEnd={onMomentumScrollEnd}
          >
            {GUIDE_STEPS.map((guide) => (
              <View key={guide.key} style={[styles.slide, { width: pageWidth }]}>
                <View style={styles.imageCard}>
                  <Image
                    source={guide.image}
                    style={styles.image}
                    contentFit="cover"
                    transition={200}
                  />
                </View>
                <View style={styles.stepIcon}>
                  <Ionicons
                    name={guide.icon}
                    size={20}
                    color={colors.primary}
                  />
                </View>
                <Text style={styles.slideTitle}>{guide.title}</Text>
                <Text style={styles.slideDesc}>{guide.desc}</Text>
              </View>
            ))}
          </ScrollView>
        ) : null}
      </View>

      <View style={styles.pagination}>
        {GUIDE_STEPS.map((guide, index) => (
          <Pressable
            key={guide.key}
            accessibilityRole="button"
            accessibilityLabel={`Go to step ${index + 1}`}
            hitSlop={8}
            onPress={() => goToStep(index)}
            style={[styles.dot, step === index && styles.dotActive]}
          />
        ))}
      </View>

      <View
        style={[
          styles.footer,
          { paddingBottom: Math.max(insets.bottom, spacing.lg) },
        ]}
      >
        <AppButton
          label={isLastStep ? "Allow camera and start" : "Next"}
          icon={isLastStep ? "camera-outline" : undefined}
          loading={submitting}
          onPress={handlePrimaryPress}
        />
        {!isLastStep ? (
          <AppButton label="Skip" variant="ghost" onPress={finish} />
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  header: { paddingHorizontal: spacing.xl, paddingTop: spacing.xl },
  eyebrow: {
    ...typography.label,
    color: colors.primary,
    textTransform: "uppercase",
    letterSpacing: 1,
  },
  title: { ...typography.display, color: colors.text, marginTop: spacing.xs },

  carousel: { flex: 1, marginTop: spacing.xl },
  slide: { paddingHorizontal: spacing.xl, alignItems: "center" },
  imageCard: {
    width: "100%",
    aspectRatio: 4 / 3,
    borderRadius: radius.lg,
    overflow: "hidden",
    backgroundColor: colors.surfaceMuted,
    ...shadow.card,
  },
  image: { width: "100%", height: "100%" },
  stepIcon: {
    width: 44,
    height: 44,
    borderRadius: radius.pill,
    backgroundColor: colors.primarySurface,
    alignItems: "center",
    justifyContent: "center",
    marginTop: spacing.xl,
  },
  slideTitle: {
    ...typography.title,
    color: colors.text,
    marginTop: spacing.md,
    textAlign: "center",
  },
  slideDesc: {
    ...typography.body,
    color: colors.textSecondary,
    textAlign: "center",
    lineHeight: 22,
    marginTop: spacing.sm,
  },

  pagination: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    paddingVertical: spacing.xl,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: radius.pill,
    backgroundColor: colors.borderStrong,
    marginHorizontal: 4,
  },
  dotActive: { backgroundColor: colors.primary, width: 22 },

  footer: { paddingHorizontal: spacing.xl },
});
