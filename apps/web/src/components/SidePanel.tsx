import React, { useState, useEffect, useRef, useCallback } from "react";
import { Side, SystemState, Preset, GridSettings } from "../types";
import * as api from "../services/api";
import GridTable from "./GridTable";
import { toast } from "sonner";
import { NumberInput } from "./NumberInput";
import { RefreshCw } from "lucide-react";

const Toggle = ({
  checked,
  onChange,
  activeColorClass,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  activeColorClass: string;
}) => (
  <button
    type="button"
    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center justify-center rounded-full transition-colors duration-200 ease-in-out focus:outline-none ${checked ? activeColorClass : "bg-slate-700"}`}
    onClick={() => onChange(!checked)}
  >
    <span
      className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${checked ? "translate-x-2" : "-translate-x-2"}`}
    />
  </button>
);

interface Props {
  side: Side;
  state: SystemState | null;
  presets: Preset[];
  onRefreshPresets: () => void;
}

export default function SidePanel({
  side,
  state,
  presets,
  onRefreshPresets,
}: Props) {
  const isBuy = side === "buy";
  const colorClass = isBuy ? "text-emerald-500" : "text-rose-500";
  const bgClass = isBuy ? "bg-emerald-500/5" : "bg-rose-500/5";
  const activeToggleClass = isBuy ? "bg-emerald-600" : "bg-rose-600";
  const btnClass = isBuy
    ? "bg-emerald-600/90 hover:bg-emerald-600 text-slate-100"
    : "bg-rose-600/90 hover:bg-rose-600 text-slate-100";

  const settings = isBuy ? state?.buy_settings : state?.sell_settings;
  const emergency = isBuy
    ? state?.buy_state?.emergency_state
    : state?.sell_state?.emergency_state;
  const isHedged = isBuy
    ? state?.buy_state?.is_hedged
    : state?.sell_state?.is_hedged;
  const hedgeData = isBuy
    ? state?.buy_state?.hedge_data
    : state?.sell_state?.hedge_data;

  // Local state for edits
  const [localSettings, setLocalSettings] = useState<GridSettings | null>(null);
  const [showConfirmOff, setShowConfirmOff] = useState(false);
  const [pendingControl, setPendingControl] = useState<{
    is_on: boolean;
    is_cyclic: boolean;
  } | null>(null);
  const needsFullResync = useRef(false);

  const latestSettingsRef = useRef(settings);
  useEffect(() => {
    latestSettingsRef.current = settings;
  }, [settings]);

  // Resync function
  const handleResync = useCallback(() => {
    if (settings) {
      setLocalSettings(JSON.parse(JSON.stringify(settings)));
    }
  }, [settings]);

  // Resync when emergency state is removed
  const prevEmergencyRef = useRef(emergency);
  useEffect(() => {
    if (prevEmergencyRef.current && !emergency) {
      handleResync();
    }
    prevEmergencyRef.current = emergency;
  }, [emergency, handleResync]);

  // Trigger notification when hedging is triggered
  const prevHedgedRef = useRef(isHedged);
  useEffect(() => {
    if (isHedged && !prevHedgedRef.current) {
      // Trigger visual toast
      toast.warning(`${side.toUpperCase()} Hedging Triggered!`, {
        duration: 5000,
      });

      // Play audio sound
      const audio = new Audio(
        "https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3",
      );
      audio.play().catch((e) => console.error("Audio play failed", e));
    }
    prevHedgedRef.current = isHedged;
  }, [isHedged, side]);

  useEffect(() => {
    if (settings) {
      setLocalSettings((prev) => {
        if (!prev || needsFullResync.current) {
          needsFullResync.current = false;
          return JSON.parse(JSON.stringify(settings));
        }

        // Merge server executed state into local rows
        const mergedRows = prev.rows.map((localRow) => {
          const serverRow = settings.rows.find(
            (r) => r.index === localRow.index,
          );
          if (serverRow) {
            let newlyAlerted = false;

            // Check if we should trigger an alert
            // We use localRow.alert so it works even if the user hasn't hit "Apply Settings" yet
            if (
              localRow.alert &&
              serverRow.executed &&
              !localRow.alert_executed &&
              !serverRow.alert_executed
            ) {
              // Trigger visual toast
              toast.success(
                `${side.toUpperCase()} Row ${localRow.index} Executed at ${serverRow.price}!`,
                {
                  duration: 5000,
                },
              );

              // Play audio sound
              const audio = new Audio(
                "https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3",
              );
              audio.play().catch((e) => console.error("Audio play failed", e));

              newlyAlerted = true;

              // Ack to backend just in case the backend knew about the alert
              api.ackAlert(side, localRow.index).catch(() => {});
            }

            return {
              ...localRow,
              executed: serverRow.executed,
              // Keep it true locally if we just fired it, or if it was already true. Reset if not executed.
              alert_executed: serverRow.executed
                ? serverRow.alert_executed ||
                  localRow.alert_executed ||
                  newlyAlerted
                : false,
              price: serverRow.price,
              cumulative_lots: serverRow.cumulative_lots,
              cumulative_pnl: serverRow.cumulative_pnl,
              // If executed, lock gap and lots to server values
              ...(serverRow.executed
                ? { gap: serverRow.gap, lots: serverRow.lots }
                : {}),
            };
          }
          return localRow;
        });

        return {
          ...prev,
          is_on: settings.is_on,
          is_cyclic: settings.is_cyclic,
          rows: mergedRows,
        };
      });
    }
  }, [settings, side]);

  const executeControl = async (is_on: boolean, is_cyclic: boolean) => {
    try {
      setLocalSettings((prev) => (prev ? { ...prev, is_on, is_cyclic } : null));
      const res = await api.controlSide(side, is_on, is_cyclic);
      if (!res.ok) throw new Error("Failed to control side");
    } catch (e) {
      toast.error("Failed to update control state.");
      handleResync(); // Revert on failure
    }
  };

  const handleControl = async (is_on: boolean, is_cyclic: boolean) => {
    if (!is_on && settings?.is_on) {
      setPendingControl({ is_on, is_cyclic });
      setShowConfirmOff(true);
      return;
    }
    await executeControl(is_on, is_cyclic);
  };

  const confirmTurnOff = () => {
    if (pendingControl) {
      executeControl(pendingControl.is_on, pendingControl.is_cyclic);
    }
    setShowConfirmOff(false);
    setPendingControl(null);
  };

  const cancelTurnOff = () => {
    setShowConfirmOff(false);
    setPendingControl(null);
  };

  const handleApplySettings = async () => {
    if (localSettings) {
      if (
        localSettings.tp_value === null ||
        localSettings.tp_value === undefined ||
        localSettings.tp_value < 0 ||
        isNaN(localSettings.tp_value)
      ) {
        toast.error("Take Profit value must be filled and cannot be negative.");
        return;
      }
      if (
        localSettings.sl_value === null ||
        localSettings.sl_value === undefined ||
        localSettings.sl_value < 0 ||
        isNaN(localSettings.sl_value)
      ) {
        toast.error("Stop Loss value must be filled and cannot be negative.");
        return;
      }
      if (localSettings.stop_limit !== null && localSettings.stop_limit < 0) {
        toast.error("Stop Limit cannot be negative.");
        return;
      }

      // Validate rows
      for (const row of localSettings.rows) {
        if (row.lots < 0.01 || isNaN(row.lots)) {
          toast.error(`Row ${row.index} lots must be at least 0.01.`);
          return;
        }
        if (row.gap < 0 || isNaN(row.gap)) {
          toast.error(`Row ${row.index} gap cannot be negative.`);
          return;
        }
      }

      try {
        const res = await api.updateSettings(side, localSettings);
        if (!res.ok) throw new Error("Failed to apply settings");
        toast.success(`${side.toUpperCase()} settings applied successfully.`);

        // Wait 1 second before doing a full resync so the server has time to apply the changes
        setTimeout(() => {
          needsFullResync.current = true;
          // Force a re-render to trigger the useEffect that checks needsFullResync
          setLocalSettings((prev) => (prev ? { ...prev } : null));
        }, 1000);
      } catch (e) {
        toast.error("Failed to apply settings. Some rows might be locked.");
      }
    }
  };

  const handleLoadPreset = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const presetId = e.target.value;
    if (!presetId || presetId === "custom") return;
    if (settings?.is_on) {
      toast.error(
        "Cannot load preset while grid is ON. Please turn it off first.",
      );
      e.target.value = "custom";
      return;
    }

    try {
      const res = await api.loadPreset(presetId, side);
      if (!res.ok) throw new Error("Failed to load preset");
      toast.success(`Preset loaded for ${side.toUpperCase()}`);

      // Auto re-sync to the server when the websocket delivers the new settings
      needsFullResync.current = true;

      // Apply preset locally for immediate feedback
      const preset = presets.find((p) => p.id === presetId);
      if (preset) {
        setLocalSettings((prev) =>
          prev
            ? { ...prev, rows: JSON.parse(JSON.stringify(preset.rows)) }
            : null,
        );
      }
    } catch (e) {
      toast.error("Failed to load preset.");
    }
    e.target.value = "custom";
  };

  const updateLocalSetting = (key: keyof GridSettings, value: any) => {
    setLocalSettings((prev) => (prev ? { ...prev, [key]: value } : null));
  };

  const handleAddRow = () => {
    setLocalSettings((prev) => {
      if (!prev) return prev;
      const newIndex =
        prev.rows.length > 0
          ? Math.max(...prev.rows.map((r) => r.index)) + 1
          : 0;
      return {
        ...prev,
        rows: [
          ...prev.rows,
          { index: newIndex, gap: 10, lots: 0.01, alert: false } as any,
        ],
      };
    });
  };

  const handleRemoveRow = (indexToRemove: number) => {
    setLocalSettings((prev) => {
      if (!prev) return prev;
      const filtered = prev.rows.filter((r) => r.index !== indexToRemove);
      const reindexed = filtered.map((r, i) => ({ ...r, index: i }));
      return {
        ...prev,
        rows: reindexed,
      };
    });
  };

  if (!localSettings) {
    return <div className="p-4 text-gray-500">Waiting for data...</div>;
  }

  return (
    <div className="flex flex-col h-full relative">
      {emergency && (
        <div className="absolute inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-8">
          <div className="bg-rose-900/90 border-2 border-rose-500 rounded-xl p-8 text-center max-w-md shadow-2xl">
            <div className="text-5xl mb-4">🚨</div>
            <h2 className="text-2xl font-bold text-white mb-2 uppercase">
              Unknown {side} Trades Detected
            </h2>
            <p className="text-rose-200">
              Please close them manually in MT5 to resume operation.
            </p>
          </div>
        </div>
      )}

      <div
        className={`p-3 border-b border-slate-800/50 flex justify-center items-center relative ${bgClass}`}
      >
        <h2
          className={`text-lg font-bold uppercase tracking-wider ${colorClass}`}
        >
          {side} SECTION
        </h2>
      </div>

      {isHedged && (
        <div className="bg-yellow-500/20 border-b border-yellow-500/50 p-3 flex flex-col justify-center items-center">
          <span className="text-yellow-400 font-bold text-sm uppercase tracking-wider flex items-center gap-2 mb-2">
            <span>⚠️</span> Hedging Triggered
          </span>
          {hedgeData && (
            <div className="grid grid-cols-4 gap-4 text-xs font-mono text-yellow-200/80 w-full max-w-sm">
              <div className="flex flex-col items-center">
                <span className="text-yellow-500/60 uppercase text-[10px] mb-0.5">
                  Entry
                </span>
                <span>{hedgeData.entry_price.toFixed(2)}</span>
              </div>
              <div className="flex flex-col items-center">
                <span className="text-yellow-500/60 uppercase text-[10px] mb-0.5">
                  Lots
                </span>
                <span>{hedgeData.lots.toFixed(2)}</span>
              </div>
              <div className="flex flex-col items-center">
                <span className="text-yellow-500/60 uppercase text-[10px] mb-0.5">
                  TP
                </span>
                <span>{hedgeData.tp.toFixed(2)}</span>
              </div>
              <div className="flex flex-col items-center">
                <span className="text-yellow-500/60 uppercase text-[10px] mb-0.5">
                  SL
                </span>
                <span>{hedgeData.sl.toFixed(2)}</span>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="p-4 border-b border-slate-800/50 bg-slate-900/30 flex-shrink-0">
        {/* Solo Inputs Row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
          <div>
            <label className="block text-xs text-slate-400 uppercase mb-1">
              Start Limit
            </label>
            <NumberInput
              className="w-full bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-slate-300 focus:border-slate-500 focus:ring-1 focus:ring-slate-500 outline-none transition-all font-mono"
              value={localSettings.start_limit}
              onChange={(val) => updateLocalSetting("start_limit", val)}
              min={0}
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 uppercase mb-1">
              Stop Limit
            </label>
            <NumberInput
              min={0}
              isInteger={true}
              step="1"
              className="w-full bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-slate-300 focus:border-slate-500 focus:ring-1 focus:ring-slate-500 outline-none transition-all font-mono"
              value={localSettings.stop_limit}
              onChange={(val) => updateLocalSetting("stop_limit", val)}
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 uppercase mb-1">
              Hedging
            </label>
            <NumberInput
              className="w-full bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-slate-300 focus:border-slate-500 focus:ring-1 focus:ring-slate-500 outline-none transition-all font-mono"
              value={localSettings.hedging}
              onChange={(val) => updateLocalSetting("hedging", val)}
              min={0}
            />
          </div>
          <div
            title={
              settings?.is_on
                ? "You must turn the grid OFF before applying a preset."
                : ""
            }
          >
            <label className="block text-xs text-slate-400 uppercase mb-1">
              Preset
            </label>
            <select
              className={`w-full bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-slate-300 focus:border-slate-500 focus:ring-1 focus:ring-slate-500 outline-none transition-all font-mono ${settings?.is_on ? "opacity-50 cursor-not-allowed" : ""}`}
              onChange={handleLoadPreset}
              onFocus={onRefreshPresets}
              onClick={onRefreshPresets}
              defaultValue="custom"
              disabled={settings?.is_on}
            >
              <option value="custom">Custom</option>
              {presets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* TP and SL Blocks Row */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
          {/* TP Block */}
          <div className="bg-emerald-500/5 border border-emerald-500/10 rounded-lg p-3">
            <label className="block text-xs text-emerald-500 uppercase mb-2 font-bold">
              Take Profit
            </label>
            <div className="flex space-x-2">
              <select
                className="flex-1 bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-slate-300 focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/50 outline-none transition-all font-mono"
                value={localSettings.tp_type}
                onChange={(e) => updateLocalSetting("tp_type", e.target.value)}
              >
                <option value="fixed">Fixed $</option>
                <option value="equity">Equity %</option>
                <option value="balance">Balance %</option>
              </select>
              <NumberInput
                min={0}
                step="0.01"
                className="flex-1 bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-slate-300 focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/50 outline-none transition-all font-mono"
                value={localSettings.tp_value}
                onChange={(val) => updateLocalSetting("tp_value", val)}
              />
            </div>
          </div>

          {/* SL Block */}
          <div className="bg-rose-500/5 border border-rose-500/10 rounded-lg p-3">
            <label className="block text-xs text-rose-500 uppercase mb-2 font-bold">
              Stop Loss
            </label>
            <div className="flex space-x-2">
              <select
                className="flex-1 bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-slate-300 focus:border-rose-500/50 focus:ring-1 focus:ring-rose-500/50 outline-none transition-all font-mono"
                value={localSettings.sl_type}
                onChange={(e) => updateLocalSetting("sl_type", e.target.value)}
              >
                <option value="fixed">Fixed $</option>
                <option value="equity">Equity %</option>
                <option value="balance">Balance %</option>
              </select>
              <NumberInput
                min={0}
                step="0.01"
                className="flex-1 bg-slate-800 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-slate-300 focus:border-rose-500/50 focus:ring-1 focus:ring-rose-500/50 outline-none transition-all font-mono"
                value={localSettings.sl_value}
                onChange={(val) => updateLocalSetting("sl_value", val)}
              />
            </div>
          </div>
        </div>

        <div className="flex justify-between items-center">
          <div className="flex items-center space-x-6">
            <label className="flex items-center space-x-2 cursor-pointer">
              <span className="text-sm text-slate-400 font-medium">ON</span>
              <Toggle
                checked={settings?.is_on || false}
                onChange={(v) => handleControl(v, settings?.is_cyclic || false)}
                activeColorClass={activeToggleClass}
              />
            </label>
            <label className="flex items-center space-x-2 cursor-pointer">
              <span className="text-sm text-slate-400 font-medium">CYCLIC</span>
              <Toggle
                checked={settings?.is_cyclic || false}
                onChange={(v) => handleControl(settings?.is_on || false, v)}
                activeColorClass={activeToggleClass}
              />
            </label>
          </div>
          <div className="flex items-center space-x-2">
            <button
              onClick={handleResync}
              className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-md font-medium uppercase tracking-wider text-sm transition-colors flex items-center gap-2"
              title="Sync with Server"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
            <button
              onClick={handleApplySettings}
              className={`px-6 py-2 rounded-md text-sm font-bold transition-all ${btnClass}`}
            >
              APPLY SETTINGS
            </button>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-hidden flex flex-col min-h-0">
        <GridTable
          side={side}
          rows={localSettings.rows}
          isOn={localSettings.is_on}
          onChange={(index, field, value) => {
            setLocalSettings((prev) => {
              if (!prev) return prev;
              const newRows = [...prev.rows];
              const rIdx = newRows.findIndex((r) => r.index === index);
              if (rIdx > -1) {
                newRows[rIdx] = { ...newRows[rIdx], [field]: value };
              }
              return { ...prev, rows: newRows };
            });
          }}
          onAddRow={handleAddRow}
          onRemoveRow={handleRemoveRow}
        />
      </div>

      {showConfirmOff && (
        <div className="absolute inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-8">
          <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 max-w-sm shadow-2xl">
            <h2 className="text-xl font-bold text-white mb-4">
              Turn Off Grid?
            </h2>
            <p className="text-slate-300 mb-6 text-sm">
              Turning off will immediately close all open trades for this grid.
              Proceed?
            </p>
            <div className="flex justify-end space-x-3">
              <button
                onClick={cancelTurnOff}
                className="px-4 py-2 rounded-md text-sm font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={confirmTurnOff}
                className="px-4 py-2 rounded-md text-sm font-medium bg-rose-600 text-white hover:bg-rose-500 transition-colors"
              >
                Turn Off
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
