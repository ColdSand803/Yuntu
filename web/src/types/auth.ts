import type { TripFormData } from "./form";

export type AuthMode = "login" | "register";

export interface User {
  user_id: string;
  display_name: string;
  display_name_change_available_at: string | null;
  masked_email: string | null;
  linux_do_username: string | null;
  email_login_enabled: boolean;
  display_name_review_required: boolean;
}

export interface ProfileUpdateResponse {
  ok: boolean;
  user: User;
}

export interface Quota {
  policy?: string;
  limit: number;
  reserved: number;
  consumed: number;
  remaining: number;
  resets_at?: string | null;
}

export interface ActiveTrip {
  trip_id: string;
  job_id: string;
  status: "SUBMITTING" | "PENDING" | "RUNNING" | string;
}

export interface MeResponse {
  ok: boolean;
  user: User;
  quota: Quota;
  active_trip: ActiveTrip | null;
}

export interface SendCodeRequest {
  mode: AuthMode;
  email: string;
  invitation_code?: string | null;
}

export interface SendCodeResponse {
  ok: boolean;
  challenge_id: string;
  resend_after_seconds: number;
}

export interface VerifyCodeRequest {
  challenge_id: string;
  code: string;
}

export interface ClosureSendCodeResponse {
  ok: boolean;
  challenge_id: string;
  resend_after_seconds: number;
}

export interface ClosureConfirmRequest {
  challenge_id: string;
  code: string;
}

export interface HistoryTripItem {
  trip_id: string;
  job_id: string;
  status: "SUCCESS" | "FAILED" | "TIMEOUT" | "REJECTED";
  city: string;
  days: number;
  result_record_id: number | string | null;
  created_at: string;
  finished_at: string | null;
  expires_from_history_at: string;
  retry_input: {
    trip_request: TripFormData;
  };
  error: {
    code: string;
    message: string;
    retryable: boolean;
  } | null;
}

export interface HistoryResponse {
  ok: boolean;
  items: HistoryTripItem[];
  next_cursor: string | null;
}
