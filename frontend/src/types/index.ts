// Mirrors backend/app/schemas/*.py and backend/app/models/enums.py.

export type UserRole =
  | "administrator"
  | "executive"
  | "business_development"
  | "project_manager"
  | "proposal_manager"
  | "viewer";

export type SetAsideType =
  | "unrestricted"
  | "sdvosb"
  | "small_business"
  | "eight_a"
  | "hubzone"
  | "wosb"
  | "edwosb"
  | "other";

export type ContractType =
  | "ae_brooks_act"
  | "idiq"
  | "matoc"
  | "satoc"
  | "task_order"
  | "design_build"
  | "construction"
  | "other";

export type MaturityStage =
  | "rumored_conceptual"
  | "funding_identified"
  | "planning"
  | "procurement_forecast"
  | "sources_sought_rfi"
  | "solicitation_expected"
  | "solicitation_released"
  | "proposal_submitted"
  | "interview_negotiation"
  | "award_pending"
  | "awarded";

export type OpportunityStatus = "active" | "archived";
export type CompanyType = "own_firm" | "teaming_partner" | "competitor" | "prime" | "subconsultant" | "other";
export type OpportunityCompanyRelationship =
  | "incumbent"
  | "teaming_partner"
  | "confirmed_competitor"
  | "historical_competitor"
  | "likely_competitor"
  | "possible_competitor"
  | "subconsultant"
  | "prime";
export type ContactRole =
  | "contracting_officer"
  | "program_manager"
  | "small_business_specialist"
  | "technical_contact"
  | "agency_engineer"
  | "teaming_partner_contact"
  | "municipal_official"
  | "other";
export type TaskStatus = "open" | "in_progress" | "completed" | "cancelled";
export type TaskPriority = "low" | "medium" | "high" | "urgent";
export type GoNoGoOutcome = "go" | "conditional_go" | "no_go";
export type DocumentCategory =
  | "solicitation"
  | "amendment"
  | "scope"
  | "plans"
  | "agency_document"
  | "proposal_draft"
  | "sf330"
  | "teaming_agreement"
  | "resume"
  | "project_sheet"
  | "debrief"
  | "award_document"
  | "other";
export type IntelligenceCategory = "live_opportunity" | "pre_solicitation" | "early_signal" | "award_intelligence";
export type JurisdictionLevel = "federal" | "state" | "local" | "regional" | "private";
export type ConnectorType = "api" | "rss" | "structured_file" | "csv" | "html_scrape" | "pdf_parse" | "manual";
export type SourceHealthStatus = "never_run" | "healthy" | "degraded" | "failing" | "needs_configuration" | "manual_only";
export type SyncRunStatus = "running" | "success" | "partial_failure" | "failure";
export type SyncTriggeredBy = "manual" | "scheduled";

export type AlertCategory =
  | "new_matching_opportunity"
  | "new_sources_sought"
  | "deadline_approaching"
  | "opportunity_amended"
  | "gonogo_needed"
  | "task_due"
  | "recompete_approaching"
  | "other";
export type ActivityType =
  | "created"
  | "stage_changed"
  | "score_recalculated"
  | "field_updated"
  | "document_uploaded"
  | "ai_analysis_completed"
  | "gonogo_started"
  | "gonogo_decided"
  | "task_created"
  | "task_completed"
  | "note"
  | "ingested"
  | "amended";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  title: string | null;
  is_active: boolean;
}

export interface AgencyOffice {
  id: string;
  agency_id: string;
  name: string;
  city: string | null;
  state: string | null;
  notes: string | null;
}

export interface Agency {
  id: string;
  name: string;
  short_name: string | null;
  agency_type: string | null;
  priority_tier: number;
  notes: string | null;
  is_sample_data: boolean;
  offices: AgencyOffice[];
}

