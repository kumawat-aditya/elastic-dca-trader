import React from "react";
import { SystemState } from "../types";
import { Activity, Server, Settings2 } from "lucide-react";

interface Props {
  state: SystemState | null;
  serverConnected: boolean;
  eaConnected: boolean;
  onCreatePreset: () => void;
}

export default function TopBar({
  state,
  serverConnected,
  eaConnected,
  onCreatePreset,
}: Props) {
  const getTrendColor = (trend?: string) => {
    if (!trend) return "text-slate-400";
    const t = trend.toLowerCase();
    if (t === "buy") return "text-emerald-500 font-bold uppercase";
    if (t === "sell") return "text-rose-500 font-bold uppercase";
    return "text-slate-400 uppercase";
  };

  return (
    <div className="bg-slate-900 border-b border-slate-800 p-3 flex flex-col md:flex-row items-center justify-between shrink-0 gap-4 shadow-sm z-10">
      <div className="flex items-center space-x-4">
        <h1 className="text-xl font-bold text-slate-200 tracking-tight">
          Elastic DCA v4
        </h1>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-3 text-sm font-mono">
        <div className="text-slate-400 font-bold px-2">
          {state?.symbol || "---"}
        </div>
        <div className="flex space-x-4 bg-slate-800/50 px-3 py-1.5 rounded-md border border-slate-700/50">
          <div className="text-slate-400">
            Ask:{" "}
            <span className="text-rose-500">
              {state?.current_ask?.toFixed(5) || "---"}
            </span>
          </div>
          <div className="text-slate-400">
            Bid:{" "}
            <span className="text-emerald-500">
              {state?.current_bid?.toFixed(5) || "---"}
            </span>
          </div>
          <div className="text-slate-400">
            Mid:{" "}
            <span className="text-blue-500 font-bold">
              {state?.current_mid?.toFixed(5) || "---"}
            </span>
          </div>
        </div>
        <div className="flex space-x-4 bg-slate-800/50 px-3 py-1.5 rounded-md border border-slate-700/50">
          <div className="text-slate-400">
            H1:{" "}
            <span className={getTrendColor(state?.trend_h1)}>
              {state?.trend_h1 || "---"}
            </span>
          </div>
          <div className="text-slate-400">
            H4:{" "}
            <span className={getTrendColor(state?.trend_h4)}>
              {state?.trend_h4 || "---"}
            </span>
          </div>
        </div>
        <div className="flex space-x-4 bg-slate-800/50 px-3 py-1.5 rounded-md border border-slate-700/50">
          <div className="text-slate-400">
            Equity:{" "}
            <span className="text-emerald-500">
              ${state?.equity?.toFixed(2) || "---"}
            </span>
          </div>
          <div className="text-slate-400">
            Balance:{" "}
            <span className="text-slate-300">
              ${state?.balance?.toFixed(2) || "---"}
            </span>
          </div>
        </div>
      </div>

      <div className="flex items-center space-x-6">
        <div className="flex items-center space-x-4 text-xs font-bold uppercase tracking-wider">
          <div className="flex items-center space-x-1.5">
            <Server
              className={`w-4 h-4 ${serverConnected ? "text-emerald-500" : "text-rose-500"}`}
            />
            <span
              className={serverConnected ? "text-emerald-500" : "text-rose-500"}
            >
              Server: {serverConnected ? "Connected" : "Disconnected"}
            </span>
          </div>
          <div className="flex items-center space-x-1.5">
            <Activity
              className={`w-4 h-4 ${eaConnected ? "text-emerald-500" : "text-rose-500"}`}
            />
            <span
              className={eaConnected ? "text-emerald-500" : "text-rose-500"}
            >
              EA: {eaConnected ? "Connected" : "Disconnected"}
            </span>
          </div>
        </div>

        <button
          onClick={onCreatePreset}
          className="bg-slate-800 hover:bg-slate-700 border border-slate-700/50 text-slate-200 px-3 py-1.5 rounded-md text-sm font-medium flex items-center space-x-2 transition-colors shadow-sm"
        >
          <Settings2 className="w-4 h-4 text-slate-400" />
          <span>Manage Presets</span>
        </button>
      </div>
    </div>
  );
}
