// The Main chat, as Muse draws it: one long thread, gray bubbles from the
// agent on the left, pale-blue bubbles from you on the right, cards inline
// for work in progress, a typing bubble while it thinks, and a "+ Message"
// pill with a mic at the bottom.
import React, { useCallback, useMemo, useState } from "react";
import { FlatList, StyleSheet, Text, TextInput, View } from "react-native";
import { Pressable } from "../ui/Tap";
import { MicIcon } from "../ui/Icons";
import { C, R } from "../theme";
import { CredentialCard } from "../ui/CredentialCard";
import type { CredentialRequest } from "../api";
import type { ChatMessage } from "../api";

export type LiveTurn = { text: string; steps: string[] } | null;

type Row =
  | { key: string; kind: "msg"; msg: ChatMessage }
  | { key: string; kind: "card" }
  | { key: string; kind: "live"; live: NonNullable<LiveTurn> };

// One user-facing line per runtime event, in the voice of the app rather
// than the tool namespace. Returns null for events not worth showing.
export function describe(kind: string, data: Record<string, any>): string | null {
  const t = String(data.tool ?? "");
  switch (kind) {
    case "tool_call":
      if (t === "muse.exec") return "Running a command…";
      if (t === "muse.read") return "Reading a file…";
      if (t === "muse.write" || t === "muse.edit") return "Writing a file…";
      if (t === "muse.memory_search") return "Checking memory…";
      if (t === "subagent.spawn") return `Delegating: ${String(data.args?.label ?? "a task")}`;
      if (t.startsWith("browser.")) return "Using the browser…";
      if (t.startsWith("todo.")) return null;
      return `${t.split(".").pop()}…`;
    case "subagent_spawn": return `Started: ${data.label ?? "background work"}`;
    case "handoff": return "Result arrived";
    case "compaction": return null;
    default: return null;
  }
}

// A short verb-first status for the name pill under the avatar, like
// "Booking reservation…" in the real app.
export function statusTitle(steps: string[]): string {
  const last = steps[steps.length - 1];
  return last ?? "Thinking…";
}

function TypingDots() {
  return (
    <View style={s.typing}>
      {[0, 1, 2].map((i) => (
        <View key={i} style={[s.dot, { opacity: 0.35 + i * 0.25 }]} />
      ))}
    </View>
  );
}

function WorkCard({ steps }: { steps: string[] }) {
  const current = steps[steps.length - 1];
  return (
    <View style={s.workCard}>
      <View style={s.workHead}>
        <View style={s.workIcon}><Text style={{ fontSize: 16 }}>⚙️</Text></View>
        <View style={{ flex: 1 }}>
          <Text style={s.workTitle}>Working</Text>
          <Text style={s.workSub} numberOfLines={1}>{current}</Text>
        </View>
      </View>
      {steps.length > 1 ? (
        <View style={s.workSteps}>
          {steps.slice(-4, -1).map((st, i) => <Text key={i} style={s.workStep}>{st}</Text>)}
        </View>
      ) : null}
    </View>
  );
}

