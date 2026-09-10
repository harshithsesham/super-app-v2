// REST + WebSocket client for the superapp daemon.
import * as SecureStore from "expo-secure-store";

export type Session = { url: string; token: string; user?: string; name?: string };

export type ChatMessage = { role: "user" | "assistant" | "handoff"; text: string };
export type ActivityEvent = { ts: number; kind: string; data: Record<string, any> };
export type Subagent = { spawn_id: string; label: string; status: string };
export type FileEntry = { path: string; bytes: number; mtime: number };
export type Skill = { name: string; status: string; description: string; path: string };
export type FeedPost = { id: string; kicker: string; category: string; title: string; body: string; ts: number };
export type Idea = { id: string; icon: string; title: string; body: string };
export type Goal = { id: string; title: string; category: string; done: boolean; plan?: string[] };
export type Approval = { id: string; kind: string; title: string; subtitle: string; details: { label: string; value: string }[]; decision: string | null };
export type Connector = { provider: string; status: "connected" | "available"; configured: boolean; email: string | null };
export type BrowserTask = { task_id: string; title: string; status: string; status_title: string; url: string; screenshot?: string };
export type Hub = {
  greeting: string; stamp: string;
  brief: { ready: boolean; title: string; sub: string; text: string; kicker?: string };
  inbox: { connected: boolean; email?: string | null; headline: string; body: string; stats: { n: number; label: string }[] };
  goals: { open: number; done: number };
  grid: { name: string; skill: string; tone: string; ask: string; status: string; sub: string }[];
};

export type Frame =
  | { type: "history"; messages: ChatMessage[]; assistant: string; status: string }
  | { type: "turn_start"; user_text: string | null }
  | { type: "text_delta"; text: string }
  | { type: "event"; kind: string; data: Record<string, any>; ts: number }
  | { type: "turn_end"; text: string }
  | { type: "approval"; approval: Approval }
  | { type: "approval_resolved"; id: string; decision: string }
  | { type: "browser"; task: BrowserTask }
  | { type: "error"; message: string };

const KEY = "session";

export async function loadSession(): Promise<Session | null> {
  try {
    const raw = await SecureStore.getItemAsync(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}
export async function saveSession(s: Session) {
  await SecureStore.setItemAsync(KEY, JSON.stringify(s));
}
export async function clearSession() {
  await SecureStore.deleteItemAsync(KEY);
}

export class Api {
  constructor(public session: Session) {}
  private get headers() {
    return { Authorization: `Bearer ${this.session.token}`, "Content-Type": "application/json" };
  }
  private async req<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${this.session.url}${path}`, { ...init, headers: this.headers });
    if (!res.ok) throw new Error(`${path}: ${res.status}`);
    return (await res.json()) as T;
  }
  me() {
    return this.req<{ user: string; assistant: string; model: string; status: string; identity: string; user_md: string }>("/v1/me");
  }
  history() { return this.req<{ messages: ChatMessage[] }>("/v1/history"); }
  activity() { return this.req<{ events: ActivityEvent[]; subagents: Subagent[]; status: string }>("/v1/activity"); }
  memory() { return this.req<{ "MEMORY.md": string; today: string; people: string }>("/v1/memory"); }
  files() { return this.req<{ files: FileEntry[] }>("/v1/files"); }
  skills() { return this.req<{ skills: Skill[] }>("/v1/skills"); }
  feed() { return this.req<{ posts: FeedPost[] }>("/v1/feed"); }
  ideas() { return this.req<{ ideas: Idea[] }>("/v1/ideas"); }
  goals() { return this.req<{ goals: Goal[] }>("/v1/goals"); }
  setGoals(goals: Goal[]) { return this.req<{ goals: Goal[] }>("/v1/goals", { method: "PUT", body: JSON.stringify({ goals }) }); }
  approvals() { return this.req<{ approvals: Approval[] }>("/v1/approvals"); }
  resolveApproval(id: string, decision: "allow" | "deny") {
    return this.req<{ id: string; decision: string }>(`/v1/approvals/${id}`, { method: "POST", body: JSON.stringify({ decision }) });
  }
  connectors() { return this.req<{ connectors: Connector[] }>("/v1/connectors"); }
  browserTasks() { return this.req<{ tasks: BrowserTask[]; cards: BrowserTask[] }>("/v1/browser/tasks"); }
  hub() { return this.req<Hub>("/v1/hub"); }
  voiceStatus() { return this.req<{ tts: boolean; voice_id: string }>("/v1/voice/status"); }
  stopBrowserTask(id: string) { return this.req<{ task_id: string }>(`/v1/browser/tasks/${id}/stop`, { method: "POST" }); }
  gmailAuthUrl() { return this.req<{ auth_url: string }>("/v1/gmail/auth-url"); }
  gmailDisconnect() { return this.req<{ removed: boolean }>("/v1/gmail/disconnect", { method: "POST" }); }
  fileUrl(path: string) { return `${this.session.url}/v1/files/${encodeURI(path)}`; }
}

// The live channel. Reconnects with backoff; the server replays history on
// every (re)connect so the client can always rebuild from the first frame.
export class AgentSocket {
  private ws: WebSocket | null = null;
  private closed = false;
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  constructor(
    private session: Session,
    private onFrame: (f: Frame) => void,
    private onState: (s: "connecting" | "open" | "closed") => void,
  ) {}

  connect() {
    this.closed = false;
    this.onState("connecting");
    const base = this.session.url.replace(/^http/, "ws").replace(/\/$/, "");
    const ws = new WebSocket(`${base}/v1/ws?token=${encodeURIComponent(this.session.token)}`);
    this.ws = ws;
    ws.onopen = () => { this.attempt = 0; this.onState("open"); };
    ws.onmessage = (ev) => {
      try { this.onFrame(JSON.parse(String(ev.data)) as Frame); } catch {}
    };
    ws.onclose = () => { this.onState("closed"); if (!this.closed) this.scheduleReconnect(); };
    ws.onerror = () => { /* onclose follows */ };
  }
  private scheduleReconnect() {
    const delay = Math.min(15000, 500 * 2 ** this.attempt++);
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.connect(), delay);
  }
  send(text: string) { this.ws?.send(JSON.stringify({ type: "message", text })); }
  stop() { this.ws?.send(JSON.stringify({ type: "stop" })); }
  close() { this.closed = true; if (this.timer) clearTimeout(this.timer); this.ws?.close(); }
}
