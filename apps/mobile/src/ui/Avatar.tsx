// The agent's avatar: a soft beige figure with a small face, sized to fit the
// chat header or a list row. The real app renders a 3D character; this is
// the placeholder until avatar generation lands.
import React from "react";
import { StyleSheet, View } from "react-native";
import { C } from "../theme";

export function Avatar({ size = 64 }: { size?: number }) {
  const eye = Math.max(3, size * 0.06);
  return (
    <View style={[s.wrap, { width: size, height: size * 1.05, borderRadius: size / 2 }]}>
      <View style={[s.hood, { width: size * 0.62, height: size * 0.62, borderRadius: size * 0.31, top: size * 0.1 }]} />
      <View style={[s.face, { width: size * 0.46, height: size * 0.4, borderRadius: size * 0.2, top: size * 0.2 }]}>
        <View style={[s.eyes, { gap: size * 0.14, marginTop: size * 0.12 }]}>
          <View style={{ width: eye, height: eye, borderRadius: eye, backgroundColor: C.text }} />
          <View style={{ width: eye, height: eye, borderRadius: eye, backgroundColor: C.text }} />
        </View>
        <View style={[s.smile, { width: size * 0.1, height: size * 0.05, borderRadius: size * 0.05, marginTop: size * 0.05 }]} />
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { backgroundColor: C.avatar, alignItems: "center", overflow: "hidden" },
  hood: { position: "absolute", backgroundColor: C.avatarShade },
  face: { position: "absolute", backgroundColor: "#F6EEE4", alignItems: "center" },
  eyes: { flexDirection: "row" },
  smile: { borderBottomWidth: 2, borderColor: C.text, borderRadius: 8 },
});
