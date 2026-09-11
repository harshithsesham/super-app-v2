// Apple Health: read HealthKit on this phone and sync rollups, sessions, and
// samples into the user's cell, where the apple_healthkit skill reads them
// with health-cli. Nothing leaves the phone except this upload to the cell.
import { Platform } from "react-native";
import Constants from "expo-constants";
import * as SecureStore from "expo-secure-store";
import {
  CategoryValueSleepAnalysis, WorkoutActivityType, isHealthDataAvailable, requestAuthorization,
  queryCategorySamples, queryQuantitySamples, queryStatisticsForQuantity, queryWorkoutSamples,
} from "@kingstinct/react-native-healthkit";
import type { Api } from "./api";

const FLAG = "health_connected";

// identifier, output field, statistics, unit, aggregate kind
const DAILY: { id: any; field: string; stat: "sum" | "avg" | "minmax"; unit: string }[] = [
  { id: "HKQuantityTypeIdentifierStepCount", field: "steps", stat: "sum", unit: "count" },
  { id: "HKQuantityTypeIdentifierDistanceWalkingRunning", field: "distance_meters", stat: "sum", unit: "m" },
  { id: "HKQuantityTypeIdentifierActiveEnergyBurned", field: "active_energy_kcal", stat: "sum", unit: "kcal" },
  { id: "HKQuantityTypeIdentifierBasalEnergyBurned", field: "basal_energy_kcal", stat: "sum", unit: "kcal" },
  { id: "HKQuantityTypeIdentifierAppleExerciseTime", field: "exercise_minutes", stat: "sum", unit: "min" },
  { id: "HKQuantityTypeIdentifierFlightsClimbed", field: "flights_climbed", stat: "sum", unit: "count" },
  { id: "HKQuantityTypeIdentifierHeartRate", field: "hr", stat: "minmax", unit: "count/min" },
  { id: "HKQuantityTypeIdentifierRestingHeartRate", field: "resting_hr_bpm", stat: "avg", unit: "count/min" },
  { id: "HKQuantityTypeIdentifierHeartRateVariabilitySDNN", field: "hrv_sdnn_ms", stat: "avg", unit: "ms" },
  { id: "HKQuantityTypeIdentifierVO2Max", field: "vo2max_ml_kg_min", stat: "avg", unit: "ml/(kg*min)" },
  { id: "HKQuantityTypeIdentifierRespiratoryRate", field: "respiratory_rate_bpm", stat: "avg", unit: "count/min" },
  { id: "HKQuantityTypeIdentifierOxygenSaturation", field: "oxygen_saturation_pct", stat: "avg", unit: "%" },
  { id: "HKQuantityTypeIdentifierBodyMass", field: "body_mass_kg", stat: "avg", unit: "kg" },
];
const READ_TYPES: any[] = [...DAILY.map((d) => d.id), "HKCategoryTypeIdentifierSleepAnalysis", "HKWorkoutTypeIdentifier"];

export async function healthAvailable(): Promise<boolean> {
  if (Platform.OS !== "ios") return false;
  try { return isHealthDataAvailable(); } catch { return false; }
}

export async function isHealthConnected(): Promise<boolean> {
  try { return (await SecureStore.getItemAsync(FLAG)) === "1"; } catch { return false; }
}

async function setConnected(v: boolean) {
  try { if (v) await SecureStore.setItemAsync(FLAG, "1"); else await SecureStore.deleteItemAsync(FLAG); } catch {}
}

/** First-time connect: ask for read access, then sync the last 30 days. */
export async function connectHealth(api: Api): Promise<{ ok: boolean; message?: string }> {
  if (!(await healthAvailable())) return { ok: false, message: "Health data is not available on this device." };
  try {
    await requestAuthorization({ toRead: READ_TYPES });
  } catch (e) {
    return { ok: false, message: e instanceof Error ? e.message : String(e) };
  }
  await setConnected(true);
  const end = new Date();
  const start = new Date(end.getTime() - 30 * 86400000);
  const r = await syncRange(api, start, end, false);
  return { ok: true, message: `Synced ${r.metrics} days` };
}

