import { api } from "./client";
import type {
  Agency,
  AgencyOffice,
  AiSolicitationAnalysis,
  Alert,
  Company,
  Contact,
  DashboardSummary,
  Discipline,
  ForecastSummary,
  GoNoGoCriteriaScore,
  GoNoGoReview,
  IntelligenceItem,
  IntelligenceSource,
  IntelligenceSyncRun,
  NaicsCode,
  Opportunity,
  OpportunityCompanyLink,
  OpportunityContactLink,
  OpportunityDocument,
  OpportunityListItem,
  OpportunityScore,
  PipelineStage,
  RevenueForecast,
  SyncAllResult,
  Task,
  User,
  WinLossReview,
} from "@/types";

// --- Auth ---------------------------------------------------------------------
export const authApi = {
  login: (email: string, password: string) =>
    api.post<{ access_token: string; user: User }>("/api/auth/login", { email, password }),
  me: () => api.get<User>("/api/auth/me"),
};

export const usersApi = {
  list: () => api.get<User[]>("/api/users"),
  create: (data: { email: string; full_name: string; password: string; role: string; title?: string }) =>
    api.post<User>("/api/users", data),
};

// --- Dashboard ------------------------------------------------------------------
export const dashboardApi = {
  summary: () => api.get<DashboardSummary>("/api/dashboard/summary"),
};

// --- Opportunities ----------------------------------------------------------------
export interface OpportunityListParams {
  [key: string]: string | number | undefined;
  q?: string;
  stage_id?: string;
  agency_id?: string;
  set_aside?: string;
  state?: string;
  maturity_stage?: string;
  status?: string;
  min_score?: number;
  sort_by?: string;
  sort_dir?: string;
  limit?: number;
  offset?: number;
}

function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
  const usp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
  });
  const qs = usp.toString();
  return qs ? `?${qs}` : "";
}

export const opportunitiesApi = {
  list: (params: OpportunityListParams = {}) =>
    api.get<OpportunityListItem[]>(`/api/opportunities${buildQuery(params)}`),
  get: (id: string) => api.get<Opportunity>(`/api/opportunities/${id}`),
  create: (data: Record<string, unknown>) => api.post<Opportunity>("/api/opportunities", data),
  update: (id: string, data: Record<string, unknown>) => api.patch<Opportunity>(`/api/opportunities/${id}`, data),
  archive: (id: string) => api.delete<void>(`/api/opportunities/${id}`),
  changeStage: (id: string, pipeline_stage_id: string, note?: string) =>
    api.post<Opportunity>(`/api/opportunities/${id}/stage`, { pipeline_stage_id, note }),
  getScore: (id: string) => api.get<OpportunityScore>(`/api/opportunities/${id}/score`),
  recalculateScore: (id: string) => api.post<OpportunityScore>(`/api/opportunities/${id}/score/recalculate`),
  activities: (id: string) => api.get(`/api/opportunities/${id}/activities`),
};

// --- Go/No-Go ---------------------------------------------------------------------
export const gonogoApi = {
  get: (opportunityId: string) => api.get<GoNoGoReview>(`/api/opportunities/${opportunityId}/gonogo`),
  updateCriteria: (reviewId: string, scores: { criterion: string; score: number; notes?: string }[]) =>
    api.patch<GoNoGoReview>(`/api/gonogo/${reviewId}`, scores),
  decide: (reviewId: string, decision: string, decision_notes?: string) =>
    api.post<GoNoGoReview>(`/api/gonogo/${reviewId}/decide`, { decision, decision_notes }),
};
export type { GoNoGoCriteriaScore };