export interface Company {
  id: string;
  name: string;
  company_type: CompanyType;
  website: string | null;
  headquarters_city: string | null;
  headquarters_state: string | null;
  other_locations: string | null;
  naics_codes: string | null;
  technical_specialties: string | null;
  is_sdvosb: boolean;
  is_vosb: boolean;
  is_hubzone: boolean;
  is_eight_a: boolean;
  is_wosb: boolean;
  is_edwosb: boolean;
  is_dbe: boolean;
  is_small_business: boolean;
  federal_experience_summary: string | null;
  agencies_served: string | null;
  contract_vehicles: string | null;
  relationship_strength: number | null;
  notes: string | null;
  is_sample_data: boolean;
}

export interface OpportunityCompanyLink {
  id: string;
  company: Company;
  relationship_type: OpportunityCompanyRelationship;
  rationale: string | null;
  confidence: string;
}

export interface Contact {
  id: string;
  full_name: string;
  organization: string | null;
  title: string | null;
  email: string | null;
  phone: string | null;
  agency_id: string | null;
  agency_office_id: string | null;
  company_id: string | null;
  role: ContactRole;
  relationship_strength: number | null;
  last_contact_date: string | null;
  next_follow_up_date: string | null;
  notes: string | null;
}

export interface OpportunityContactLink {
  id: string;
  contact: Contact;
  role_on_opportunity: ContactRole;
}

export interface OpportunityListItem {
  id: string;
  title: string;
  solicitation_number: string | null;
  location_state: string | null;
  set_aside: SetAsideType;
  contract_type: ContractType;
  estimated_value_high: number | null;
  estimated_fee: number | null;
  proposal_due_at: string | null;
  pipeline_stage_id: string | null;
  maturity_stage: MaturityStage;
  status: OpportunityStatus;
  is_sdvosb_setaside: boolean;
  is_sample_data: boolean;
  agency: Agency | null;
  current_score: number | null;
  current_score_band: string | null;
}

export interface Opportunity extends OpportunityListItem {
  agency_id: string | null;
  agency_office_id: string | null;
  location_city: string | null;
  naics_code: string | null;
  psc_code: string | null;
  estimated_value_low: number | null;
  estimated_fee: number | null;
  contract_duration_months: number | null;
  questions_due_at: string | null;
  site_visit_at: string | null;
  industry_day_at: string | null;
  sources_sought_due_at: string | null;
  incumbent_company_id: string | null;
  incumbent_notes: string | null;
  description: string | null;
  scope_summary: string | null;
  evaluation_factors: string | null;
  past_performance_requirements: string | null;
  internal_notes: string | null;
  opportunity_source_label: string;
  assigned_user_id: string | null;
  source: string;
  source_url: string | null;
  retrieved_at: string;
  confidence: string;
  created_at: string;
  updated_at: string;
}

export interface OpportunityScore {
  id: string;
  opportunity_id: string;
  score: number;
  band: "high" | "medium" | "low";
  category_scores: Record<string, number>;
  category_rationale: Record<string, string[]>;
  why_it_scores_highly: string;
  primary_concern: string;
  computed_at: string;
}

export interface PipelineStage {
  id: string;
  name: string;
  sort_order: number;
  is_closed_won: boolean;
  is_closed_lost: boolean;
  is_active: boolean;
}

export interface GoNoGoCriteriaScore {
  id: string;
  criterion: string;
  score: number;
  notes: string | null;
}

export interface GoNoGoReview {
  id: string;
  opportunity_id: string;
  ai_recommendation: string | null;
  ai_recommendation_rationale: string | null;
  decision: GoNoGoOutcome | null;
  decided_by_id: string | null;
  decided_at: string | null;
  decision_notes: string | null;
  criteria_scores: GoNoGoCriteriaScore[];
}

export interface Task {
  id: string;
  opportunity_id: string | null;
  opportunity_title: string | null;
  title: string;
  notes: string | null;
  owner_id: string | null;
  due_date: string | null;
  priority: TaskPriority;
  status: TaskStatus;
  created_by_id: string | null;
}

export interface Activity {
  id: string;
  opportunity_id: string;
  activity_type: ActivityType;
  description: string;
  detail: string | null;
  extra_data: Record<string, unknown> | null;
  actor_id: string | null;
  created_at: string;
}

