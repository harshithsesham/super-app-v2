// App shell: the space theme over Muse's structure. Hub first, then the
// long conversation, Ideas, Goals, Library. The avatar with its status
// pill sits at the top of every tab, and the orb hangs at the edge for voice.
import Constants from "expo-constants";
import { StatusBar } from "expo-status-bar";
import { useFonts } from "expo-font";
import { InstrumentSans_400Regular, InstrumentSans_600SemiBold } from "@expo-google-fonts/instrument-sans";
import { InstrumentSerif_400Regular } from "@expo-google-fonts/instrument-serif";
import { JetBrainsMono_400Regular } from "@expo-google-fonts/jetbrains-mono";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Keyboard, KeyboardAvoidingView, Platform, StyleSheet, Text, View } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { Pressable } from "./src/ui/Tap";
import { Avatar } from "./src/ui/Avatar";
import { Stars } from "./src/ui/Stars";
import { Orb } from "./src/ui/Orb";
import { ChatIcon, GoalsIcon, HubIcon, IdeasIcon, LibraryIcon, MenuIcon } from "./src/ui/Icons";
import { C, F } from "./src/theme";
import {
  AgentSocket, Api, clearSession, loadSession,
  type ActivityEvent, type Approval, type BrowserTask, type ChatMessage, type Frame, type Session,
} from "./src/api";
import { ApprovalCard } from "./src/ui/ApprovalCard";
import { BrowserCard } from "./src/ui/BrowserCard";
import { SignInScreen } from "./src/screens/SignInScreen";
import { registerForPush, useNotificationTaps } from "./src/push";
import { HubScreen } from "./src/screens/HubScreen";
import { ChatScreen, describe, statusTitle, type LiveTurn } from "./src/screens/ChatScreen";
import { IdeasScreen } from "./src/screens/IdeasScreen";
import { GoalsScreen } from "./src/screens/GoalsScreen";
import { LibraryScreen } from "./src/screens/LibraryScreen";
import { ConnectorsScreen } from "./src/screens/ConnectorsScreen";
import { MemoryScreen } from "./src/screens/MemoryScreen";
import { ActivitySheet } from "./src/screens/ActivitySheet";
import { MenuSheet } from "./src/screens/MenuSheet";

const extra = (Constants.expoConfig?.extra ?? {}) as { apiUrl?: string; apiToken?: string };
type Tab = "hub" | "chat" | "ideas" | "goals" | "library";
type Page = "connectors" | "memory" | null;

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <View style={{ flex: 1, backgroundColor: C.bg, justifyContent: "center", padding: 32 }}>
          <Text style={{ color: C.red, fontSize: 16, marginBottom: 12 }}>Something broke on this screen.</Text>
          <Text style={{ color: C.muted, fontSize: 12, marginBottom: 24 }}>{String(this.state.error?.message ?? this.state.error)}</Text>
          <Pressable style={{ backgroundColor: C.accent, borderRadius: 12, padding: 14, alignItems: "center" }} onPress={() => this.setState({ error: null })}>
            <Text style={{ color: C.onAccent, fontWeight: "600" }}>Try again</Text>
          </Pressable>
        </View>
      );
    }
    return this.props.children;
  }
}

export default function AppRoot() {
  return (
    <ErrorBoundary>
      <SafeAreaProvider>
        <App />
      </SafeAreaProvider>
    </ErrorBoundary>
  );
}

