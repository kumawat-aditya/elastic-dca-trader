export type Side = "buy" | "sell";

export interface GridRow {
  index: number;
  gap: number;
  lots: number;
  alert: boolean;

  // --- SERVER MANAGED (Read-Only for UI Display) ---
  readonly alert_executed: boolean;
  readonly executed: boolean;
  readonly price: number | null;
  readonly cumulative_lots: number;
  readonly pnl: number;
  readonly cumulative_pnl: number;
}

export interface GridSettings {
  is_on: boolean;
  is_cyclic: boolean;
  start_limit: number | null;
  row_stop_limit: number | null;
  tp_type: "fixed" | "equity" | "balance";
  tp_value: number;
  sl_type: "fixed" | "equity" | "balance";
  sl_value: number;
  hedging: number | null;
  rows: GridRow[];
}

export interface GridState {
  readonly session_id: string | null;
  readonly reference_point: number | null;
  readonly is_hedged: boolean;
  readonly hedge_data: {
    entry_price: number;
    sl: number;
    tp: number;
    lots: number;
  } | null;
  readonly emergency_state: boolean;
  readonly total_cumulative_lots: number;
  readonly total_cumulative_pnl: number;
}

export interface SystemState {
  readonly ea_connected: boolean;
  readonly last_ea_ping_ts: number;
  readonly account_id: string;
  readonly symbol: string;
  readonly equity: number;
  readonly balance: number;
  readonly current_mid: number;
  readonly current_ask: number;
  readonly current_bid: number;
  readonly trend_h1: string;
  readonly trend_h4: string;

  buy_settings: GridSettings;
  buy_state: GridState;
  sell_settings: GridSettings;
  sell_state: GridState;
}

export interface Preset {
  id: string;
  name: string;
  rows: GridRow[];
}