export interface OpportunityDocument {
  id: string;
  opportunity_id: string;
  category: DocumentCategory;
  original_filename: string;
  content_type: string | null;
  size_bytes: number | null;
  version: number;
  uploaded_by_id: string | null;
  notes: string | null;
  created_at: string;
}

export interface AiSolicitationAnalysis {
  id: string;
  document_id: string;
  opportunity_id: string;
  model_used: string;
  analyzed_at: string;
  executive_summary: string | null;
  scope: string | null;
  deliverables: string[] | null;
  required_disciplines: string[] | null;
  relevant_naics: string[] | null;
  contract_type: string | null;
  evaluation_factors: string[] | null;
  page_limits: string | null;
  required_forms: string[] | null;
  key_personnel_requirements: string | null;
  past_performance_requirements: string | null;
  submission_instructions: string | null;
  deadline: string | null;
  questions_deadline: string | null;
  site_visit: string | null;
  interview_requirements: string | null;
  small_business_requirements: string | null;
  subcontracting_requirements: string | null;
  licensing_requirements: string | null;
  geographic_restrictions: string | null;
  top_10_things_to_know: string[] | null;
  red_flags: string[] | null;
}

export interface RevenueForecast {
  id: string;
  opportunity_id: string;
  total_contract_value: number | null;
  principal_share_pct: number | null;
  estimated_fee: number | null;
  win_probability_pct: number | null;
  expected_award_date: string | null;
  expected_revenue_start: string | null;
  expected_revenue_end: string | null;
  market_sector: string | null;
  weighted_value: number | null;
}

export interface ForecastBucket {
  label: string;
  total_pipeline: number;
  weighted_pipeline: number;
  committed_revenue: number;
  opportunity_count: number;
}

export interface ForecastSummary {
  total_pipeline: number;
  weighted_pipeline: number;
  committed_revenue: number;
  target_revenue: number;
  revenue_gap: number;
  by_month: ForecastBucket[];
  by_quarter: ForecastBucket[];
  by_year: ForecastBucket[];
  by_agency: ForecastBucket[];
  by_market_sector: ForecastBucket[];
}

export interface Alert {
  id: string;
  category: AlertCategory;
  title: string;
  body: string | null;
  opportunity_id: string | null;
  is_read: boolean;
  created_at: string;
}

export interface ChartBucket {
  label: string;
  value: number;
  count: number | null;
}

export interface KpiCards {
  total_active_opportunities: number;
  total_estimated_contract_value: number;
  total_estimated_fee: number;
  discovered_this_week: number;
  due_within_30_days: number;
  awaiting_go_no_go: number;
  active_proposals: number;
  interviews_pending: number;
  awards_pending: number;
  wins: number;
  losses: number;
  win_rate_pct: number | null;
  sdvosb_setaside_count: number;
  sole_source_or_limited_competition_count: number;
  recompete_count: number;
  early_stage_count: number;
}

export interface IntelligenceKpis {
  live_opportunity_count: number;
  pre_solicitation_count: number;
  early_signal_count: number;
  award_intelligence_count: number;
  new_this_week: number;
  sources_checked_today: number;
  sources_with_errors: number;
  new_intelligence_since_last_view: number;
  last_viewed_at: string | null;
}

export interface DashboardSummary {
  kpis: KpiCards;
  intelligence: IntelligenceKpis;
  pipeline_by_stage: ChartBucket[];
  pipeline_by_agency: ChartBucket[];
  pipeline_by_state: ChartBucket[];
  pipeline_by_source: ChartBucket[];
  pipeline_by_contract_type: ChartBucket[];
  pipeline_by_naics: ChartBucket[];
  pipeline_by_score_band: ChartBucket[];
  pipeline_value_over_time: ChartBucket[];
  upcoming_deadlines: OpportunityListItem[];
  highest_priority_opportunities: OpportunityListItem[];
  high_priority_signals: IntelligenceItem[];
  attention_today_tasks: Task[];
}

export interface NaicsCode {
  id: string;
  code: string;
  title: string;
  is_core_market: boolean;
}

export interface Discipline {
  id: string;
  name: string;
  category: string | null;
}

