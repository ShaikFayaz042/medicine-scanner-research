const { withAndroidManifest } = require("@expo/config-plugins");

module.exports = function withApiCleartextTraffic(config) {
  return withAndroidManifest(config, (config) => {
    const application = config.modResults.manifest.application?.[0];
    if (!application) return config;

    application.$ ??= {};
    if ((process.env.EXPO_PUBLIC_API_URL ?? "").startsWith("http://")) {
      application.$["android:usesCleartextTraffic"] = "true";
    } else {
      delete application.$["android:usesCleartextTraffic"];
    }

    return config;
  });
};