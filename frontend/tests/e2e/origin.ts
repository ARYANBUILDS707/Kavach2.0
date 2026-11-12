/** The origin the app is served from. The backend checks the exact Origin header, so API calls
 * made directly from a test must send the same one the browser does. Defaults to the standard
 * local development origin; set KAVACH_E2E_ORIGIN when serving the app on another port. */
export const ORIGIN = process.env.KAVACH_E2E_ORIGIN ?? "http://127.0.0.1:5173";
