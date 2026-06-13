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
  /** Superset group id (Sets sharing it are logged in alternation), or null. */
  superset_group: number | null;
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
  superset_group?: number | null;
}

/** Payload to edit a Set (only sent fields change). */
export interface SetUpdate {
  weight_kg?: number;
  reps?: number;
  effort_rir?: number | null;
  set_type?: SetType;
  superset_group?: number | null;
}

/** A personal record a written Set achieved (see lib/pr.ts `PRKind`). */
export interface PRReadout {
  kind: 'weight' | 'e1rm' | 'reps_at_weight' | 'volume';
  value: number;
  at_weight_kg: number | null;
}

/** The add/edit-Set response: the Set plus any PRs it set (server-authoritative). */
export interface SetWriteResult extends TrainingSet {
  prs: PRReadout[];
}

/** A persisted personal record row, from GET /api/sessions/prs. */
export interface PersonalRecord {
  exercise_id: string;
  kind: 'weight' | 'e1rm' | 'reps_at_weight' | 'volume';
  value: number;
  at_weight_kg: number | null;
  achieved_at: string;
}

// --- Training analytics (Recovery, per-muscle volume, e1RM trend) ---

/** Whether a muscle is a primary or secondary mover for an Exercise. */
export type MuscleRole = 'primary' | 'secondary';

/** One muscle group's current Recovery (freshness) score, 0–100. */
export interface MuscleRecovery {
  muscle: string;
  recovery: number;
}

/** Per-muscle Recovery snapshot + the model parameters used (GET /api/analytics/recovery). */
export interface RecoveryResponse {
  as_of: string;
  half_life_hours: number;
  muscles: MuscleRecovery[];
}

/** One muscle group's set count + volume-load over the trailing window, by role. */
export interface MuscleVolume {
  muscle: string;
  role: MuscleRole;
  set_count: number;
  volume_load: number;
}

/** Per-muscle weekly volume over a trailing window (GET /api/analytics/volume). */
export interface VolumeResponse {
  weeks: number;
  muscles: MuscleVolume[];
}

/** One estimated-1RM datapoint: the Set's time and its e1RM (kg). */
export interface E1rmPoint {
  time: string;
  e1rm: number;
}

/** The estimated-1RM trend for one Exercise (GET /api/analytics/e1rm-trend). */
export interface E1rmTrendResponse {
  exercise_id: string;
  points: E1rmPoint[];
  best_e1rm: number | null;
}

// --- In-gym toolkit (Gym Profile, rest timer) ---

/** A user's available equipment (GET/PUT /api/gym-profile). */
export interface GymProfile {
  /** Bar weights owned, kg (sorted ascending). */
  bar_weights_kg: number[];
  /** Plate denominations owned, kg (each available in pairs, sorted ascending). */
  plate_weights_kg: number[];
  /** Equipment kinds available, aligned with the Exercise library's values. */
  equipment: string[];
}

/** A user's rest-timer preference for one Exercise (GET/PUT /api/exercises/{id}/rest). */
export interface RestPref {
  exercise_id: string;
  /** The user's explicit override in seconds, or null if unset. */
  default_rest_seconds: number | null;
  /** What the timer should use: the override, or the app's global default. */
  effective_rest_seconds: number;
}

// --- Freestyle Recommendation ("generate me a workout", #11) ---

/** One prescribed Exercise in a proposal: target sets × reps × weight. */
export interface RecommendedExercise {
  exercise_id: string;
  name: string;
  target_sets: number;
  target_reps: number;
  target_weight_kg: number;
  /** True when the weight is a first guess (the Exercise had no usable history). */
  is_starting_point: boolean;
  primary_muscles: string[];
  secondary_muscles: string[];
}

/** Today's freestyle workout proposal (GET /api/recommendations/freestyle). */
export interface RecommendationResponse {
  exercises: RecommendedExercise[];
}

/**
 * The autoregulation applied to today's Program day (#14, ADR-0004): why the day
 * looks the way it does (trimmed/raised on Readiness + Recovery, within Principle
 * bounds), plus the early-deload flag.
 */
export interface Autoregulation {
  adjusted: boolean;
  reason: string;
  readiness: number | null;
  early_deload: boolean;
  trimmed_muscles: string[];
}

/** The active-Program context on a Program-drawn Recommendation. */
export interface ProgramContext {
  program_id: string;
  program_name: string;
  day_name: string;
  day_index: number;
  week: number;
  total_weeks: number;
  is_deload: boolean;
  autoregulation: Autoregulation | null;
}

/**
 * Today's Recommendation (GET /api/recommendations/today) — drawn from the
 * active Program when one is running (`source: "program"`, `program` set), else
 * freestyle (`source: "freestyle"`, `program: null`).
 */
export interface TodayRecommendationResponse extends RecommendationResponse {
  source: 'program' | 'freestyle';
  program: ProgramContext | null;
}

/**
 * The re-shaped proposal a conversational adjust returns (POST
 * /api/recommendations/adjust) — the today shape plus a human `note` and the
 * validated levers `applied`.
 */
