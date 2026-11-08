// Named aliases over the types generated from contract/openapi.json (do not hand-edit
// schema.d.ts; regenerate with `npm run api:types`). Wire fields stay snake_case.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type SessionResponse = Schemas["SessionResponse"];
export type SessionData = Schemas["SessionData"];
export type SessionUser = Schemas["SessionUser"];
export type Role = SessionUser["role"];
export type LoginRequest = Schemas["LoginRequest"];
export type ErrorResponse = Schemas["ErrorResponse"];
export type ModelsResponse = Schemas["ModelsResponse"];
export type SmsModelStatus = Schemas["SmsModelStatus"];
