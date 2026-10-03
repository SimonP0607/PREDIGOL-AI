/** Types for /api/v1/auth/* and /api/v1/admin/{users,audit}. Mirrors fbi.api.contracts.auth. */
import type { Iso } from "./types";

export type Language = "es" | "en";
export type RoleKey = "SUPER_ADMIN" | "USER";
export type PermissionKey = "app" | "admin" | "admin.users" | "admin.shadow_preview";

export interface Me {
  id: number;
  email: string;
  display_name: string;
  role: RoleKey | string;
  permissions: PermissionKey[];
  language: Language;
  /** IANA zone every time on screen is shown in. Stored data stays UTC. */
  timezone: string;
  session_expires_at: Iso;
}

export interface PreferencesIn {
  language?: Language;
  timezone?: string;
  display_name?: string;
}

export interface AdminUser {
  id: number;
  email: string;
  display_name: string;
  role: RoleKey | string;
  status: "active" | "disabled";
  language: Language;
  timezone: string;
  created_at: Iso;
  last_login_at: Iso | null;
  active_sessions: number;
}

export interface AdminUserCreate {
  email: string;
  display_name?: string;
  role: RoleKey;
  password: string;
  language: Language;
  timezone: string;
}

export interface AuditEvent {
  id: number;
  at: Iso;
  action: string;
  actor_email: string | null;
  target_email: string | null;
  email: string | null;
  ip: string | null;
  detail: Record<string, unknown>;
}