export interface AdjustResponse extends TodayRecommendationResponse {
  note: string;
  applied: {
    volume_scale: number | null;
    exclude_equipment: string[];
    max_exercises: number | null;
  };
}

// --- Readiness (the daily biometric signal, #14, ADR-0004) ---

/** One metric's contribution to the Readiness score (recent vs the baseline). */
export interface ReadinessComponent {
  metric: string;
  recent: number;
  baseline: number;
  score: number;
  weight: number;
  direction: 'above' | 'below' | 'at';
}

/**
 * Today's Readiness (GET /api/readiness): a 0–100 biometric signal from HRV,
 * resting HR and sleep vs the user's baseline. `insufficient_data` is true (and
 * `score`/`band` null) when there's no usable history.
 */
export interface ReadinessResponse {
  score: number | null;
  band: 'low' | 'moderate' | 'high' | null;
  insufficient_data: boolean;
  components: ReadinessComponent[];
}

// --- Principles knowledge base (the receipts UI source, #12/#14) ---

export type EvidenceGrade = 'A' | 'B' | 'C';

/** A peer-reviewed source backing a Principle, with a resolvable link. */
export interface Citation {
  authors: string;
  year: number;
  title: string;
  journal: string;
  doi: string | null;
  pmid: string | null;
  url: string | null;
  resolved_url: string | null;
}

/** One typed parameter range inside a Principle's params. */
export interface ParamRange {
  min: number | null;
  max: number | null;
  value: number | null;
  unit: string | null;
}

/** A cited exercise-science rule (GET /api/principles/{key}). */
export interface Principle {
  id: string;
  key: string;
  statement: string;
  category: string;
  params: Record<string, ParamRange>;
  goals: TrainingGoal[];
  experience_levels: ExperienceLevel[];
  evidence_grade: EvidenceGrade;
  notes: string | null;
  version: number;
  updated_at: string;
  citations: Citation[];
}

// --- Goal-driven Programs (#13, ADR-0004) ---

export type TrainingGoal = 'bulk' | 'cut' | 'maintain' | 'strength';
export type ExperienceLevel = 'beginner' | 'intermediate' | 'advanced';
export type ProgramStatus = 'active' | 'archived';

/** One generated parameter's receipt: which Principle it came from + the value. */
export interface ParamProvenance {
  principle_key: string;
  value: number;
  unit: string | null;
  min: number | null;
  max: number | null;
}

/** One training day in a Program's split: its name and ordered muscle slots. */
export interface ProgramDay {
  day_index: number;
  name: string;
  /** Ordered slots, e.g. [{ muscle: "chest" }, { muscle: "triceps" }]. */
  slots: Array<{ muscle: string }>;
}

/** A per-muscle weekly volume target for one week (ramps, then deloads). */
export interface ProgramMuscleVolume {
  muscle: string;
  week: number;
  target_sets: number;
  is_deload: boolean;
}

/** A Program in the user's list (header without the day/volume detail). */
export interface ProgramSummary {
  id: string;
  name: string;
  preset_key: string | null;
  goal: TrainingGoal;
  experience: ExperienceLevel;
  days_per_week: number;
  session_minutes: number;
  mesocycle_weeks: number;
  total_weeks: number;
  deload_week: number;
  rep_range_low: number;
  rep_range_high: number;
  effort_rir: number;
  status: ProgramStatus;
  created_at: string;
}

/** A Program with its split days, ramping volume, and provenance receipt. */
export interface ProgramDetail extends ProgramSummary {
  days: ProgramDay[];
  muscle_volumes: ProgramMuscleVolume[];
  provenance: Record<string, ParamProvenance>;
}

/** One catalog preset, for the browse list (GET /api/programs/presets). */
export interface ProgramPreset {
  key: string;
  name: string;
  summary: string;
  goal: TrainingGoal;
  experience: ExperienceLevel;
  days_per_week: number;
  session_minutes: number;
}

/** The option sets the guided quiz renders (GET /api/programs/quiz-options). */
export interface QuizOptions {
  goals: Array<{ value: TrainingGoal; label: string }>;
  experience_levels: Array<{ value: ExperienceLevel; label: string }>;
  days_per_week: number[];
  session_minutes: number[];
}

/** The quiz answers (or a preset selection) that generate a Program. */
export interface GenerateProgramRequest {
  preset_key?: string;
  goal?: TrainingGoal;
  experience?: ExperienceLevel;
  days_per_week?: number;
  session_minutes?: number;
}

// --- Nutrition: Food catalog + Diary (the MyFitnessPal core, #21) ---

/** The four daily Meal slots a Diary Entry lands in (CONTEXT.md "Meal"). */
export type Meal = 'breakfast' | 'lunch' | 'dinner' | 'snack';

/** A bundle of macros (calories + the three macronutrients, grams). */
export interface MacroTotals {
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
}

