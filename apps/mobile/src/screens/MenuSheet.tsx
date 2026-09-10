// The hamburger: side chats, then the settings entries (Connectors, Memory,
// Sign out). Side chats arrive with the chat.* tools; today only Main chat.
import React from "react";
import { Modal, StyleSheet, Text, View } from "react-native";
import { Pressable } from "../ui/Tap";
import { C, R } from "../theme";

export function MenuSheet({ visible, onClose, onOpen, assistant }: {
  visible: boolean; onClose: () => void; onOpen: (screen: "connectors" | "memory" | "signout") => void; assistant: string;
}) {
  return (
    <Modal visible={visible} animationType="fade" transparent onRequestClose={onClose}>
      <Pressable style={s.backdrop} onPress={onClose}>
        <View style={s.panel}>
          <Text style={s.section}>Chats</Text>
          <View style={s.card}>
            <View style={[s.row, s.rowActive]}><Text style={s.rowText}>Main chat</Text><Text style={s.chev}>›</Text></View>
            <Pressable style={s.row} onPress={onClose}><Text style={[s.rowText, { color: C.muted }]}>New side chat</Text><Text style={s.plus}>+</Text></Pressable>
          </View>
          <Text style={s.section}>{assistant}</Text>
          <View style={s.card}>
            <Pressable style={s.row} onPress={() => onOpen("connectors")}><Text style={s.rowText}>Connectors</Text><Text style={s.chev}>›</Text></Pressable>
            <Pressable style={s.row} onPress={() => onOpen("memory")}><Text style={s.rowText}>Memory</Text><Text style={s.chev}>›</Text></Pressable>
            <Pressable style={[s.row, { borderBottomWidth: 0 }]} onPress={() => onOpen("signout")}><Text style={[s.rowText, { color: C.red }]}>Sign out</Text></Pressable>
          </View>
        </View>
      </Pressable>
    </Modal>
  );
}

const s = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.25)", flexDirection: "row" },
  panel: { width: "80%", backgroundColor: C.bg, paddingTop: 70, paddingHorizontal: 16, gap: 8 },
  section: { fontSize: 13, fontWeight: "600", color: C.muted, marginTop: 12, marginLeft: 4 },
  card: { backgroundColor: C.surface, borderRadius: R.card, paddingHorizontal: 14 },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: C.border },
  rowActive: {},
  rowText: { fontSize: 17, color: C.text },
  chev: { fontSize: 20, color: C.muted },
  plus: { fontSize: 20, color: C.muted },
});