// --- Tasks --------------------------------------------------------------------
export const tasksApi = {
  list: (params: { status?: string; owner_id?: string; opportunity_id?: string } = {}) =>
    api.get<Task[]>(`/api/tasks${buildQuery(params)}`),
  listForOpportunity: (opportunityId: string) => api.get<Task[]>(`/api/opportunities/${opportunityId}/tasks`),
  create: (data: Record<string, unknown>, opportunityId?: string) =>
    opportunityId
      ? api.post<Task>(`/api/opportunities/${opportunityId}/tasks`, data)
      : api.post<Task>("/api/tasks", data),
  update: (id: string, data: Record<string, unknown>) => api.patch<Task>(`/api/tasks/${id}`, data),
};

// --- Documents ------------------------------------------------------------------
export const documentsApi = {
  list: (opportunityId: string) => api.get<OpportunityDocument[]>(`/api/opportunities/${opportunityId}/documents`),
  upload: (opportunityId: string, file: File, category: string, notes?: string) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("category", category);
    if (notes) formData.append("notes", notes);
    return api.upload<OpportunityDocument>(`/api/opportunities/${opportunityId}/documents`, formData);
  },
  downloadUrl: (documentId: string) => `/api/documents/${documentId}/download`,
  analyze: (documentId: string) => api.post<AiSolicitationAnalysis>(`/api/documents/${documentId}/analyze`),
  getAnalysis: (documentId: string) => api.get<AiSolicitationAnalysis>(`/api/documents/${documentId}/analysis`),
};

// --- Forecast -------------------------------------------------------------------
export const forecastApi = {
  get: (opportunityId: string) => api.get<RevenueForecast | null>(`/api/opportunities/${opportunityId}/forecast`),
  upsert: (opportunityId: string, data: Record<string, unknown>) =>
    api.post<RevenueForecast>(`/api/opportunities/${opportunityId}/forecast`, data),
  summary: (targetPeriod?: string) =>
    api.get<ForecastSummary>(`/api/forecast/summary${buildQuery({ target_period: targetPeriod })}`),
};

// --- Agencies / Companies / Contacts ------------------------------------------------
export const agenciesApi = {
  list: (q?: string) => api.get<Agency[]>(`/api/agencies${buildQuery({ q })}`),
  get: (id: string) => api.get<Agency>(`/api/agencies/${id}`),
  create: (data: Record<string, unknown>) => api.post<Agency>("/api/agencies", data),
  update: (id: string, data: Record<string, unknown>) => api.patch<Agency>(`/api/agencies/${id}`, data),
  createOffice: (agencyId: string, data: Record<string, unknown>) =>
    api.post<AgencyOffice>(`/api/agencies/${agencyId}/offices`, data),
};

export const companiesApi = {
  list: (params: { q?: string; company_type?: string; is_sdvosb?: boolean } = {}) =>
    api.get<Company[]>(`/api/companies${buildQuery(params as Record<string, string | number | undefined>)}`),
  get: (id: string) => api.get<Company>(`/api/companies/${id}`),
  create: (data: Record<string, unknown>) => api.post<Company>("/api/companies", data),
  update: (id: string, data: Record<string, unknown>) => api.patch<Company>(`/api/companies/${id}`, data),
  listForOpportunity: (opportunityId: string) =>
    api.get<OpportunityCompanyLink[]>(`/api/opportunities/${opportunityId}/companies`),
  linkToOpportunity: (opportunityId: string, data: Record<string, unknown>) =>
    api.post<OpportunityCompanyLink>(`/api/opportunities/${opportunityId}/companies`, data),
  unlink: (linkId: string) => api.delete<void>(`/api/opportunity-companies/${linkId}`),
};

export const contactsApi = {
  list: (q?: string) => api.get<Contact[]>(`/api/contacts${buildQuery({ q })}`),
  get: (id: string) => api.get<Contact>(`/api/contacts/${id}`),
  create: (data: Record<string, unknown>) => api.post<Contact>("/api/contacts", data),
  update: (id: string, data: Record<string, unknown>) => api.patch<Contact>(`/api/contacts/${id}`, data),
  listForOpportunity: (opportunityId: string) =>
    api.get<OpportunityContactLink[]>(`/api/opportunities/${opportunityId}/contacts`),
  linkToOpportunity: (opportunityId: string, data: Record<string, unknown>) =>
    api.post<OpportunityContactLink>(`/api/opportunities/${opportunityId}/contacts`, data),
  unlink: (linkId: string) => api.delete<void>(`/api/opportunity-contacts/${linkId}`),
};

