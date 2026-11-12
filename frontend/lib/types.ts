export interface User {
  id: string;
  username: string;
  is_admin: boolean;
  last_login_at: string | null;
}

export interface AdminUser extends User {
  is_active: boolean;
  telegram_enabled: boolean;
  telegram_chat_id: string | null;
}

export interface AuthResponse {
  user: User;
  csrf_token: string;
  expires_at: string;
}

export interface MessageResponse {
  ok: boolean;
  message: string;
}

export interface Credential {
  id: string;
  label: string;
  token_hint: string;
  status: string;
  is_primary: boolean;
  rate_limit_per_second: number;
  sender_id: number | null;
  last_checked_at: string | null;
  last_check_ok: boolean | null;
  last_check_message: string | null;
}

export interface Collection {
  id: string;
  name: string;
  short_name: string | null;
  photo_url: string | null;
  floor_price: string | null;
  max_offer: string | null;
  supply: number | null;
  day_volume: string | null;
  market_cap: string | null;
  is_new: boolean;
  zero_commission: boolean;
  cashback_percent: string | null;
  points_multiplier: string | null;
  offers_supported: boolean;
  models_available: boolean;
  models_count: number;
  updated_at: string;
}

export interface CollectionModel {
  name: string;
  photo_url: string | null;
  floor_price: string | null;
  max_offer: string | null;
}

export type CollectionAttribute = CollectionModel;

export interface Rule {
  id: string;
  name: string;
  collection_id: string;
  collection_name: string | null;
  scope_mode: string;
  models: string[];
  backdrops: string[];
  excluded_backdrops: string[];
  symbols: string[];
  scope_guard: boolean;
  strategy: string;
  hold_first_place: boolean;
  pause_on_uncertainty: boolean;
  discount_percent: string;
  max_price_percent: string | null;
  fixed_price: string | null;
  min_step: string;
  max_price_per_offer: string | null;
  max_budget: string | null;
  max_active_offers: number;
  max_nfts: number;
  expiration_days: number | null;
  check_interval_seconds: number;
  enabled: boolean;
  state: string;
  on_limit_behavior: string;
  last_run_at: string | null;
  next_run_at: string | null;
  last_error: string | null;
  last_position_status: string | null;
  last_decision: Record<string, unknown> | null;
  active_offers: number;
  created_at: string;
  updated_at: string;
}

export interface DryRunPreview {
  rule_id: string | null;
  action: string;
  status: string;
  reason: string;
  target_price: string | null;
  cap: string | null;
  floor_price: string | null;
  competitor_amount: string | null;
  own_amount: string | null;
  own_rank: number | null;
  total_offers: number;
  detail: Record<string, unknown>;
}

export interface Offer {
  id: string;
  rule_id: string;
  rule_name: string | null;
  source: string;
  rebid_count: number;
  collection_id: string;
  collection_name: string | null;
  external_offer_id: string;
  scope: Record<string, unknown>;
  scope_kind: string;
  amount: string;
  max_amount: string | null;
  max_nfts: number;
  current_nfts: number;
  status: string;
  position_status: string;
  position_rank: number | null;
  last_action: string | null;
  last_action_at: string | null;
  last_synced_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface PurchasedGift {
  id: string;
  offer_id: string;
  collection_id: string;
  collection_name: string;
  gift_id: string | null;
  amount: string;
  purchased_at: string;
  portals_url: string | null;
  raw: Record<string, unknown> | null;
}

export interface Operation {
  id: string;
  operation_type: string;
  state: string;
  attempts: number;
  max_attempts: number;
  scheduled_at: string;
  started_at: string | null;
  finished_at: string | null;
  last_error: string | null;
  requires_verification: boolean;
  result: Record<string, unknown> | null;
  rule_id: string | null;
  offer_id: string | null;
  created_at: string;
}

export interface HistoryEntry {
  id: string;
  action: string;
  level: string;
  message: string;
  actor: string;
  entity_type: string | null;
  entity_id: string | null;
  details: Record<string, unknown> | null;
  duration_ms: number | null;
  created_at: string;
}

export interface Settings {
  automation_enabled: boolean;
  emergency_stop: boolean;
  emergency_stop_reason: string | null;
  mode: string;
  default_min_step: string;
  throughput: Record<string, unknown> | null;
  notifications_paused: boolean;
  smart_trader_enabled: boolean;
  smart_trader_min_spread_percent: string;
  smart_trader_max_rebids_per_offer: number | null;
  smart_trader_excluded_collections: string[];
  smart_trader_excluded_models: string[];
  smart_trader_excluded_backdrops: string[];
  smart_trader_excluded_symbols: string[];
  smart_trader_attribute_collection_id: string | null;
}

export interface NotificationItem {
  id: string;
  level: string;
  event: string;
  title: string;
  message: string;
  read_at: string | null;
  created_at: string;
}

export interface NotificationSettings {
  in_app_enabled: boolean;
  telegram_enabled: boolean;
  telegram_chat_id: string | null;
  events: Record<string, boolean>;
  min_interval_seconds: number;
  max_per_hour: number;
}

export interface DashboardSummary {
  api_status: string;
  api_message: string | null;
  api_last_check: string | null;
  worker_state: string;
  worker_last_tick: string | null;
  mode: string;
  automation_enabled: boolean;
  emergency_stop: boolean;
  active_rules: number;
  paused_rules: number;
  error_rules: number;
  active_offers: number;
  first_place_confirmed: number;
  outbid_offers: number;
  limit_reached_offers: number;
  insufficient_funds_offers: number;
  unknown_position_offers: number;
  balance: string | null;
  frozen_funds: string | null;
  balance_source: string;
  queue: Record<string, number>;
  rate_limit: Record<string, unknown> | null;
  throughput: Record<string, unknown> | null;
  recent_events: HistoryEntry[];
}

export interface SystemStatus {
  app_version: string;
  environment: string;
  database: string;
  portals_reachable: boolean;
  credential_status: string | null;
  credential_hint: string | null;
  requests_total: number;
  errors_total: number;
  rate_limited_total: number;
  last_success_at: string | null;
  last_error_at: string | null;
  last_error_message: string | null;
  remaining_limit: number | null;
  limit_per_second: number | null;
  worker: Record<string, unknown>;
  queue: Record<string, number>;
  offers_synced_at: string | null;
  unsynced_offers: number;
}
