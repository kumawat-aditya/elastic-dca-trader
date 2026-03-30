import React, { useState, useEffect } from "react";
import { GridRow, Preset } from "../types";
import { X, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { NumberInput } from "./NumberInput";

interface Props {
  presetToEdit?: Preset | null;
  onClose: () => void;
  onSave: (name: string, rows: GridRow[], presetId?: string) => Promise<void>;
}

export default function CreatePresetModal({
  presetToEdit,
  onClose,
  onSave,
}: Props) {
  const [name, setName] = useState("");
  const [rows, setRows] = useState<GridRow[]>([
    { index: 0, gap: 10, lots: 0.01, alert: false },
  ]);

  useEffect(() => {
    if (presetToEdit) {
      setName(presetToEdit.name);
      setRows(JSON.parse(JSON.stringify(presetToEdit.rows)));
    }
  }, [presetToEdit]);

  const handleAddRow = () => {
    setRows((prev) => [
      ...prev,
      {
        index: prev.length > 0 ? Math.max(...prev.map((r) => r.index)) + 1 : 0,
        gap: 10,
        lots: 0.01,
        alert: false,
      },
    ]);
  };

  const handleRemoveRow = (idx: number) => {
    setRows((prev) =>
      prev.filter((_, i) => i !== idx).map((r, i) => ({ ...r, index: i })),
    );
  };

  const handleChange = (idx: number, field: keyof GridRow, value: any) => {
    setRows((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: value };
      return next;
    });
  };

  const handleSave = async () => {
    if (!name.trim()) {
      toast.error("Please enter a preset name.");
      return;
    }

    for (const row of rows) {
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
      await onSave(name, rows, presetToEdit?.id);
      toast.success(
        `Preset "${name}" ${presetToEdit ? "updated" : "created"} successfully.`,
      );
      onClose();
    } catch (error: any) {
      toast.error(
        error.message || "Failed to save preset. Name might already exist.",
      );
      console.error(error);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl w-full max-w-2xl flex flex-col max-h-[90vh] overflow-hidden">
        <div className="flex justify-between items-center p-5 border-b border-slate-800/50 bg-slate-950/50">
          <h2 className="text-xl font-bold text-slate-100 tracking-tight">
            {presetToEdit ? "Update Preset" : "Create Preset"}
          </h2>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-300 transition-colors p-1 rounded-md hover:bg-slate-800"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 border-b border-slate-800/50">
          <label className="block text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">
            Preset Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-slate-100 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none transition-all shadow-inner"
            placeholder="e.g. Aggressive Scalper"
          />
        </div>

        <div className="flex-1 overflow-auto p-5 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-slate-900">
          <table className="w-full text-left text-sm whitespace-nowrap mb-4">
            <thead className="text-xs text-slate-500 uppercase border-b border-slate-800/50">
              <tr>
                <th className="pb-3 font-medium px-2">Idx</th>
                <th className="pb-3 font-medium px-2">Gap</th>
                <th className="pb-3 font-medium px-2">Lots</th>
                <th className="pb-3 font-medium text-center px-2">Alert</th>
                <th className="pb-3 font-medium px-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/30">
              {rows.map((row, i) => (
                <tr key={i} className="hover:bg-slate-800/20 transition-colors">
                  <td className="py-3 px-2 font-mono text-slate-500">
                    {row.index}
                  </td>
                  <td className="py-3 px-2">
                    <NumberInput
                      min={0}
                      value={row.gap}
                      onChange={(val) => handleChange(i, "gap", val ?? 0)}
                      className="w-24 bg-slate-950 border border-slate-800 rounded-md px-2 py-1.5 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 font-mono transition-all shadow-inner"
                    />
                  </td>
                  <td className="py-3 px-2">
                    <NumberInput
                      min={0.01}
                      step="0.01"
                      value={row.lots}
                      onChange={(val) => handleChange(i, "lots", val ?? 0.01)}
                      className="w-24 bg-slate-950 border border-slate-800 rounded-md px-2 py-1.5 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 font-mono transition-all shadow-inner"
                    />
                  </td>
                  <td className="py-3 px-2 text-center">
                    <input
                      type="checkbox"
                      checked={row.alert}
                      onChange={(e) =>
                        handleChange(i, "alert", e.target.checked)
                      }
                      className="form-checkbox h-4 w-4 text-indigo-500 bg-slate-900 border-slate-700 rounded cursor-pointer focus:ring-indigo-500/50 transition-all"
                    />
                  </td>
                  <td className="py-3 px-2 text-right">
                    <button
                      onClick={() => handleRemoveRow(i)}
                      className="text-slate-500 hover:text-rose-400 p-1.5 rounded-md hover:bg-rose-500/10 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <button
            onClick={handleAddRow}
            className="w-full py-3 border border-dashed border-slate-700 rounded-xl text-slate-400 hover:text-slate-200 hover:border-slate-500 hover:bg-slate-800/50 flex items-center justify-center space-x-2 transition-all"
          >
            <Plus className="w-4 h-4" />
            <span className="text-sm font-medium uppercase tracking-wider">
              Add Row
            </span>
          </button>
        </div>

        <div className="p-5 border-t border-slate-800/50 bg-slate-950/50 flex justify-end space-x-3">
          <button
            onClick={onClose}
            className="px-6 py-2.5 rounded-xl font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="bg-indigo-600 hover:bg-indigo-500 text-white px-6 py-2.5 rounded-xl font-bold transition-all shadow-lg shadow-indigo-900/20 active:scale-[0.98]"
          >
            {presetToEdit ? "Update Preset" : "Save Preset"}
          </button>
        </div>
      </div>
    </div>
  );
}