export async function disconnectHealth() { await setConnected(false); }

/** Every app open: last 3 days plus any range the agent asked for. Cheap and silent. */
export async function syncHealthIfConnected(api: Api): Promise<void> {
  if (!(await isHealthConnected())) return;
  try {
    const end = new Date();
    await syncRange(api, new Date(end.getTime() - 3 * 86400000), end, true);
    const { requests } = await api.healthRequests();
    for (const req of requests.slice(0, 3)) {
      await syncRange(api, new Date(req.start_date + "T00:00:00"), new Date(req.end_date + "T23:59:59"), true, [req.id]);
    }
  } catch {}
}

function dayKey(d: Date): string {
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, "0"), dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}
function dayBounds(d: Date): { startDate: Date; endDate: Date } {
  const s = new Date(d); s.setHours(0, 0, 0, 0);
  const e = new Date(s); e.setDate(e.getDate() + 1);
  return { startDate: s, endDate: e };
}
const r1 = (n: number) => Math.round(n * 10) / 10;

async function dailyMetrics(day: Date): Promise<Record<string, number | string>> {
  const row: Record<string, number | string> = { date: dayKey(day) };
  const filter = { date: dayBounds(day) };
  await Promise.all(DAILY.map(async (m) => {
    try {
      const stats = m.stat === "sum" ? ["cumulativeSum"] : m.stat === "avg" ? ["discreteAverage"] : ["discreteAverage", "discreteMin", "discreteMax"];
      const res = await queryStatisticsForQuantity(m.id, stats as any, { filter, unit: m.unit });
      if (m.stat === "sum" && res.sumQuantity) row[m.field] = r1(res.sumQuantity.quantity);
      else if (m.stat === "avg" && res.averageQuantity) row[m.field] = r1(res.averageQuantity.quantity);
      else if (m.stat === "minmax") {
        if (res.averageQuantity) row["hr_average_bpm"] = r1(res.averageQuantity.quantity);
        if (res.minimumQuantity) row["hr_min_bpm"] = r1(res.minimumQuantity.quantity);
        if (res.maximumQuantity) row["hr_max_bpm"] = r1(res.maximumQuantity.quantity);
      }
    } catch {}
  }));
  return row;
}

function activityName(t: number): string {
  const name = (WorkoutActivityType as any)[t];
  return typeof name === "string" ? name.replace(/([A-Z])/g, "_$1").toLowerCase() : `type_${t}`;
}

function toMeters(q?: { unit: string; quantity: number }): number | undefined {
  if (!q) return undefined;
  const u = q.unit.toLowerCase();
  if (u === "m") return r1(q.quantity);
  if (u === "km") return r1(q.quantity * 1000);
  if (u === "mi") return r1(q.quantity * 1609.344);
  if (u === "yd") return r1(q.quantity * 0.9144);
  return r1(q.quantity);
}
function toMinutes(q?: { unit: string; quantity: number }): number | undefined {
  if (!q) return undefined;
  const u = q.unit.toLowerCase();
  if (u === "s") return r1(q.quantity / 60);
  if (u === "h" || u === "hr") return r1(q.quantity * 60);
  return r1(q.quantity);
}