export function ChatScreen({
  assistant,
  messages,
  live,
  busy,
  onSend,
  onStop,
  footer,
  card,
  credRequests,
  onDeclineCredential,
  onCredentialSaved,
}: {
  assistant: string;
  messages: ChatMessage[];
  live: LiveTurn;
  busy: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  footer?: React.ReactNode;
  card?: React.ReactNode;   // an inline card that follows the thread (browser task)
  credRequests?: Record<string, CredentialRequest>;
  onDeclineCredential?: (id: string) => void;
  onCredentialSaved?: () => void;
}) {
  const [draft, setDraft] = useState("");

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = messages.map((m, i) => ({ key: `m${i}`, kind: "msg", msg: m }));
    if (card) out.push({ key: "card", kind: "card" });
    if (live) out.push({ key: "live", kind: "live", live });
    return out.reverse();   // inverted list: index 0 is the newest, pinned at the bottom
  }, [messages, live, card]);

  const send = useCallback(() => {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    onSend(text);
  }, [draft, onSend]);

  const render = ({ item }: { item: Row }) => {
    if (item.kind === "card") {
      return <View style={s.agentCol}>{card}</View>;
    }
    if (item.kind === "live") {
      return (
        <View style={s.agentCol}>
          {item.live.steps.length ? <WorkCard steps={item.live.steps} /> : null}
          {item.live.text ? (
            <View style={s.agentBubble}><Text style={s.agentText}>{item.live.text}</Text></View>
          ) : (
            <TypingDots />
          )}
        </View>
      );
    }
    const m = item.msg;
    if (m.role === "user") {
      return (
        <View style={s.userCol}>
          <View style={s.userBubble}><Text style={s.userText}>{m.text}</Text></View>
        </View>
      );
    }
    if (m.role === "handoff") {
      return (
        <View style={s.agentCol}>
          <View style={s.handoffCard}>
            <Text style={s.handoffTitle}>Background work finished</Text>
            <Text style={s.handoffText} numberOfLines={2}>{m.text.split("\n").slice(1).join(" ").slice(0, 160)}</Text>
          </View>
        </View>
      );
    }
    // Secure Store cards ride inside the reply as [[secure-store:<id>]] lines, like Muse's embed tokens
    const parts = m.text.split(/^\s*\[\[secure-store:([a-z0-9_]+)\]\]\s*$/m);
    if (parts.length > 1) {
      return (
        <View style={[s.agentCol, { gap: 8 }]}>
          {parts.map((part, i) => {
            if (i % 2 === 1) {
              const req = credRequests?.[part];
              return req ? <CredentialCard key={part} request={req} onDecline={onDeclineCredential} onSaved={onCredentialSaved} /> : null;
            }
            return part.trim() ? <View key={i} style={s.agentBubble}><Text style={s.agentText}>{part.trim()}</Text></View> : null;
          })}
        </View>
      );
    }
    return (
      <View style={s.agentCol}>
        <View style={s.agentBubble}><Text style={s.agentText}>{m.text}</Text></View>
      </View>
    );
  };

  return (
    <View style={s.root}>
      <FlatList
        data={rows}
        keyExtractor={(r) => r.key}
        renderItem={render}
        contentContainerStyle={s.list}
        keyboardDismissMode="interactive"
        inverted
        maintainVisibleContentPosition={{ minIndexForVisible: 0, autoscrollToTopThreshold: 120 }}
        ListEmptyComponent={
          <View style={[s.empty, { transform: [{ scaleY: -1 }] }]}>
            <Text style={s.emptyTitle}>Hi, I'm {assistant}.</Text>
            <Text style={s.emptySub}>Your personal agent. Tell me your name, what to call you, and what's on your plate. I'll remember, and I'll get to work.</Text>
          </View>
        }
      />
      {footer}
      <View style={s.inputWrap}>
        <View style={s.inputPill}>
          <Pressable feel="control" hitSlop={8} onPress={() => {}}>
            <Text style={s.plus}>+</Text>
          </Pressable>
          <TextInput
            style={s.input}
            value={draft}
            onChangeText={setDraft}
            placeholder="Message"
            placeholderTextColor={C.muted}
            multiline
            onSubmitEditing={send}
            blurOnSubmit
            returnKeyType="send"
          />
          {draft.trim() ? (
            <Pressable style={s.sendBtn} feel="control" onPress={send}>
              <Text style={s.sendText}>↑</Text>
            </Pressable>
          ) : busy ? (
            <Pressable style={[s.sendBtn, { backgroundColor: C.text }]} feel="control" onPress={onStop}>
              <Text style={s.sendText}>■</Text>
            </Pressable>
          ) : (
            <View style={{ paddingHorizontal: 4 }}><MicIcon /></View>
          )}
        </View>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
  list: { paddingHorizontal: 14, paddingTop: 12, paddingBottom: 6, gap: 8 },  // inverted: top is visual bottom
  agentCol: { alignItems: "flex-start", gap: 8, maxWidth: "88%" },
  userCol: { alignItems: "flex-end" },
  agentBubble: { backgroundColor: C.bubbleAgent, borderRadius: R.bubble, paddingHorizontal: 16, paddingVertical: 12 },
  agentText: { fontSize: 17, lineHeight: 23, color: C.text },
  userBubble: { backgroundColor: C.bubbleUser, borderRadius: R.bubble, paddingHorizontal: 16, paddingVertical: 12, maxWidth: "82%" },
  userText: { fontSize: 17, lineHeight: 23, color: C.text },
  typing: { flexDirection: "row", gap: 5, backgroundColor: C.bubbleAgent, borderRadius: R.bubble, paddingHorizontal: 16, paddingVertical: 16 },
  dot: { width: 9, height: 9, borderRadius: 5, backgroundColor: "#8C9099" },
  workCard: { backgroundColor: C.bubbleAgent, borderRadius: R.card, padding: 12, gap: 10, alignSelf: "stretch" },
  workHead: { flexDirection: "row", alignItems: "center", gap: 12 },
  workIcon: { width: 40, height: 40, borderRadius: 12, backgroundColor: C.blueTint, alignItems: "center", justifyContent: "center" },
  workTitle: { fontSize: 16, fontWeight: "600", color: C.text },
  workSub: { fontSize: 15, color: C.muted, marginTop: 1 },
  workSteps: { backgroundColor: C.surface, borderRadius: 14, padding: 10, gap: 4 },
  workStep: { fontSize: 13, color: C.muted },
  handoffCard: { backgroundColor: C.bubbleAgent, borderRadius: R.card, padding: 14, gap: 4 },
  handoffTitle: { fontSize: 15, fontWeight: "600", color: C.text },
  handoffText: { fontSize: 14, color: C.muted },
  empty: { paddingTop: 40, paddingHorizontal: 12, gap: 8 },
  emptyTitle: { fontSize: 24, fontWeight: "600", color: C.text },
  emptySub: { fontSize: 16, lineHeight: 23, color: C.body },
  inputWrap: { paddingHorizontal: 14, paddingBottom: 6, backgroundColor: C.bg },
  inputPill: {
    flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: C.surface, borderRadius: R.pill,
    paddingLeft: 16, paddingRight: 12, minHeight: 56, shadowColor: "#000", shadowOpacity: 0.06, shadowRadius: 10,
    shadowOffset: { width: 0, height: 2 },
  },
  plus: { fontSize: 26, color: C.text, lineHeight: 28 },
  input: { flex: 1, fontSize: 17, color: C.text, paddingVertical: 12, maxHeight: 140 },
  sendBtn: { width: 34, height: 34, borderRadius: 17, backgroundColor: C.accent, alignItems: "center", justifyContent: "center" },
  sendText: { color: C.onAccent, fontSize: 17, fontWeight: "700" },
});
