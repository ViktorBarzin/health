import { type Page, type Locator } from '@playwright/test';

export class DashboardPage {
  readonly page: Page;
  readonly error: Locator;
  readonly activityRings: Locator;

  // MetricCard locators (via dynamic data-testid on MetricCard component)
  readonly metricCardSteps: Locator;
  readonly metricCardActiveEnergy: Locator;
  readonly metricCardHeartRate: Locator;
  readonly metricCardExercise: Locator;
  readonly metricValueSteps: Locator;
  readonly metricValueActiveEnergy: Locator;
  readonly metricValueHeartRate: Locator;
  readonly metricValueExercise: Locator;

  // Sleep summary
  readonly sleepSummary: Locator;
  readonly sleepSummaryHours: Locator;
  readonly sleepSummaryQuality: Locator;

  // Recent workouts
  readonly recentWorkouts: Locator;
  readonly recentWorkoutsViewAll: Locator;

  // Layout components
  readonly sidebarNavDashboard: Locator;
  readonly sidebarNavMetrics: Locator;
  readonly sidebarNavWorkouts: Locator;
  readonly sidebarNavSleep: Locator;
  readonly sidebarNavBody: Locator;
  readonly sidebarNavTrends: Locator;
  readonly sidebarNavSettings: Locator;
  readonly headerMenuToggle: Locator;
  readonly headerUserMenuBtn: Locator;
  readonly headerLogoutBtn: Locator;

  // Date range picker
  readonly daterangeStartInput: Locator;
  readonly daterangeEndInput: Locator;

  constructor(page: Page) {
    this.page = page;
    this.error = page.locator('[data-testid="dashboard-error"]');
    this.activityRings = page.locator('[data-testid="dashboard-activity-rings"]');

    // MetricCard components
    this.metricCardSteps = page.locator('[data-testid="metric-card-Steps"]');
    this.metricCardActiveEnergy = page.locator('[data-testid="metric-card-Active Energy"]');
    this.metricCardHeartRate = page.locator('[data-testid="metric-card-Heart Rate"]');
    this.metricCardExercise = page.locator('[data-testid="metric-card-Exercise"]');
    this.metricValueSteps = page.locator('[data-testid="metric-value-Steps"]');
    this.metricValueActiveEnergy = page.locator('[data-testid="metric-value-Active Energy"]');
    this.metricValueHeartRate = page.locator('[data-testid="metric-value-Heart Rate"]');
    this.metricValueExercise = page.locator('[data-testid="metric-value-Exercise"]');

    // Sleep summary
    this.sleepSummary = page.locator('[data-testid="sleep-summary"]');
    this.sleepSummaryHours = page.locator('[data-testid="sleep-summary-hours"]');
    this.sleepSummaryQuality = page.locator('[data-testid="sleep-summary-quality"]');

    // Recent workouts
    this.recentWorkouts = page.locator('[data-testid="recent-workouts"]');
    this.recentWorkoutsViewAll = page.locator('[data-testid="recent-workouts-view-all"]');

    // Layout components
    this.sidebarNavDashboard = page.locator('[data-testid="sidebar-nav-dashboard"]');
    this.sidebarNavMetrics = page.locator('[data-testid="sidebar-nav-metrics"]');
    this.sidebarNavWorkouts = page.locator('[data-testid="sidebar-nav-workouts"]');
    this.sidebarNavSleep = page.locator('[data-testid="sidebar-nav-sleep"]');
    this.sidebarNavBody = page.locator('[data-testid="sidebar-nav-body"]');
    this.sidebarNavTrends = page.locator('[data-testid="sidebar-nav-trends"]');
    this.sidebarNavSettings = page.locator('[data-testid="sidebar-nav-settings"]');
    this.headerMenuToggle = page.locator('[data-testid="header-menu-toggle"]');
    this.headerUserMenuBtn = page.locator('[data-testid="header-user-menu-btn"]');
    this.headerLogoutBtn = page.locator('[data-testid="header-logout-btn"]');

    // Date range picker
    this.daterangeStartInput = page.locator('[data-testid="daterange-start-input"]');
    this.daterangeEndInput = page.locator('[data-testid="daterange-end-input"]');
  }

  async goto() {
    await this.page.goto('/');
  }

  sidebarNav(key: string): Locator {
    return this.page.locator(`[data-testid="sidebar-nav-${key}"]`);
  }

  daterangePreset(value: string): Locator {
    return this.page.locator(`[data-testid="daterange-preset-${value}"]`);
  }

  recentWorkout(index: number): Locator {
    return this.page.locator(`[data-testid="recent-workout-${index}"]`);
  }
}
