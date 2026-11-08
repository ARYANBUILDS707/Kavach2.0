// Named aliases over the types generated from contract/openapi.json (do not hand-edit
// schema.d.ts; regenerate with `npm run api:types`). Wire fields stay snake_case.
import type { components, operations } from "./schema";

type Schemas = components["schemas"];

export type SessionResponse = Schemas["SessionResponse"];
export type SessionData = Schemas["SessionData"];
export type SessionUser = Schemas["SessionUser"];
export type Role = SessionUser["role"];
export type LoginRequest = Schemas["LoginRequest"];
export type ErrorResponse = Schemas["ErrorResponse"];

export type ModelsResponse = Schemas["ModelsResponse"];
export type SmsModelStatus = Schemas["SmsModelStatus"];
export type ModelState = SmsModelStatus["state"];

export type IncidentListResponse = Schemas["IncidentListResponse"];
export type IncidentSummary = Schemas["IncidentSummary"];
export type IncidentDetailResponse = Schemas["IncidentDetailResponse"];
export type IncidentDetail = Schemas["IncidentDetailData"];
export type IncidentEvent = Schemas["IncidentEventView"];
export type Assessment = Schemas["AssessmentView"];
export type Stage = Schemas["Stage"];
export type ModelOutput = Schemas["ModelOutput"];
export type Tier = IncidentSummary["tier"];
export type AnalysisStatus = IncidentSummary["analysis_status"];
export type IncidentKind = IncidentSummary["kind"];
export type Channel = IncidentEvent["channel"];

/** Exactly the query the contract accepts (`review_status` is not supported: 422). */
export type IncidentListQuery = NonNullable<
  operations["list_incidents_api_v1_incidents_get"]["parameters"]["query"]
>;
