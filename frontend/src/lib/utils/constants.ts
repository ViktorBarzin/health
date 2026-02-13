/** Human-readable labels for metric types */
export const METRIC_LABELS: Record<string, string> = {
  StepCount: 'Steps',
  HeartRate: 'Heart Rate',
  RestingHeartRate: 'Resting Heart Rate',
  HeartRateVariabilitySDNN: 'HRV (SDNN)',
  OxygenSaturation: 'Blood Oxygen',
  BodyMass: 'Weight',
  BodyMassIndex: 'BMI',
  BodyFatPercentage: 'Body Fat',
  LeanBodyMass: 'Lean Body Mass',
  Height: 'Height',
  ActiveEnergyBurned: 'Active Energy',
  BasalEnergyBurned: 'Resting Energy',
  DistanceWalkingRunning: 'Walking + Running Distance',
  DistanceCycling: 'Cycling Distance',
  DistanceSwimming: 'Swimming Distance',
  FlightsClimbed: 'Flights Climbed',
  AppleExerciseTime: 'Exercise Minutes',
  AppleStandTime: 'Stand Time',
  AppleStandHour: 'Stand Hours',
  RespiratoryRate: 'Respiratory Rate',
  BloodPressureSystolic: 'Blood Pressure (Systolic)',
  BloodPressureDiastolic: 'Blood Pressure (Diastolic)',
  BloodGlucose: 'Blood Glucose',
  BodyTemperature: 'Body Temperature',
  DietaryWater: 'Water Intake',
  DietaryEnergyConsumed: 'Calories Consumed',
  DietaryProtein: 'Protein',
  DietaryCarbohydrates: 'Carbohydrates',
  DietaryFatTotal: 'Total Fat',
  DietaryCaffeine: 'Caffeine',
  SleepAnalysis: 'Sleep',
  MindfulSession: 'Mindful Minutes',
  VO2Max: 'VO2 Max',
  WalkingHeartRateAverage: 'Walking Heart Rate',
  EnvironmentalAudioExposure: 'Noise Exposure',
  HeadphoneAudioExposure: 'Headphone Audio',
  WalkingDoubleSupportPercentage: 'Double Support Time',
  WalkingSpeed: 'Walking Speed',
  WalkingStepLength: 'Step Length',
  WalkingAsymmetryPercentage: 'Walking Asymmetry',
  SixMinuteWalkTestDistance: '6-Min Walk Distance',
  StairAscentSpeed: 'Stair Ascent Speed',
  StairDescentSpeed: 'Stair Descent Speed',
};

/** Chart colors for each metric type */
export const METRIC_COLORS: Record<string, string> = {
  StepCount: '#10b981',
  HeartRate: '#ef4444',
  RestingHeartRate: '#f87171',
  HeartRateVariabilitySDNN: '#fb923c',
  OxygenSaturation: '#06b6d4',
  BodyMass: '#ec4899',
  BodyMassIndex: '#f472b6',
  BodyFatPercentage: '#a78bfa',
  ActiveEnergyBurned: '#f59e0b',
  BasalEnergyBurned: '#fbbf24',
  DistanceWalkingRunning: '#3b82f6',
  DistanceCycling: '#6366f1',
  FlightsClimbed: '#14b8a6',
  AppleExerciseTime: '#f97316',
  AppleStandTime: '#84cc16',
  RespiratoryRate: '#22d3ee',
  BloodPressureSystolic: '#e11d48',
  BloodPressureDiastolic: '#be123c',
  SleepAnalysis: '#8b5cf6',
  VO2Max: '#059669',
  WalkingHeartRateAverage: '#fb7185',
  EnvironmentalAudioExposure: '#fbbf24',
  MindfulSession: '#a78bfa',
};