async function workouts(startDate: Date, endDate: Date) {
  try {
    const rows = await queryWorkoutSamples({ filter: { date: { startDate, endDate } }, limit: 0 } as any);
    return rows.map((w: any) => {
      const s = new Date(w.startDate), e = new Date(w.endDate);
      return {
        id: `healthkit_workout_${w.uuid ?? s.toISOString()}`, category: "workout", start_datetime: s.toISOString(), end_datetime: e.toISOString(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, activity_type: activityName(w.workoutActivityType),
        duration_minutes: toMinutes(w.duration) ?? r1((e.getTime() - s.getTime()) / 60000),
        energy_kcal: w.totalEnergyBurned ? r1(w.totalEnergyBurned.quantity) : undefined,
        distance_meters: toMeters(w.totalDistance),
        source: w.sourceRevision?.source?.name ?? w.device?.name ?? undefined,
      };
    });
  } catch { return []; }
}

async function sleepSessions(startDate: Date, endDate: Date) {
  try {
    const samples = await queryCategorySamples("HKCategoryTypeIdentifierSleepAnalysis" as any, { filter: { date: { startDate, endDate } }, limit: 0, ascending: true } as any);
    const sorted = [...samples].map((x: any) => ({ s: new Date(x.startDate).getTime(), e: new Date(x.endDate).getTime(), v: Number(x.value) }))
      .sort((a, b) => a.s - b.s);
    const sessions: { s: number; e: number; mins: Record<number, number> }[] = [];
    for (const x of sorted) {
      const cur = sessions[sessions.length - 1];
      if (!cur || x.s - cur.e > 60 * 60000) sessions.push({ s: x.s, e: x.e, mins: {} });
      const ses = sessions[sessions.length - 1];
      ses.e = Math.max(ses.e, x.e);
      ses.mins[x.v] = (ses.mins[x.v] ?? 0) + (x.e - x.s) / 60000;
    }
    const V = CategoryValueSleepAnalysis;
    return sessions.map((ses) => {
      const core = ses.mins[V.asleepCore] ?? 0, deep = ses.mins[V.asleepDeep] ?? 0, rem = ses.mins[V.asleepREM] ?? 0;
      const unspecified = ses.mins[V.asleepUnspecified] ?? 0, awake = ses.mins[V.awake] ?? 0, inBed = ses.mins[V.inBed] ?? 0;
      const asleep = core + deep + rem + unspecified;
      const total = (ses.e - ses.s) / 60000;
      return {
        id: `healthkit_sleep_${new Date(ses.s).toISOString()}`, category: "sleep", start_datetime: new Date(ses.s).toISOString(),
        end_datetime: new Date(ses.e).toISOString(), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        duration_minutes: r1(total), in_bed_minutes: r1(inBed || total), asleep_minutes: r1(asleep), core_minutes: r1(core),
        deep_minutes: r1(deep), rem_minutes: r1(rem), awake_minutes: r1(awake),
        efficiency_pct: total > 0 ? r1((asleep / total) * 100) : undefined,
      };
    });
  } catch { return []; }
}

async function heartRateSamples(startDate: Date, endDate: Date) {
  try {
    const rows = await queryQuantitySamples("HKQuantityTypeIdentifierHeartRate" as any, { filter: { date: { startDate, endDate } }, limit: 3000, ascending: true, unit: "count/min" } as any);
    return rows.map((q: any) => ({ type: "heart_rate", datetime: new Date(q.startDate).toISOString(), value: r1(q.quantity), unit: "count/min" }));
  } catch { return []; }
}

export async function syncRange(api: Api, start: Date, end: Date, incremental: boolean, fulfills: string[] = []) {
  const days: Date[] = [];
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) days.push(new Date(d));
  const metrics = [];
  for (const d of days) metrics.push(await dailyMetrics(d));
  const sessions = [...(await sleepSessions(start, end)), ...(await workouts(start, end))];
  const sampleStart = new Date(Math.max(start.getTime(), end.getTime() - 2 * 86400000));
  const samples = await heartRateSamples(sampleStart, end);
  const payload = {
    provider: "healthkit",
    device: { model: Constants.deviceName ?? "iPhone", os: `${Platform.OS} ${Platform.Version}` },
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    metrics, sessions, samples,
    range: { start_date: dayKey(start), end_date: dayKey(end), incremental },
    fulfills,
  };
  const r = await api.healthSync(payload);
  return { metrics: r.counts.metrics, sessions: r.counts.sessions, samples: r.counts.samples };
}
