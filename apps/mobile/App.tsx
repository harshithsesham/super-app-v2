// App shell, laid out like Muse: hamburger at top left, the avatar centered
// with a name pill that shows what it's doing, the active tab below, and a
// floating five-icon bar: Chat, Feed, Ideas, Goals, Library.
import Constants from "expo-constants";
import { StatusBar } from "expo-status-bar";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { Pressable } from "./src/ui/Tap";
import { Avatar } from "./src/ui/Avatar";
import { ChatIcon, FeedIcon, GoalsIcon, IdeasIcon, LibraryIcon, MenuIcon } from "./src/ui/Icons";
import { C, R } from "./src/theme";
import {
  AgentSocket, Api, clearSession, loadSession,
  type ActivityEvent, type Approval, type ChatMessage, type Frame, type Session,
} from "./src/api";
import { ApprovalCard } from "./src/ui/ApprovalCard";
import { SignInScreen } from "./src/screens/SignInScreen";
import { ChatScreen, describe, statusTitle, type LiveTurn } from "./src/screens/ChatScreen";
import { FeedScreen } from "./src/screens/FeedScreen";
import { IdeasScreen } from "./src/screens/IdeasScreen";
import { GoalsScreen } from "./src/screens/GoalsScreen";
import { LibraryScreen } from "./src/screens/LibraryScreen";
import { ConnectorsScreen } from "./src/screens/ConnectorsScreen";
import { MemoryScreen } from "./src/screens/MemoryScreen";
import { ActivitySheet } from "./src/screens/ActivitySheet";
import { MenuSheet } from "./src/screens/MenuSheet";

const extra = (Constants.expoConfig?.extra ?? {}) as { apiUrl?: string; apiToken?: string };
type Tab = "chat" | "feed" | "ideas" | "goals" | "library";
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
            <Text style={{ color: "#fff", fontWeight: "600" }}>Try again</Text>
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
  const [auth, setAuth] = useState<"loading" | "signin" | "ready">("loading");
  const [session, setSession] = useState<Session | null>(null);
  const [tab, setTab] = useState<Tab>("chat");
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
  const socket = useRef<AgentSocket | null>(null);

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
        if (f.text) setMessages((m) => [...m, { role: "assistant", text: f.text }]);
        break;
      case "approval":
        setApprovals((a) => [...a.filter((x) => x.id !== f.approval.id), f.approval]);
        setTab("chat");
        break;
      case "approval_resolved":
        setApprovals((a) => a.filter((x) => x.id !== f.id));
        break;
      case "error":
        setBusy(false); setLive(null);
        setMessages((m) => [...m, { role: "assistant", text: `Something went wrong: ${f.message}` }]);
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

  // Pending cards survive a reconnect: ask the daemon for them whenever the socket opens.
  useEffect(() => {
    if (connection !== "open" || !api) return;
    api.approvals().then((r) => setApprovals(r.approvals)).catch(() => {});
  }, [connection, api]);

  const decide = useCallback(async (id: string, decision: "allow" | "deny") => {
    if (!api) return;
    setDeciding(id);
    try { await api.resolveApproval(id, decision); } catch {}
    setApprovals((a) => a.filter((x) => x.id !== id));
    setDeciding(null);
  }, [api]);

  const sendToChat = useCallback((text: string) => {
    setTab("chat");
    socket.current?.send(text);
  }, []);

  const signOut = useCallback(async () => {
    await clearSession();
    socket.current?.close();
    setSession(null); setMessages([]); setPage(null); setMenu(false);
    setAuth("signin");
  }, []);

  if (auth === "loading") {
    return <View style={{ flex: 1, backgroundColor: C.bg, justifyContent: "center", alignItems: "center" }}><ActivityIndicator color={C.accent} /></View>;
  }
  if (auth === "signin" || !session || !api) {
    return <SignInScreen defaultUrl={extra.apiUrl ?? ""} defaultToken={extra.apiToken} onSignedIn={(s) => { setSession(s); setAuth("ready"); }} />;
  }

  if (page === "connectors") return <SafeAreaView style={s.root} edges={["top"]}><StatusBar style="dark" /><ConnectorsScreen api={api} onBack={() => setPage(null)} /></SafeAreaView>;
  if (page === "memory") return <SafeAreaView style={s.root} edges={["top"]}><StatusBar style="dark" /><MemoryScreen api={api} onBack={() => setPage(null)} /></SafeAreaView>;

  const status = busy ? statusTitle(live?.steps ?? []) : connection === "open" ? null : "Reconnecting…";

  return (
    <SafeAreaView style={s.root} edges={["top", "left", "right"]}>
      <StatusBar style="dark" />
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

      <View style={s.body}>
        {tab === "chat" ? (
          <>
            <ChatScreen assistant={assistant} messages={messages} live={live} busy={busy}
              onSend={(t) => socket.current?.send(t)} onStop={() => socket.current?.stop()}
              footer={approvals.length ? (
                <ApprovalCard approval={approvals[0]} busy={deciding === approvals[0].id}
                  onDecide={(d) => decide(approvals[0].id, d)} />
              ) : null} />
          </>
        ) : tab === "feed" ? (
          <FeedScreen api={api} onDiscuss={(p) => sendToChat(`Let's discuss this from my feed: "${p.title}"`)} />
        ) : tab === "ideas" ? (
          <IdeasScreen api={api} onStart={(i) => sendToChat(`Yes, go ahead: ${i.title}`)} />
        ) : tab === "goals" ? (
          <GoalsScreen api={api} onDiscuss={(g) => sendToChat(`Let's work on my goal: ${g.title}`)} />
        ) : (
          <LibraryScreen api={api} />
        )}
      </View>

      <View style={s.tabWrap}>
        <View style={s.tabBar}>
          {([
            ["chat", ChatIcon], ["feed", FeedIcon], ["ideas", IdeasIcon], ["goals", GoalsIcon], ["library", LibraryIcon],
          ] as const).map(([t, Icon]) => (
            <Pressable key={t} style={[s.tabItem, tab === t && s.tabActive]} feel="control" onPress={() => setTab(t)}>
              <Icon active={tab === t} />
            </Pressable>
          ))}
        </View>
      </View>

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
    shadowColor: "#000", shadowOpacity: 0.05, shadowRadius: 6, shadowOffset: { width: 0, height: 2 } },
  avatarWrap: { alignItems: "center" },
  namePill: { marginTop: -14, backgroundColor: C.surface, borderRadius: 16, paddingHorizontal: 14, paddingVertical: 6, alignItems: "center",
    shadowColor: "#000", shadowOpacity: 0.05, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, maxWidth: 240 },
  name: { fontSize: 17, fontWeight: "700", color: C.text },
  status: { fontSize: 14, color: C.muted, marginTop: 1 },
  body: { flex: 1 },
  tabWrap: { alignItems: "center", paddingTop: 6, paddingBottom: 26, backgroundColor: C.bg },
  tabBar: { flexDirection: "row", backgroundColor: C.surface, borderRadius: 36, padding: 6, gap: 4,
    shadowColor: "#000", shadowOpacity: 0.1, shadowRadius: 16, shadowOffset: { width: 0, height: 6 } },
  tabItem: { width: 58, height: 58, borderRadius: 29, alignItems: "center", justifyContent: "center" },
  tabActive: { backgroundColor: C.card },
});