/** Unicode/emoji icons for metric types */
export const METRIC_ICONS: Record<string, string> = {
  StepCount: '\u{1F6B6}',         // walking
  HeartRate: '\u{2764}',           // heart
  RestingHeartRate: '\u{1F49A}',   // green heart
  HeartRateVariabilitySDNN: '\u{1F4C8}', // chart
  OxygenSaturation: '\u{1FA78}',   // lungs
  BodyMass: '\u{2696}',            // scale
  BodyMassIndex: '\u{1F4CA}',      // bar chart
  BodyFatPercentage: '\u{1F4CA}',
  ActiveEnergyBurned: '\u{1F525}', // fire
  BasalEnergyBurned: '\u{26A1}',   // lightning
  DistanceWalkingRunning: '\u{1F3C3}', // runner
  DistanceCycling: '\u{1F6B4}',    // cyclist
  FlightsClimbed: '\u{1FA9C}',     // stairs
  AppleExerciseTime: '\u{23F1}',   // stopwatch
  AppleStandTime: '\u{1F9CD}',     // standing
  SleepAnalysis: '\u{1F319}',      // moon
  MindfulSession: '\u{1F9D8}',     // meditation
  VO2Max: '\u{1F4AA}',             // muscle
  RespiratoryRate: '\u{1F32C}',    // wind
  BloodPressureSystolic: '\u{1FA7A}', // stethoscope
  BloodPressureDiastolic: '\u{1FA7A}',
  EnvironmentalAudioExposure: '\u{1F50A}', // speaker
};

/** Default display units for metric types */
export const METRIC_UNITS: Record<string, string> = {
  StepCount: 'count',
  HeartRate: 'bpm',
  RestingHeartRate: 'bpm',
  HeartRateVariabilitySDNN: 'ms',
  OxygenSaturation: '%',
  BodyMass: 'kg',
  BodyMassIndex: '',
  BodyFatPercentage: '%',
  ActiveEnergyBurned: 'kcal',
  BasalEnergyBurned: 'kcal',
  DistanceWalkingRunning: 'm',
  DistanceCycling: 'm',
  FlightsClimbed: 'count',
  AppleExerciseTime: 'min',
  AppleStandTime: 'min',
  AppleStandHour: 'count',
  SleepAnalysis: 'hr',
  MindfulSession: 'min',
  VO2Max: 'mL/kg/min',
  RespiratoryRate: 'count/min',
  BloodPressureSystolic: 'mmHg',
  BloodPressureDiastolic: 'mmHg',
  EnvironmentalAudioExposure: 'dBASPL',
};

/** Sleep goal and quality thresholds */
export const SLEEP_GOAL_HOURS = 8;
export const SLEEP_QUALITY_THRESHOLDS = {
  excellent: 8,
  good: 7,
  fair: 6,
} as const;

/** BMI category definitions */
export const BMI_CATEGORIES = [
  { max: 18.5, label: 'Underweight', color: 'text-yellow-400' },
  { max: 25, label: 'Normal', color: 'text-green-400' },
  { max: 30, label: 'Overweight', color: 'text-yellow-400' },
  { max: Infinity, label: 'Obese', color: 'text-red-400' },
] as const;

/** Earliest possible date for Apple Health data (iOS 8 launch, Sept 2014) */
export const EARLIEST_HEALTH_DATA = new Date(2014, 8, 1);

/** Human-readable labels for workout activity types */
export const WORKOUT_LABELS: Record<string, string> = {
  Running: 'Running',
  Walking: 'Walking',
  Cycling: 'Cycling',
  Swimming: 'Swimming',
  Hiking: 'Hiking',
  Yoga: 'Yoga',
  FunctionalStrengthTraining: 'Strength Training',
  HighIntensityIntervalTraining: 'HIIT',
  TraditionalStrengthTraining: 'Weight Lifting',
  Elliptical: 'Elliptical',
  Rowing: 'Rowing',
  Dance: 'Dance',
  Pilates: 'Pilates',
  CoreTraining: 'Core Training',
  Flexibility: 'Flexibility',
  MixedCardio: 'Mixed Cardio',
  Tennis: 'Tennis',
  Soccer: 'Soccer',
  Basketball: 'Basketball',
};