// --- Pipeline / Reference ---------------------------------------------------------
export const pipelineStagesApi = {
  list: () => api.get<PipelineStage[]>("/api/pipeline-stages"),
  update: (updates: { id: string; name?: string; sort_order?: number; is_active?: boolean }[]) =>
    api.patch<PipelineStage[]>("/api/pipeline-stages", updates),
};

export const referenceApi = {
  naicsCodes: () => api.get<NaicsCode[]>("/api/reference/naics-codes"),
  disciplines: () => api.get<Discipline[]>("/api/reference/disciplines"),
};

// --- Alerts -----------------------------------------------------------------------
export const alertsApi = {
  list: (unreadOnly?: boolean) => api.get<Alert[]>(`/api/alerts${buildQuery({ unread_only: unreadOnly ? 1 : undefined })}`),
  markRead: (id: string) => api.patch<Alert>(`/api/alerts/${id}/read`),
};

// --- Intelligence sources (Source Registry) -----------------------------------------
export const intelligenceApi = {
  listSources: () => api.get<IntelligenceSource[]>("/api/intelligence/sources"),
  updateSource: (id: string, data: { is_enabled?: boolean; polling_frequency_hours?: number | null; notes?: string }) =>
    api.patch<IntelligenceSource>(`/api/intelligence/sources/${id}`, data),
  syncSource: (id: string) => api.post<IntelligenceSyncRun>(`/api/intelligence/sources/${id}/sync`),
  syncAll: () => api.post<SyncAllResult>("/api/intelligence/sync-all"),
  syncRuns: (sourceId?: string, limit = 50) =>
    api.get<IntelligenceSyncRun[]>(`/api/intelligence/sync-runs${buildQuery({ source_id: sourceId, limit })}`),
};

// --- Intelligence items (Discover feed) ----------------------------------------------
export interface IntelligenceItemListParams {
  [key: string]: string | number | boolean | undefined;
  q?: string;
  category?: string;
  source_id?: string;
  jurisdiction_level?: string;
  state?: string;
  naics_code?: string;
  maturity_stage?: string;
  set_aside?: string;
  include_sample_data?: boolean;
  unpromoted_only?: boolean;
  sort_by?: string;
  sort_dir?: string;
  limit?: number;
  offset?: number;
}

export const intelligenceItemsApi = {
  list: (params: IntelligenceItemListParams = {}) =>
    api.get<IntelligenceItem[]>(`/api/intelligence/items${buildQuery(params)}`),
};

// --- Settings -----------------------------------------------------------------------
export const settingsApi = {
  getScoringWeights: () =>
    api.get<{ id: string; name: string; weights: Record<string, number>; geographic_priorities: Record<string, number>; agency_priority_tiers: Record<string, number> }>(
      "/api/settings/scoring-weights"
    ),
  updateScoringWeights: (data: Record<string, unknown>) =>
    api.patch("/api/settings/scoring-weights", data),
  getHideSampleData: () => api.get<{ hide_sample_data_by_default: boolean }>("/api/settings/hide-sample-data"),
  setHideSampleData: (value: boolean) =>
    api.patch<{ hide_sample_data_by_default: boolean }>("/api/settings/hide-sample-data", { hide_sample_data_by_default: value }),
};

// --- Win/Loss -------------------------------------------------------------------------
export const winLossApi = {
  get: (opportunityId: string) => api.get<WinLossReview | null>(`/api/opportunities/${opportunityId}/win-loss`),
  create: (opportunityId: string, data: Record<string, unknown>) =>
    api.post<WinLossReview>(`/api/opportunities/${opportunityId}/win-loss`, data),
};
