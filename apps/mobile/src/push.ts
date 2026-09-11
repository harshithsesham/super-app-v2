// Push registration: ask once after sign-in, hand the raw APNs device token to
// the gateway (never to a third-party relay), and open the right place when a
// notification is tapped. Everything is best-effort: a simulator or a denied
// permission must never affect the rest of the app.
import { useEffect } from "react";
import { Platform } from "react-native";
import Constants from "expo-constants";
import * as Notifications from "expo-notifications";
import type { Api } from "./api";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false,
  }),
});

function apnsEnv(): "production" | "sandbox" {
  // TestFlight and App Store builds use Apple's production gateway; a local Xcode build uses sandbox.
  return __DEV__ || Constants.appOwnership === "expo" ? "sandbox" : "production";
}

export async function registerForPush(api: Api): Promise<void> {
  if (Platform.OS !== "ios") return;
  try {
    const { status: existing } = await Notifications.getPermissionsAsync();
    let status = existing;
    if (existing !== "granted") status = (await Notifications.requestPermissionsAsync()).status;
    if (status !== "granted") return;
    const device = await Notifications.getDevicePushTokenAsync();
    if (!device?.data) return;
    await api.registerPush(String(device.data), "ios", apnsEnv());
  } catch {
    // no APNs on the simulator, or the user said no: fine
  }
}

export function useNotificationTaps(onOpen: (data: Record<string, unknown>) => void) {
  useEffect(() => {
    const sub = Notifications.addNotificationResponseReceivedListener((r) => {
      onOpen((r.notification.request.content.data ?? {}) as Record<string, unknown>);
    });
    Notifications.getLastNotificationResponseAsync().then((r) => {
      if (r) onOpen((r.notification.request.content.data ?? {}) as Record<string, unknown>);
    }).catch(() => {});
    return () => sub.remove();
  }, [onOpen]);
}
