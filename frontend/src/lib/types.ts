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
  count: number;
  trend_pct?: number;
}

export interface MetricResponse {
  data: MetricDataPoint[];
  stats: MetricStats;
}

export interface WorkoutSummary {
  id: number;
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
  steps_today: number;
  active_energy_today: number;
  exercise_minutes_today: number;
  stand_hours_today: number;
  resting_hr: number;
  hrv: number;
  spo2: number;
  sleep_hours_last_night: number;
}

export interface ImportStatus {
  batch_id: string;
  status: string;
  record_count: number;
  filename: string;
  imported_at: string;
}

export interface ActivityRingData {
  date: string;
  active_energy: number;
  active_energy_goal: number;
  exercise_minutes: number;
  exercise_goal: number;
  stand_hours: number;
  stand_goal: number;
}
