// Connector tiles: a rounded square with the service's mark, in its own colour,
// the way the Connectors list looks in Muse. Marks come from the bundled icon
// fonts; anything unknown falls back to a lettered tile in the app accent.
import React from "react";
import { StyleSheet, Text, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { FontAwesome6, Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { C } from "../theme";

type Spec = { lib: "fa6" | "mci" | "ion"; icon: string; bg?: string; color?: string; gradient?: string[]; brand?: boolean };

const SPECS: Record<string, Spec> = {
  gmail: { lib: "mci", icon: "gmail", bg: "#FFFFFF", color: "#EA4335" },
  "google-calendar": { lib: "mci", icon: "calendar-month", bg: "#FFFFFF", color: "#1A73E8" },
  "google-contacts": { lib: "mci", icon: "contacts", bg: "#FFFFFF", color: "#1A73E8" },
  "google-drive": { lib: "mci", icon: "google-drive", bg: "#FFFFFF", color: "#FBBC04" },
  "google-docs": { lib: "mci", icon: "file-document", bg: "#FFFFFF", color: "#4285F4" },
  "google-sheets": { lib: "mci", icon: "google-spreadsheet", bg: "#FFFFFF", color: "#0F9D58" },
  "google-slides": { lib: "mci", icon: "presentation", bg: "#FFFFFF", color: "#F4B400" },
  "google-tasks": { lib: "mci", icon: "check-circle", bg: "#FFFFFF", color: "#4285F4" },
  "google-forms": { lib: "mci", icon: "form-select", bg: "#FFFFFF", color: "#7248B9" },
  "google-health-connect": { lib: "mci", icon: "heart-pulse", bg: "#FFFFFF", color: "#4285F4" },
  "apple-healthkit": { lib: "fa6", icon: "heart", bg: "#FFFFFF", color: "#FF2D55" },
  browser: { lib: "fa6", icon: "globe", bg: "#111111", color: "#FFFFFF" },
  "facebook-cli": { lib: "fa6", icon: "facebook", bg: "#1877F2", color: "#FFFFFF", brand: true },
  instagram: { lib: "fa6", icon: "instagram", gradient: ["#F58529", "#DD2A7B", "#8134AF"], color: "#FFFFFF", brand: true },
  "instagram-messages": { lib: "fa6", icon: "instagram", gradient: ["#F58529", "#DD2A7B", "#8134AF"], color: "#FFFFFF", brand: true },
  messenger: { lib: "fa6", icon: "facebook-messenger", bg: "#0084FF", color: "#FFFFFF", brand: true },
  spotify: { lib: "fa6", icon: "spotify", bg: "#1DB954", color: "#FFFFFF", brand: true },
  threads: { lib: "fa6", icon: "threads", bg: "#000000", color: "#FFFFFF", brand: true },
  "threads-messages": { lib: "fa6", icon: "threads", bg: "#000000", color: "#FFFFFF", brand: true },
  "outlook-mail": { lib: "mci", icon: "microsoft-outlook", bg: "#0078D4", color: "#FFFFFF" },
  "outlook-calendar": { lib: "fa6", icon: "calendar", bg: "#0078D4", color: "#FFFFFF" },
  "outlook-contacts": { lib: "fa6", icon: "address-book", bg: "#0078D4", color: "#FFFFFF" },
  peloton: { lib: "fa6", icon: "person-biking", bg: "#DF1C2F", color: "#FFFFFF" },
  plaid: { lib: "fa6", icon: "building-columns", bg: "#111111", color: "#FFFFFF" },
  "function-health": { lib: "fa6", icon: "vial", bg: "#F26B3A", color: "#FFFFFF" },
  healthex: { lib: "fa6", icon: "heart-pulse", bg: "#1EAF8C", color: "#FFFFFF" },
  withings: { lib: "mci", icon: "scale-bathroom", bg: "#00A3A3", color: "#FFFFFF" },
  tessie: { lib: "fa6", icon: "car", bg: "#E82127", color: "#FFFFFF" },
  "philips-hue": { lib: "fa6", icon: "lightbulb", bg: "#7A3CE8", color: "#FFFFFF" },
  printify: { lib: "fa6", icon: "print", bg: "#39B54A", color: "#FFFFFF" },
  ticketmaster: { lib: "fa6", icon: "ticket", bg: "#026CDF", color: "#FFFFFF" },
  duffel: { lib: "fa6", icon: "plane", bg: "#E5546B", color: "#FFFFFF" },
  flightaware: { lib: "fa6", icon: "plane-departure", bg: "#0A2A66", color: "#FFFFFF" },
  calendly: { lib: "fa6", icon: "calendar-check", bg: "#006BFF", color: "#FFFFFF" },
  opentable: { lib: "fa6", icon: "utensils", bg: "#DA3743", color: "#FFFFFF" },
};

export function BrandIcon({ name, label, size = 40 }: { name: string; label?: string; size?: number }) {
  const spec = SPECS[name];
  const radius = size * 0.26;
  if (!spec) {
    return (
      <View style={[s.tile, { width: size, height: size, borderRadius: radius, backgroundColor: C.blueTint }]}>
        <Text style={{ color: C.accent, fontSize: size * 0.42, fontWeight: "700" }}>{(label ?? name).slice(0, 1).toUpperCase()}</Text>
      </View>
    );
  }
  const glyph = spec.lib === "fa6"
    ? <FontAwesome6 name={spec.icon as any} size={size * 0.5} color={spec.color} {...(spec.brand ? { iconStyle: "brand" } : {})} />
    : spec.lib === "mci"
      ? <MaterialCommunityIcons name={spec.icon as any} size={size * 0.58} color={spec.color} />
      : <Ionicons name={spec.icon as any} size={size * 0.55} color={spec.color} />;
  if (spec.gradient) {
    return (
      <LinearGradient colors={spec.gradient as [string, string, ...string[]]} start={{ x: 0, y: 1 }} end={{ x: 1, y: 0 }}
        style={[s.tile, { width: size, height: size, borderRadius: radius }]}>{glyph}</LinearGradient>
    );
  }
  return <View style={[s.tile, { width: size, height: size, borderRadius: radius, backgroundColor: spec.bg }]}>{glyph}</View>;
}

const s = StyleSheet.create({ tile: { alignItems: "center", justifyContent: "center", overflow: "hidden" } });