export interface WinLossReview {
  id: string;
  opportunity_id: string;
  outcome: string;
  winner_company_id: string | null;
  winning_team_notes: string | null;
  award_amount: number | null;
  decision_date: string | null;
  why_won_lost: string | null;
  debrief_notes: string | null;
  evaluation_scores_notes: string | null;
  relationship_strength_notes: string | null;
  technical_weaknesses: string | null;
  proposal_weaknesses: string | null;
  pricing_issues: string | null;
  past_performance_gaps: string | null;
  recorded_by_id: string | null;
}

export interface ApiError {
  detail: string;
}

export interface IntelligenceSource {
  id: string;
  name: string;
  organization: string | null;
  jurisdiction_level: JurisdictionLevel;
  geographic_coverage: string | null;
  source_url: string | null;
  api_url: string | null;
  connector_type: ConnectorType;
  connector_key: string | null;
  requires_auth: boolean;
  auth_notes: string | null;
  is_enabled: boolean;
  polling_frequency_hours: number | null;
  last_attempted_sync_at: string | null;
  last_successful_sync_at: string | null;
  last_result_count: number | null;
  last_error: string | null;
  health_status: SourceHealthStatus;
  terms_notes: string | null;
  default_intelligence_category: IntelligenceCategory | null;
  notes: string | null;
}

export interface IntelligenceSyncRun {
  id: string;
  intelligence_source_id: string;
  started_at: string;
  finished_at: string | null;
  status: SyncRunStatus;
  items_fetched: number;
  items_created: number;
  items_updated: number;
  items_unchanged: number;
  items_errored: number;
  error_detail: string | null;
  // Connector-reported query diagnostics (date window, filters used, totalRecords,
  // pages fetched, records kept after relevance filtering, live diagnostic probes) —
  // only some connectors report this (currently SAM.gov); null otherwise. Shape is
  // connector-specific, so this stays loosely typed rather than modeling every
  // connector's fields.
  diagnostics: Record<string, unknown> | null;
  triggered_by: SyncTriggeredBy;
}

export interface SyncAllResult {
  sources_attempted: number;
  sources_succeeded: number;
  sources_skipped: string[];
}

export interface IntelligenceItem {
  id: string;
  intelligence_source_id: string;
  external_id: string;
  title: string;
  description: string | null;
  agency_name: string | null;
  agency_id: string | null;
  jurisdiction_level: JurisdictionLevel | null;
  location_city: string | null;
  location_state: string | null;
  naics_code: string | null;
  psc_code: string | null;
  set_aside: SetAsideType | null;
  estimated_value_low: number | null;
  estimated_value_high: number | null;
  funding_amount: number | null;
  posted_at: string | null;
  proposal_due_at: string | null;
  estimated_solicitation_date: string | null;
  estimated_award_date: string | null;
  estimated_time_to_procurement: string | null;
  maturity_stage: MaturityStage | null;
  intelligence_category: IntelligenceCategory;
  solicitation_number: string | null;
  contract_number: string | null;
  funding_award_number: string | null;
  project_number: string | null;
  incumbent_name: string | null;
  awardee_name: string | null;
  is_prime_award: boolean | null;
  relevant_disciplines: string[] | null;
  early_signal_score: number | null;
  early_signal_score_rationale: {
    band: string;
    category_scores: Record<string, number>;
    category_rationale: Record<string, string[]>;
    disclaimer: string;
  } | null;
  sam_relevance_score: number | null;
  sam_relevance_rationale: {
    tier: string;
    components: Record<string, number>;
    matched_positive_phrases: string[];
    matched_negative_phrases: string[];
    why_relevant: string;
    why_not_fit: string | null;
    disclaimer: string;
  } | null;
  // Not an IntelligenceItem column — see the backend schema's own comment. The
  // latest Principal Pursuit Score for the Opportunity this item promoted to, if any.
  pursuit_score: number | null;
  first_detected_at: string;
  last_seen_at: string;
  opportunity_id: string | null;
  dedup_status: string;
  project_cluster_id: string | null;
  dedup_match_reason: string | null;
  is_sample_data: boolean;
  source: string;
  source_url: string | null;
  retrieved_at: string;
  confidence: string;
}
