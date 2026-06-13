export interface User {
  id: number;
  email: string;
  created_at: string;
}

export interface MetricAvailable {
  metric_type: string;
  unit: string;
  count: number;
  latest_time: string;
}

export interface MetricDataPoint {
  time: string;
  value: number;
  min?: number;
  max?: number;
}

export interface MetricStats {
  avg: number;
  min: number;
  max: number;
  total: number | null;
  count: number;
  trend_pct?: number;
}

export interface MetricResponse {
  data: MetricDataPoint[];
  stats: MetricStats;
}

export interface WorkoutSummary {
  id: string;
  activity_type: string;
  time: string;
  end_time: string;
  duration_sec: number;
  total_distance_m: number;
  total_energy_kj: number;
}

export interface RoutePoint {
  time: string;
  latitude: number;
  longitude: number;
  altitude_m: number;
}

export interface WorkoutDetail extends WorkoutSummary {
  metadata: Record<string, string>;
  route_points: RoutePoint[];
}

export interface DashboardSummary {
  steps_today: number | null;
  active_energy_today: number | null;
  exercise_minutes_today: number | null;
  stand_hours_today: number | null;
  resting_hr: number | null;
  hrv: number | null;
  spo2: number | null;
  sleep_hours_last_night: number | null;
}

export interface ImportStatus {
  batch_id: string;
  status: string;
  record_count: number;
  filename: string;
  imported_at: string;
  error_message?: string | null;
}

export interface ExerciseSummary {
  id: string;
  name: string;
  category: string | null;
  equipment: string | null;
  level: string | null;
  mechanic: string | null;
  force: string | null;
  primary_muscles: string[];
  secondary_muscles: string[];
  images: string[];
  is_custom: boolean;
  demo_video_url: string;
}

export interface ExerciseDetail extends ExerciseSummary {
  instructions: string[];
}

export interface MuscleOption {
  value: string;
  label: string;
}

export interface ExerciseCreate {
  name: string;
  category?: string | null;
  equipment?: string | null;
  level?: string | null;
  mechanic?: string | null;
  force?: string | null;
  instructions: string[];
  primary_muscles: string[];
  secondary_muscles: string[];
}

export interface ActivityRingData {
  date: string;
  active_energy_burned_kj: number | null;
  active_energy_goal_kj: number | null;
  exercise_minutes: number | null;
  exercise_goal_minutes: number | null;
  stand_hours: number | null;
  stand_goal_hours: number | null;
}

// --- Session/Set logging (the live gym-logging core) ---

/** The four set types. Non-normal types are excluded from volume/PR stats. */
export type SetType = 'normal' | 'warmup' | 'drop' | 'failure';

/** One performed Set. Effort is the one-tap RIR chip (0–4, 4 = "4+"). */
export interface TrainingSet {
  id: string;
  exercise_id: string;
  order_index: number;
  weight_kg: number;
  reps: number;
  set_type: SetType;
  effort_rir: number | null;
  exercise_name: string | null;
}

/** A Session in list form: timing plus derived counts and counted volume. */
export interface SessionSummary {
  id: string;
  started_at: string;
  ended_at: string | null;
  is_active: boolean;
  set_count: number;
  total_volume_kg: number;
}

/** A Session with its Sets in order. */
export interface SessionDetail extends SessionSummary {
  sets: TrainingSet[];
}

/** Payload to log a Set. */
export interface SetCreate {
  exercise_id: string;
  weight_kg: number;
  reps: number;
  effort_rir?: number | null;
  set_type?: SetType;
}

/** Payload to edit a Set (only sent fields change). */
export interface SetUpdate {
  weight_kg?: number;
  reps?: number;
  effort_rir?: number | null;
  set_type?: SetType;
}
