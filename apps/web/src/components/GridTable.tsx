import React from "react";
import { GridRow, Side } from "../types";
import { Plus, Trash2 } from "lucide-react";
import { NumberInput } from "./NumberInput";

interface Props {
  side: Side;
  rows: GridRow[];
  isOn: boolean;
  onChange: (index: number, field: keyof GridRow, value: any) => void;
  onAddRow: () => void;
  onRemoveRow: (index: number) => void;
}

export default function GridTable({
  side,
  rows,
  isOn,
  onChange,
  onAddRow,
  onRemoveRow,
}: Props) {
  const isBuy = side === "buy";
  const highlightClass = isBuy
    ? "bg-emerald-500/10 text-emerald-200/90"
    : "bg-rose-500/10 text-rose-200/90";
  const focusRing = isBuy
    ? "focus:ring-emerald-500/30 focus:border-emerald-500/50"
    : "focus:ring-rose-500/30 focus:border-rose-500/50";

  return (
    <div className="flex-1 overflow-auto relative scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-slate-900 flex flex-col min-h-0">
      <table className="w-full text-left text-sm whitespace-nowrap">
        <thead className="sticky top-0 bg-slate-900 backdrop-blur text-xs text-slate-400 uppercase border-b border-slate-800 z-10 shadow-sm">
          <tr>
            <th className="px-3 py-3 font-medium">Idx</th>
            <th className="px-3 py-3 font-medium">Gap</th>
            <th className="px-3 py-3 font-medium">Lots</th>
            <th className="px-3 py-3 font-medium">Price</th>
            <th className="px-3 py-3 font-medium">CumLots</th>
            <th className="px-3 py-3 font-medium">CumPnL</th>
            <th className="px-3 py-3 font-medium text-center">Alert</th>
            <th className="px-3 py-3 font-medium text-center"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/50">
          {rows.map((row) => {
            const isExecuted = row.executed;
            const isLocked = isExecuted && isOn;
            const rowClass = isExecuted
              ? highlightClass
              : "hover:bg-slate-800/40 transition-colors";

            return (
              <tr key={row.index} className={rowClass}>
                <td className="px-3 py-2 font-mono text-slate-500">
                  {row.index}
                </td>
                <td className="px-3 py-2">
                  <NumberInput
                    min={0}
                    disabled={isLocked}
                    value={row.gap}
                    onChange={(val) => onChange(row.index, "gap", val ?? 0)}
                    className={`w-16 bg-slate-800 border border-slate-700 rounded-md px-1 py-0.5 outline-none font-mono text-center transition-all ${focusRing} ${isLocked ? "opacity-50 cursor-not-allowed border-transparent bg-transparent" : "hover:border-slate-600 focus:ring-1"}`}
                  />
                </td>
                <td className="px-3 py-2">
                  <NumberInput
                    min={0.01}
                    step="0.01"
                    disabled={isLocked}
                    value={row.lots}
                    onChange={(val) => onChange(row.index, "lots", val ?? 0.01)}
                    className={`w-16 bg-slate-800 border border-slate-700 rounded-md px-1 py-0.5 outline-none font-mono text-center transition-all ${focusRing} ${isLocked ? "opacity-50 cursor-not-allowed border-transparent bg-transparent" : "hover:border-slate-600 focus:ring-1"}`}
                  />
                </td>
                <td className="px-3 py-2 font-mono text-slate-300">
                  {row.price != null ? row.price.toFixed(5) : "---"}
                </td>
                <td className="px-3 py-2 font-mono text-slate-400">
                  {row.cumulative_lots != null
                    ? row.cumulative_lots.toFixed(2)
                    : "---"}
                </td>
                <td
                  className={`px-3 py-2 font-mono font-bold ${row.cumulative_pnl && row.cumulative_pnl >= 0 ? "text-emerald-500" : row.cumulative_pnl && row.cumulative_pnl < 0 ? "text-rose-500" : "text-slate-500"}`}
                >
                  {row.cumulative_pnl != null
                    ? `$${row.cumulative_pnl.toFixed(2)}`
                    : "---"}
                </td>
                <td className="px-3 py-2 text-center">
                  <input
                    type="checkbox"
                    checked={row.alert}
                    onChange={(e) =>
                      onChange(row.index, "alert", e.target.checked)
                    }
                    className={`form-checkbox h-4 w-4 bg-slate-900 border-slate-700 rounded cursor-pointer transition-all ${isBuy ? "text-emerald-500 focus:ring-emerald-500/50" : "text-rose-500 focus:ring-rose-500/50"}`}
                  />
                </td>
                <td className="px-3 py-2 text-center">
                  {!isLocked && (
                    <button
                      onClick={() => onRemoveRow(row.index)}
                      className="text-slate-500 hover:text-rose-500 transition-colors p-1"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="p-3 border-t border-slate-800/50 mt-auto sticky bottom-0 bg-slate-900 backdrop-blur-sm">
        <button
          onClick={onAddRow}
          className={`w-full py-2 border border-dashed border-slate-700 rounded-md text-slate-400 hover:text-slate-200 flex items-center justify-center space-x-2 transition-colors ${isBuy ? "hover:border-emerald-500/40 hover:bg-emerald-500/10" : "hover:border-rose-500/40 hover:bg-rose-500/10"}`}
        >
          <Plus className="w-4 h-4" />
          <span className="text-sm font-medium uppercase tracking-wider">
            Add Row
          </span>
        </button>
      </div>
    </div>
  );
}
