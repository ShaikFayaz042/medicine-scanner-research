// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require('eslint/config');
const expoConfig = require("eslint-config-expo/flat");

module.exports = defineConfig([
  expoConfig,
  {
    // `example/` is leftover template scaffolding, not part of the app.
    ignores: ["dist/*", "example/*", "android/*", "ios/*"],
  }
]);