function App() {
  const [fontsLoaded] = useFonts({ InstrumentSerif_400Regular, InstrumentSans_400Regular, InstrumentSans_600SemiBold, JetBrainsMono_400Regular });
  const [auth, setAuth] = useState<"loading" | "signin" | "ready">("loading");
  const [session, setSession] = useState<Session | null>(null);
  const [tab, setTab] = useState<Tab>("hub");
  const [page, setPage] = useState<Page>(null);
  const [menu, setMenu] = useState(false);
  const [activity, setActivity] = useState(false);

  const [assistant, setAssistant] = useState("Muse");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [live, setLive] = useState<LiveTurn>(null);
  const [busy, setBusy] = useState(false);
  const [connection, setConnection] = useState<"connecting" | "open" | "closed">("connecting");
  const [liveEvents, setLiveEvents] = useState<ActivityEvent[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [deciding, setDeciding] = useState<string | null>(null);
  const [browser, setBrowser] = useState<BrowserTask | null>(null);
  const [lastReply, setLastReply] = useState<{ seq: number; text: string } | null>(null);
  const [speak, setSpeak] = useState<{ seq: number; text: string } | null>(null);
  const [canSpeak, setCanSpeak] = useState(false);
  const [keyboard, setKeyboard] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const socket = useRef<AgentSocket | null>(null);

  // Runtime problems show as a passing line under the name, never as chat bubbles.
  const showNotice = useCallback((text: string) => {
    setNotice(text);
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    noticeTimer.current = setTimeout(() => setNotice(null), 8000);
  }, []);

  useEffect(() => {
    const show = Keyboard.addListener(Platform.OS === "ios" ? "keyboardWillShow" : "keyboardDidShow", () => setKeyboard(true));
    const hide = Keyboard.addListener(Platform.OS === "ios" ? "keyboardWillHide" : "keyboardDidHide", () => setKeyboard(false));
    return () => { show.remove(); hide.remove(); };
  }, []);

  useEffect(() => {
    (async () => {
      const stored = await loadSession();
      if (stored) { setSession(stored); setAuth("ready"); return; }
      if (extra.apiUrl && extra.apiToken) { setSession({ url: extra.apiUrl, token: extra.apiToken }); setAuth("ready"); return; }
      setAuth("signin");
    })();
  }, []);

  const onFrame = useCallback((f: Frame) => {
    switch (f.type) {
      case "history":
        setMessages(f.messages);
        setAssistant(f.assistant && f.assistant !== "your assistant" ? f.assistant : "Muse");
        setBusy(f.status === "running");
        if (f.status !== "running") setLive(null);
        break;
      case "turn_start":
        setBusy(true);
        if (f.user_text) setMessages((m) => [...m, { role: "user", text: f.user_text! }]);
        setLive({ text: "", steps: [] });
        break;
      case "text_delta":
        setLive((l) => ({ text: (l?.text ?? "") + f.text, steps: l?.steps ?? [] }));
        break;
      case "event": {
        setLiveEvents((e) => [...e.slice(-200), { ts: f.ts, kind: f.kind, data: f.data }]);
        const line = describe(f.kind, f.data);
        if (line) setLive((l) => ({ text: l?.text ?? "", steps: [...(l?.steps ?? []), line] }));
        break;
      }
      case "turn_end":
        setBusy(false); setLive(null);
        if (f.text) {
          setMessages((m) => [...m, { role: "assistant", text: f.text }]);
          setLastReply((r) => ({ seq: (r?.seq ?? 0) + 1, text: f.text }));
        }
        break;
      case "approval":
        setApprovals((a) => [...a.filter((x) => x.id !== f.approval.id), f.approval]);
        setTab("chat");
        break;
      case "approval_resolved":
        setApprovals((a) => a.filter((x) => x.id !== f.id));
        break;
      case "browser":
        setBrowser(f.task);
        break;
      case "error":
        setBusy(false); setLive(null);
        showNotice(f.message);
        break;
    }
  }, []);

  useEffect(() => {
    if (auth !== "ready" || !session) return;
    const s = new AgentSocket(session, onFrame, setConnection);
    s.connect();
    socket.current = s;
    return () => { s.close(); socket.current = null; };
  }, [auth, session, onFrame]);

  const api = useMemo(() => (session ? new Api(session) : null), [session]);

  useEffect(() => {
    if (connection !== "open" || !api) return;
    api.approvals().then((r) => setApprovals(r.approvals)).catch(() => {});
    api.voiceStatus().then((v) => setCanSpeak(v.tts)).catch(() => setCanSpeak(false));
  }, [connection, api]);

  useEffect(() => {
    if (auth === "ready" && api) registerForPush(api);
  }, [auth, api]);

  useNotificationTaps(useCallback((data: Record<string, unknown>) => {
    setPage(null); setMenu(false); setActivity(false);
    setTab(data.tab === "chat" || data.approval ? "chat" : "hub");
  }, []));

  const decide = useCallback(async (id: string, decision: "allow" | "deny") => {
    if (!api) return;
    setDeciding(id);
    try { await api.resolveApproval(id, decision); } catch {}
    setApprovals((a) => a.filter((x) => x.id !== id));
    setDeciding(null);
  }, [api]);

  const sendToChat = useCallback((text: string) => { setTab("chat"); socket.current?.send(text); }, []);
  const sendFromOrb = useCallback((text: string) => { socket.current?.send(text); }, []);

  const signOut = useCallback(async () => {
    await clearSession();
    socket.current?.close();
    setSession(null); setMessages([]); setPage(null); setMenu(false);
    setAuth("signin");
  }, []);

  if (!fontsLoaded || auth === "loading") {
    return <View style={{ flex: 1, backgroundColor: C.bg, justifyContent: "center", alignItems: "center" }}><ActivityIndicator color={C.accent} /></View>;
  }
  if (auth === "signin" || !session || !api) {
    return <SignInScreen defaultUrl={extra.apiUrl ?? ""} defaultToken={extra.apiToken} onSignedIn={(s) => { setSession(s); setAuth("ready"); }} />;
  }

  if (page === "connectors") return <SafeAreaView style={s.root} edges={["top"]}><Stars /><StatusBar style="light" /><ConnectorsScreen api={api} onBack={() => setPage(null)} /></SafeAreaView>;
  if (page === "memory") return <SafeAreaView style={s.root} edges={["top"]}><Stars /><StatusBar style="light" /><MemoryScreen api={api} onBack={() => setPage(null)} /></SafeAreaView>;

  const status = notice ?? (busy ? statusTitle(live?.steps ?? []) : connection === "open" ? null : "Reconnecting…");
  const showHeader = tab !== "hub";

  return (
    <SafeAreaView style={s.root} edges={["top", "left", "right"]}>
      <Stars />
      <StatusBar style="light" />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      {showHeader ? (
        <View style={s.header}>
          {tab === "chat" ? (
            <Pressable style={s.menuBtn} feel="control" onPress={() => setMenu(true)}><MenuIcon /></Pressable>
          ) : <View style={{ width: 48 }} />}
          <Pressable style={s.avatarWrap} onPress={() => setActivity(true)}>
            <Avatar size={64} />
            <View style={s.namePill}>
              <Text style={s.name}>{assistant}</Text>
              {status ? <Text style={s.status} numberOfLines={1}>{status}</Text> : null}
            </View>
          </Pressable>
          <View style={{ width: 48 }} />
        </View>
      ) : null}

      <View style={s.body}>
        {tab === "hub" ? (
          <HubScreen api={api} assistant={assistant}
            onAsk={sendToChat}
            onPlay={(text) => setSpeak((p) => ({ seq: (p?.seq ?? 0) + 1, text }))}
            onConnect={() => setPage("connectors")} />
        ) : tab === "chat" ? (
          <ChatScreen assistant={assistant} messages={messages} live={live} busy={busy}
            onSend={(t) => socket.current?.send(t)} onStop={() => socket.current?.stop()}
            card={browser ? <BrowserCard task={browser} onStop={() => { api.stopBrowserTask(browser.task_id).catch(() => {}); }} /> : null}
            footer={approvals.length ? (
              <ApprovalCard approval={approvals[0]} busy={deciding === approvals[0].id} onDecide={(d) => decide(approvals[0].id, d)} />
            ) : null} />
        ) : tab === "ideas" ? (
          <IdeasScreen api={api} onStart={(i) => sendToChat(`Yes, go ahead: ${i.title}`)} />
        ) : tab === "goals" ? (
          <GoalsScreen api={api} onDiscuss={(g) => sendToChat(`Let's work on my goal: ${g.title}`)} />
        ) : (
          <LibraryScreen api={api} />
        )}
      </View>

      <Orb session={session} assistant={assistant} busy={busy} lastReply={lastReply} onSend={sendFromOrb} speak={speak} canSpeak={canSpeak} />

      {keyboard ? null : <View style={s.tabWrap}>
        <View style={s.tabBar}>
          {([
            ["hub", HubIcon], ["chat", ChatIcon], ["ideas", IdeasIcon], ["goals", GoalsIcon], ["library", LibraryIcon],
          ] as const).map(([t, Icon]) => (
            <Pressable key={t} style={[s.tabItem, tab === t && s.tabActive]} feel="control" onPress={() => setTab(t)}>
              <Icon active={tab === t} />
            </Pressable>
          ))}
        </View>
      </View>}
      </KeyboardAvoidingView>

      <MenuSheet visible={menu} assistant={assistant} onClose={() => setMenu(false)}
        onOpen={(sc) => { setMenu(false); if (sc === "signout") signOut(); else setPage(sc); }} />
      <ActivitySheet api={api} assistant={assistant} visible={activity} onClose={() => setActivity(false)} liveCount={liveEvents.length} />
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
  header: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", paddingHorizontal: 16, paddingTop: 4, height: 118 },
  menuBtn: { width: 48, height: 48, borderRadius: 24, backgroundColor: C.surface, alignItems: "center", justifyContent: "center", marginTop: 8,
    borderWidth: 1, borderColor: C.border },
  avatarWrap: { alignItems: "center" },
  namePill: { marginTop: -14, backgroundColor: C.surface, borderRadius: 16, paddingHorizontal: 14, paddingVertical: 6, alignItems: "center",
    borderWidth: 1, borderColor: C.border, maxWidth: 240 },
  name: { fontFamily: F.sansSemi, fontSize: 16, color: C.text },
  status: { fontFamily: F.mono, fontSize: 10, letterSpacing: 1.5, color: C.muted, marginTop: 2 },
  body: { flex: 1 },
  tabWrap: { alignItems: "center", paddingTop: 6, paddingBottom: 26, backgroundColor: "transparent" },
  tabBar: { flexDirection: "row", backgroundColor: "rgba(20,16,31,0.96)", borderRadius: 36, padding: 6, gap: 2, borderWidth: 1, borderColor: C.border,
    shadowColor: "#000", shadowOpacity: 0.4, shadowRadius: 16, shadowOffset: { width: 0, height: 6 } },
  tabItem: { width: 52, height: 52, borderRadius: 26, alignItems: "center", justifyContent: "center" },
  tabActive: { backgroundColor: "rgba(199,184,255,0.14)" },
});
