/**
 * Native-shell integration — active ONLY inside the Capacitor mobile app.
 *
 * The same deployed site serves browsers and the mobile shell (remote-mode
 * Capacitor, see web/capacitor.config.ts). The shell injects the Capacitor
 * bridge into the page, so `isNativePlatform()` is the runtime switch: in a
 * normal browser everything here is a no-op.
 */
import { Capacitor } from "@capacitor/core";

export function isNativeApp(): boolean {
  return Capacitor.isNativePlatform();
}

export async function initNativeShell(): Promise<void> {
  if (!isNativeApp()) return;
  try {
    const { App } = await import("@capacitor/app");
    // Android hardware back = SPA history back; exit only from the root.
    void App.addListener("backButton", ({ canGoBack }) => {
      if (canGoBack || window.history.length > 1) window.history.back();
      else void App.exitApp();
    });
  } catch {
    // plugin missing in this shell build — never break the web app
  }
  try {
    const { StatusBar, Style } = await import("@capacitor/status-bar");
    await StatusBar.setStyle({ style: Style.Dark });
    await StatusBar.setBackgroundColor({ color: "#0b2239" }); // brand teal
  } catch {
    // iOS shells throw on setBackgroundColor; style alone is fine there
  }
}