/** One catalog Food with per-serving macros (GET /api/nutrition/foods). */
export interface Food {
  id: string;
  name: string;
  brand: string | null;
  /** One serving = `serving_size` of `serving_unit` (e.g. 100 "g", 1 "egg"). */
  serving_size: number;
  serving_unit: string;
  // Macros for ONE serving.
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  is_custom: boolean;
  source: string;
}

/** Payload to log a Food to a Meal of a day. `quantity` is number of servings. */
export interface DiaryEntryCreate {
  food_id: string;
  entry_date: string; // YYYY-MM-DD
  meal: Meal;
  quantity?: number;
}

/** Payload to edit a Diary Entry (only sent fields change). */
export interface DiaryEntryUpdate {
  food_id?: string;
  entry_date?: string;
  meal?: Meal;
  quantity?: number;
}

/** One Diary Entry, with its computed (per-serving × quantity) macros. */
export interface DiaryEntry {
  id: string;
  food_id: string;
  food_name: string;
  brand: string | null;
  entry_date: string;
  meal: Meal;
  quantity: number;
  serving_size: number;
  serving_unit: string;
  // The entry's macros = the Food's per-serving macros × quantity.
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
}

/** One Meal's entries plus its subtotal, for the day view. */
export interface MealSection {
  meal: Meal;
  entries: DiaryEntry[];
  totals: MacroTotals;
}

/** A whole day's diary: the four Meal sections and the day total. */
export interface DiaryDay {
  entry_date: string;
  meals: MealSection[];
  total: MacroTotals;
}

// --- Nutrition #22: barcode / Open Food Facts, custom Foods, Recipes ---

/** Payload to create a custom (private) Food (per-serving macros). */
export interface FoodCreate {
  name: string;
  brand?: string | null;
  serving_size: number;
  serving_unit: string;
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
}

/** Payload to edit one of the caller's own custom Foods (only sent fields). */
export interface FoodUpdate {
  name?: string;
  brand?: string | null;
  serving_size?: number;
  serving_unit?: string;
  calories?: number;
  protein_g?: number;
  carbs_g?: number;
  fat_g?: number;
}

/** One ingredient in a Recipe payload: a Food id + quantity (servings). */
export interface RecipeIngredientInput {
  food_id: string;
  quantity: number;
}

/** Payload to create or replace a Recipe (macros are computed server-side). */
export interface RecipeCreate {
  name: string;
  yield_servings: number;
  ingredients: RecipeIngredientInput[];
}

/** One ingredient of a Recipe, with its contribution at the used quantity. */
export interface RecipeIngredient {
  food_id: string;
  food_name: string;
  quantity: number;
  serving_size: number;
  serving_unit: string;
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
}

/**
 * A Recipe: a user-defined Food composed of other Foods, with computed
 * per-serving macros. `food_id` is the id to log to the diary — a Recipe is
 * loggable exactly like a Food.
 */
export interface Recipe {
  id: string;
  food_id: string;
  name: string;
  yield_servings: number;
  // The computed per-serving macros.
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  ingredients: RecipeIngredient[];
}

// --- Fitbod CSV import (#9) ---

/** A Fitbod exercise name that auto-matched to a library Exercise. */
export interface FitbodMatchedName {
  fitbod_name: string;
  exercise_id: string;
  exercise_name: string;
}

/** A Fitbod exercise name the user must resolve (pick or create an Exercise). */
export interface FitbodUnresolvedName {
  fitbod_name: string;
  set_count: number;
}

/** Dry-run summary of a Fitbod CSV before committing the import. */
export interface FitbodPreview {
  session_count: number;
  set_count: number;
  skipped_rows: number;
  matched: FitbodMatchedName[];
  unresolved: FitbodUnresolvedName[];
}

/** The outcome of a committed Fitbod import. */
export interface FitbodImportResult {
  batch_id: string;
  sessions_created: number;
  sets_created: number;
  unresolved_skipped: number;
  skipped_rows: number;
}

// --- Budget #23: the Goal-driven, self-calibrating daily calorie/macro target ---

/** The user's de-noised weight trend (the Budget calibrates on this). */
export interface WeightTrend {
  insufficient_data: boolean;
  true_weight_kg: number | null;
  rate_kg_per_week: number | null;
  rate_pct_per_week: number | null;
  n_samples: number;
}

/** Today's Budget: the Goal-driven calorie/macro target + the trend it rides.
 *
 * `method` is 'adaptive' (TDEE measured from energy balance) or 'estimated' (a
 * labelled bodyweight-formula fallback); `insufficient_data` (numbers null) when
 * there isn't even a bodyweight to estimate from. `goal` is the active Program's
 * goal (or 'maintain' by default) — the single Goal driving Program and Budget.
 */
export interface Budget {
  insufficient_data: boolean;
  method: 'adaptive' | 'estimated' | null;
  goal: 'bulk' | 'cut' | 'maintain' | 'strength';
  tdee_kcal: number | null;
  target_kcal: number | null;
  protein_g: number | null;
  carbs_g: number | null;
  fat_g: number | null;
  target_rate_kg_per_week: number | null;
  intake_days: number;
  trend: WeightTrend;
}
