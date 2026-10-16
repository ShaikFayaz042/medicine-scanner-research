import { Ionicons } from "@expo/vector-icons";
import {
  CameraView,
  useCameraPermissions,
  type BarcodeSettings,
} from "expo-camera";
import { useFocusEffect, useRouter } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useCallback, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Animated,
  Easing,
  LayoutChangeEvent,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AppButton } from "../../components/ui/AppButton";
import { parseBarcode, type ParsedBarcode } from "../../services/barcode";
import { describeFailure } from "../../services/session-errors";
import {
  needsManualEntry,
  toResultParams,
  verifyScannedBarcode,
  verifyScannedText,
  type Coordinates,
  type MedicineResult,
  type ScanMethod,
} from "../../services/medicine";
import { recognizeTextInRegion, type Rect } from "../../services/scanner";
import { colors, radius, shadow, spacing, typography } from "../../theme";

/** Fraction of the preview width the capture window spans. */
const FRAME_WIDTH_RATIO = 0.84;
/** Height of the capture window relative to its width. */
const FRAME_ASPECT = 0.58;
/** Nudge the window above the optical centre so the controls stay clear of it. */
const FRAME_VERTICAL_BIAS = 0.42;

/**
 * The camera only tells us when a barcode *is* seen, never when it leaves the
 * view, so presence is inferred from a quiet period. CameraView collapses
 * byte-identical detections to one every 500ms, so the window has to sit
 * comfortably above that to avoid the button flickering on a steady hand.
 */
const BARCODE_LOST_MS = 1500;

/** Hoisted so the native prop is not rewritten on every render. */
const BARCODE_SETTINGS: BarcodeSettings = {
  barcodeTypes: [
    "qr",
    "ean13",
    "ean8",
    "code128",
    "code39",
    "upc_a",
    "upc_e",
    "datamatrix",
  ],
};

