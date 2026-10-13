#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "================================================================"
echo "  🇿🇦 FLEETSENTINEL ANDROID DRIVER APK COMPILATION"
echo "  • Package: com.fleetsentinel.driver"
echo "  • Target Corridor: N4 Highveld (Pretoria East ⇄ Witbank)"
echo "  • SDK: Android 34 (Android 14) • Build-Tools: 34.0.0"
echo "================================================================"

echo ""
echo "[Step 1/3] Building containerized Android SDK build environment..."
docker build -f Dockerfile.build -t fleetsentinel-android-builder .

echo ""
echo "[Step 2/3] Compiling FleetSentinel Driver APK via Gradle 8.4..."
# Clean up any previous container instance with the same name
docker rm fleetsentinel_apk_build_instance 2>/dev/null || true

# Run compilation in isolated container (mounting project directory)
docker run --name fleetsentinel_apk_build_instance -v "$SCRIPT_DIR:/workspace" fleetsentinel-android-builder
docker rm fleetsentinel_apk_build_instance 2>/dev/null || true

echo ""
echo "[Step 3/3] Validating APK artifacts..."
APK_PATH="$SCRIPT_DIR/app/build/outputs/apk/debug/app-debug.apk"

if [ -f "$APK_PATH" ]; then
    APK_SIZE=$(du -h "$APK_PATH" | cut -f1)
    SHA256=$(sha256sum "$APK_PATH" | cut -d' ' -f1)
    echo "================================================================"
    echo "  🎉 APK COMPILED SUCCESSFULLY!"
    echo "  • Artifact: $APK_PATH"
    echo "  • File Size: $APK_SIZE"
    echo "  • SHA-256:   $SHA256"
    echo "================================================================"
else
    echo "❌ Error: Expected APK artifact not found at $APK_PATH"
    exit 1
fi