export default function ScannerScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView>(null);

  const [previewSize, setPreviewSize] = useState({ width: 0, height: 0 });
  const [cameraReady, setCameraReady] = useState(false);
  const [torchOn, setTorchOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [busyText, setBusyText] = useState("");
  // Mirrors `busy` for the barcode callback, which is deliberately stable (see
  // the note on onBarcodeScanned below) and so cannot read the state directly.
  const busyRef = useRef(false);

  const startWork = useCallback((label: string) => {
    busyRef.current = true;
    setBusy(true);
    setBusyText(label);
  }, []);

  const endWork = useCallback(() => {
    busyRef.current = false;
    setBusy(false);
    setBusyText("");
  }, []);

  // Guards against a second scan being kicked off while we navigate away.
  // Reset every time the tab regains focus.
  const handledRef = useRef(false);
  const [isFocused, setIsFocused] = useState(false);

  // Live barcode presence. The camera detects continuously, but nothing is
  // submitted until the user taps the button.
  const [detected, setDetected] = useState<ParsedBarcode | null>(null);
  const detectedDataRef = useRef<string | null>(null);
  const lostTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Lazy state rather than a ref: the value is read during render (to build the
  // interpolation) and the React Compiler is enabled for this project.
  const [sweep] = useState(() => new Animated.Value(0));

  /**
   * The capture window is positioned from JS rather than by flex layout so the
   * exact same rectangle can be handed to the cropper. Drawing and cropping
   * therefore can never drift apart.
   */
  const frame: Rect = useMemo(() => {
    const width = previewSize.width * FRAME_WIDTH_RATIO;
    const height = width * FRAME_ASPECT;
    return {
      x: (previewSize.width - width) / 2,
      y: (previewSize.height - height) * FRAME_VERTICAL_BIAS,
      width,
      height,
    };
  }, [previewSize]);

  useFocusEffect(
    useCallback(() => {
      handledRef.current = false;
      busyRef.current = false;
      setIsFocused(true);
      setBusy(false);
      setBusyText("");

      const animation = Animated.loop(
        Animated.sequence([
          Animated.timing(sweep, {
            toValue: 1,
            duration: 2200,
            easing: Easing.inOut(Easing.quad),
            useNativeDriver: true,
          }),
          Animated.timing(sweep, {
            toValue: 0,
            duration: 2200,
            easing: Easing.inOut(Easing.quad),
            useNativeDriver: true,
          }),
        ]),
      );
      animation.start();

      return () => {
        animation.stop();
        if (lostTimerRef.current) clearTimeout(lostTimerRef.current);
        lostTimerRef.current = null;
        detectedDataRef.current = null;
        setDetected(null);
        setIsFocused(false);
        setCameraReady(false);
        setTorchOn(false);
      };
    }, [sweep]),
  );

  /**
   * The backend returns everything the result screen needs, so this just hands
   * the response straight on. The only branch is the fallback for a scan that
   * came back without a batch number, which the user has to fill in.
   */
  const routeToResult = useCallback(
    (
      result: MedicineResult,
      context: {
        method: ScanMethod;
        location: Coordinates | null;
        barcode?: string;
        rawText?: string;
      },
    ) => {
      const params = toResultParams(result, {
        method: context.method,
        location: context.location,
        barcode: context.barcode,
      });

      if (needsManualEntry(result)) {
        router.push({
          pathname: "/(tabs)/manual-entry",
          params: { ...params, rawText: context.rawText ?? "" },
        });
        return;
      }

      router.push({ pathname: "/result", params });
    },
    [router],
  );

  // Layer 1a - passive detection. This only decides which button to offer; it
  // never submits anything on its own.
  const handleBarcodeDetected = useCallback(
    ({ data, type }: { data: string; type: string }) => {
      if (!data || busyRef.current || handledRef.current) return;

      // Refresh the "still in view" window on every sighting.
      if (lostTimerRef.current) clearTimeout(lostTimerRef.current);
      lostTimerRef.current = setTimeout(() => {
        detectedDataRef.current = null;
        setDetected(null);
      }, BARCODE_LOST_MS);

      // Re-render only when the code itself changes, not on every frame.
      if (detectedDataRef.current === data) return;
      detectedDataRef.current = data;
      setDetected(parseBarcode(data, type));
    },
    [],
  );

  // Layer 1b - the user confirms. The undecoded payload goes to the backend,
  // which decodes it, looks it up and verifies it in one call.
  const handleScanBarcode = useCallback(async () => {
    const barcode = detected;
    if (!barcode || busy || handledRef.current) return;

    handledRef.current = true;
    startWork("Checking the barcode...");

    try {
      // One call: the backend decodes the payload and queries the DB directly.
      const result = await verifyScannedBarcode(
        barcode.raw,
        barcode.symbology,
        null,
      );

      console.log(barcode.raw);

      routeToResult(result, {
        method: "barcode",
        location: null,
        barcode: barcode.raw,
      });
    } catch (error) {
      // A lapsed session sends the user to sign in rather than trapping them
      // on a screen where every tap fails the same way.
      const outcome = await describeFailure(
        error,
        router,
        "Something went wrong while checking the barcode.",
      );
      if (outcome.kind === "message") {
        Alert.alert("Could not check the barcode", outcome.message);
      }
    } finally {
      handledRef.current = false;
      endWork();
    }
  }, [busy, detected, endWork, routeToResult, router, startWork]);

  // Layer 2 - crop to the window, OCR it, then hand the text to the backend.
  const handleCaptureForOCR = useCallback(async () => {
    const camera = cameraRef.current;
    if (!camera || busy) return;

    if (!cameraReady) {
      Alert.alert("Camera not ready", "Give the camera a moment, then retry.");
      return;
    }

    handledRef.current = true;
    startWork("Capturing...");

    try {
      const photo = await camera.takePictureAsync({
        quality: 1,
        exif: false,
        skipProcessing: false,
      });

      if (!photo?.uri) throw new Error("The camera returned no image.");

      setBusyText("Reading the label...");
      const { text } = await recognizeTextInRegion(
        photo.uri,
        { width: photo.width, height: photo.height },
        frame,
        previewSize,
      );

      console.log(text);

      if (!text) {
        throw new Error(
          "No text was found inside the frame. Move closer, hold the pack steady and try again.",
        );
      }

      setBusyText("Verifying...");

      // One call: the backend runs the LLM extraction and the DB lookup, and
      // returns the fields plus the verdict together.
      const result = await verifyScannedText(text, null);

      // The raw text travels along so the form can show it if we fall back.
      routeToResult(result, { method: "ocr", location: null, rawText: text });
    } catch (error) {
      const outcome = await describeFailure(
        error,
        router,
        "Something went wrong while reading the label.",
      );
      if (outcome.kind === "message") {
        Alert.alert("Could not read the label", outcome.message);
      }
    } finally {
      handledRef.current = false;
      endWork();
    }
  }, [
    busy,
    cameraReady,
    endWork,
    frame,
    previewSize,
    routeToResult,
    router,
    startWork,
  ]);

  const onPreviewLayout = useCallback((event: LayoutChangeEvent) => {
    const { width, height } = event.nativeEvent.layout;
    setPreviewSize({ width, height });
  }, []);

  // --- Permission states ------------------------------------------------

  if (!permission) {
    return (
      <View style={styles.permissionContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  if (!permission.granted) {
    return (
      <View
        style={[styles.permissionContainer, { paddingTop: insets.top + 24 }]}
      >
        <View style={styles.permissionIcon}>
          <Ionicons name="camera-outline" size={40} color={colors.primary} />
        </View>
        <Text style={styles.permissionTitle}>Camera access needed</Text>
        <Text style={styles.permissionBody}>
          MediCheck uses the camera to read the barcode and printed label on the
          pack. Photos stay on your device - only the extracted text is sent for
          verification.
        </Text>
        <AppButton
          label={permission.canAskAgain ? "Allow camera" : "Try again"}
          icon="camera"
          onPress={requestPermission}
          style={styles.permissionButton}
        />
      </View>
    );
  }

  // --- Scanner -----------------------------------------------------------

  const hasFrame = previewSize.width > 0 && previewSize.height > 0;
  // A failed check digit means the code was decoded wrongly, so looking it up
  // would query the wrong product entirely.
  const misread = detected?.gtinValid === false;
  const sweepTranslate = sweep.interpolate({
    inputRange: [0, 1],
    outputRange: [0, Math.max(frame.height - 3, 0)],
  });

  return (
    <View style={styles.container} onLayout={onPreviewLayout}>
      <StatusBar style="light" />

      {isFocused ? (
        <CameraView
          ref={cameraRef}
          style={StyleSheet.absoluteFill}
          facing="back"
          enableTorch={torchOn}
          // Left at the default "off", which means continuous autofocus.
          // "on" would focus once and then lock, which is wrong for scanning.
          autofocus="off"
          animateShutter={false}
          onCameraReady={() => setCameraReady(true)}
          onMountError={() =>
            Alert.alert(
              "Camera unavailable",
              "The camera could not be started on this device.",
            )
          }
          // Must stay attached at all times. expo-camera derives
          // `barcodeScannerEnabled` from whether this prop is set, and flipping
          // it calls setShouldScanBarcodes() natively, which forces a full
          // unbindAll() + rebind of the CameraX use cases. Doing that while
          // takePictureAsync() is in flight kills the capture, surfacing as
          // "Failed to capture image". Detections are ignored via busyRef
          // inside the handler instead.
          onBarcodeScanned={handleBarcodeDetected}
          barcodeScannerSettings={BARCODE_SETTINGS}
        />
      ) : (
        <View style={StyleSheet.absoluteFill} />
      )}

      {/* Scrim with a real cut-out: four panels around the window leave the
          target area completely unobstructed. */}
      {hasFrame ? (
        <View style={StyleSheet.absoluteFill} pointerEvents="none">
          <View style={[styles.scrim, { height: frame.y }]} />
          <View style={[styles.scrimRow, { height: frame.height }]}>
            <View style={[styles.scrim, { width: frame.x }]} />
            <View style={{ width: frame.width }} />
            <View style={[styles.scrim, styles.fill]} />
          </View>
          <View style={[styles.scrim, styles.fill]} />
        </View>
      ) : null}

      {/* Window outline, corner brackets and the sweeping guide line. */}
      {hasFrame ? (
        <View
          pointerEvents="none"
          style={[
            styles.frame,
            {
              left: frame.x,
              top: frame.y,
              width: frame.width,
              height: frame.height,
            },
          ]}
        >
          <View style={[styles.corner, styles.cornerTopLeft]} />
          <View style={[styles.corner, styles.cornerTopRight]} />
          <View style={[styles.corner, styles.cornerBottomLeft]} />
          <View style={[styles.corner, styles.cornerBottomRight]} />
          {!busy ? (
            <Animated.View
              style={[
                styles.sweepLine,
                { transform: [{ translateY: sweepTranslate }] },
              ]}
            />
          ) : null}
        </View>
      ) : null}

      {/* Top bar */}
      <View
        style={[styles.topBar, { top: insets.top + spacing.sm }]}
        pointerEvents="box-none"
      >
        <View style={styles.brandPill}>
          <Ionicons name="shield-checkmark" size={16} color={colors.frame} />
          <Text style={styles.brandText}>MediCheck</Text>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="How to scan"
          hitSlop={8}
          style={styles.iconButton}
          onPress={() => router.push("/instructions")}
        >
          <Ionicons
            name="help-circle-outline"
            size={22}
            color={colors.textInverse}
          />
        </Pressable>
      </View>

      {/* Hint directly under the window, driven by whether a barcode is in view */}
      {hasFrame ? (
        <View
          pointerEvents="none"
          style={[
            styles.hintWrap,
            { top: frame.y + frame.height + spacing.lg },
          ]}
        >
          {detected ? (
            <>
              <View
                style={[
                  styles.detectedPill,
                  misread && styles.detectedPillWarning,
                ]}
              >
                <Ionicons
                  name={misread ? "warning-outline" : "barcode-outline"}
                  size={14}
                  color={colors.textInverse}
                />
                <Text style={styles.detectedPillText}>
                  {misread
                    ? "CHECK DIGIT FAILED"
                    : `${detected.symbology.toUpperCase()} detected`}
                </Text>
              </View>
              <Text style={styles.detectedCode} numberOfLines={1}>
                {misread
                  ? "Hold steadier and let it re-read"
                  : (detected.gtin ?? detected.raw)}
              </Text>
            </>
          ) : (
            <>
              <Text style={styles.hintTitle}>
                Line up the barcode or the printed label
              </Text>
              <Text style={styles.hintBody}>
                No barcode in view. Only what is inside this box is read.
              </Text>
            </>
          )}
        </View>
      ) : null}

      {/* Bottom controls. No bottom inset here: this screen sits inside the tab
          navigator, whose bar already reserves the home indicator / gesture
          area, so adding insets.bottom again would double-pad it. */}
      <View style={styles.controls}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={torchOn ? "Turn torch off" : "Turn torch on"}
          accessibilityState={{ selected: torchOn }}
          style={[styles.roundButton, torchOn && styles.roundButtonActive]}
          onPress={() => setTorchOn((v) => !v)}
        >
          <Ionicons
            name={torchOn ? "flashlight" : "flashlight-outline"}
            size={22}
            color={torchOn ? colors.text : colors.textInverse}
          />
        </Pressable>

        {/* One primary action, chosen by what is actually in front of the
            camera: a barcode is faster and more accurate than reading the
            printed label, so it takes over whenever one is present. */}
        {detected ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Scan the detected ${detected.symbology} barcode`}
            accessibilityState={{ disabled: busy || misread, busy }}
            disabled={busy || misread}
            onPress={handleScanBarcode}
            style={({ pressed }) => [
              styles.action,
              styles.actionBarcode,
              pressed && styles.actionPressed,
              (busy || misread) && styles.actionDisabled,
            ]}
          >
            {busy ? (
              <ActivityIndicator color={colors.textInverse} />
            ) : (
              <>
                <Ionicons
                  name="barcode-outline"
                  size={22}
                  color={colors.textInverse}
                />
                <Text style={styles.actionTextOnDark}>Scan barcode</Text>
              </>
            )}
          </Pressable>
        ) : (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Scan the text inside the frame"
            accessibilityState={{ disabled: busy || !cameraReady, busy }}
            disabled={busy || !cameraReady}
            onPress={handleCaptureForOCR}
            style={({ pressed }) => [
              styles.action,
              styles.actionText,
              pressed && styles.actionPressed,
              (busy || !cameraReady) && styles.actionDisabled,
            ]}
          >
            {busy ? (
              <ActivityIndicator color={colors.primary} />
            ) : (
              <>
                <Ionicons
                  name="text-outline"
                  size={22}
                  color={colors.primary}
                />
                <Text style={styles.actionTextOnLight}>Scan text</Text>
              </>
            )}
          </Pressable>
        )}

        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Enter details manually"
          style={styles.roundButton}
          onPress={() => router.push("/(tabs)/manual-entry")}
        >
          <Ionicons
            name="create-outline"
            size={22}
            color={colors.textInverse}
          />
        </Pressable>
      </View>

      {/* Blocking progress overlay */}
      {busy ? (
        <View style={styles.busyOverlay}>
          <View style={styles.busyCard}>
            <ActivityIndicator size="large" color={colors.primary} />
            <Text style={styles.busyText}>{busyText || "Working..."}</Text>
          </View>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#000" },
  fill: { flex: 1 },

  scrim: { backgroundColor: colors.scrim },
  scrimRow: { flexDirection: "row" },

  frame: {
    position: "absolute",
    borderWidth: 1.5,
    borderColor: "rgba(255,255,255,0.55)",
    borderRadius: radius.lg,
    overflow: "hidden",
  },
  corner: {
    position: "absolute",
    width: 30,
    height: 30,
    borderColor: colors.frame,
  },
  cornerTopLeft: {
    top: -1.5,
    left: -1.5,
    borderTopWidth: 4,
    borderLeftWidth: 4,
    borderTopLeftRadius: radius.lg,
  },
  cornerTopRight: {
    top: -1.5,
    right: -1.5,
    borderTopWidth: 4,
    borderRightWidth: 4,
    borderTopRightRadius: radius.lg,
  },
  cornerBottomLeft: {
    bottom: -1.5,
    left: -1.5,
    borderBottomWidth: 4,
    borderLeftWidth: 4,
    borderBottomLeftRadius: radius.lg,
  },
  cornerBottomRight: {
    bottom: -1.5,
    right: -1.5,
    borderBottomWidth: 4,
    borderRightWidth: 4,
    borderBottomRightRadius: radius.lg,
  },
  sweepLine: {
    height: 3,
    width: "100%",
    backgroundColor: colors.frame,
    opacity: 0.85,
  },

  topBar: {
    position: "absolute",
    left: spacing.lg,
    right: spacing.lg,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  brandPill: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.pill,
    backgroundColor: "rgba(15,23,42,0.55)",
  },
  brandText: {
    ...typography.label,
    color: colors.textInverse,
    marginLeft: spacing.sm,
  },
  iconButton: {
    width: 40,
    height: 40,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(15,23,42,0.55)",
  },

  hintWrap: {
    position: "absolute",
    left: spacing.xl,
    right: spacing.xl,
    alignItems: "center",
  },
  hintTitle: {
    ...typography.heading,
    fontSize: 15,
    color: colors.textInverse,
    textAlign: "center",
  },
  hintBody: {
    ...typography.caption,
    color: "rgba(255,255,255,0.75)",
    textAlign: "center",
    marginTop: spacing.xs,
    lineHeight: 17,
  },
  detectedPill: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderRadius: radius.pill,
    backgroundColor: colors.primary,
  },
  detectedPillWarning: { backgroundColor: colors.warning },
  detectedPillText: {
    ...typography.caption,
    fontSize: 11,
    letterSpacing: 0.6,
    color: colors.textInverse,
    marginLeft: 6,
  },
  detectedCode: {
    ...typography.mono,
    color: colors.textInverse,
    marginTop: spacing.sm,
    textAlign: "center",
  },

  controls: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.lg,
  },
  roundButton: {
    width: 52,
    height: 52,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(15,23,42,0.55)",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.18)",
  },
  roundButtonActive: {
    backgroundColor: colors.textInverse,
    borderColor: colors.textInverse,
  },
  // The primary action is a labelled pill rather than a bare shutter, because
  // it swaps between two modes and the label is what tells them apart.
  action: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    height: 58,
    borderRadius: radius.pill,
    marginHorizontal: spacing.md,
    ...shadow.raised,
  },
  actionBarcode: { backgroundColor: colors.primary },
  actionText: { backgroundColor: colors.surface },
  actionPressed: { transform: [{ scale: 0.97 }] },
  actionDisabled: { opacity: 0.6 },
  actionTextOnDark: {
    ...typography.heading,
    fontSize: 16,
    color: colors.textInverse,
    marginLeft: spacing.sm,
  },
  actionTextOnLight: {
    ...typography.heading,
    fontSize: 16,
    color: colors.primary,
    marginLeft: spacing.sm,
  },

  busyOverlay: {
    ...StyleSheet.absoluteFill,
    backgroundColor: "rgba(8,15,30,0.55)",
    alignItems: "center",
    justifyContent: "center",
  },
  busyCard: {
    backgroundColor: colors.surface,
    paddingVertical: spacing.xl,
    paddingHorizontal: spacing.xxl,
    borderRadius: radius.lg,
    alignItems: "center",
    minWidth: 200,
    ...shadow.raised,
  },
  busyText: {
    ...typography.label,
    color: colors.text,
    marginTop: spacing.md,
    textAlign: "center",
  },

  permissionContainer: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
    backgroundColor: colors.background,
  },
  permissionIcon: {
    width: 80,
    height: 80,
    borderRadius: radius.pill,
    backgroundColor: colors.primarySurface,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.xl,
  },
  permissionTitle: {
    ...typography.title,
    color: colors.text,
    marginBottom: spacing.sm,
    textAlign: "center",
  },
  permissionBody: {
    ...typography.body,
    color: colors.textSecondary,
    textAlign: "center",
    lineHeight: 22,
  },
  permissionButton: { alignSelf: "stretch", marginTop: spacing.xl },
});
