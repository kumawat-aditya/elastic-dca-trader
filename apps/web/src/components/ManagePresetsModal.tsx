import React, { useState } from "react";
import { Preset } from "../types";
import { X, Plus, Trash2, Edit2 } from "lucide-react";
import { toast } from "sonner";
import * as api from "../services/api";

interface Props {
  presets: Preset[];
  onClose: () => void;
  onRefresh: () => void;
  onEditPreset: (preset: Preset) => void;
  onCreatePreset: () => void;
}

export default function ManagePresetsModal({
  presets,
  onClose,
  onRefresh,
  onEditPreset,
  onCreatePreset,
}: Props) {
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<Preset | null>(null);

  const handleDelete = async (preset: Preset) => {
    setDeletingId(preset.id);
    try {
      const res = await api.deletePreset(preset.id);
      if (!res.ok) throw new Error("Failed to delete preset");
      toast.success(`Preset '${preset.name}' deleted.`);
      onRefresh();
    } catch (e) {
      toast.error("Failed to delete preset.");
    } finally {
      setDeletingId(null);
      setConfirmDelete(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl w-full max-w-md flex flex-col max-h-[90vh] overflow-hidden relative">
        <div className="flex justify-between items-center p-5 border-b border-slate-800/50 bg-slate-950/50">
          <h2 className="text-xl font-bold text-slate-100 tracking-tight">
            Manage Presets
          </h2>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-300 transition-colors p-1 rounded-md hover:bg-slate-800"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-auto p-5 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-slate-900">
          {presets.length === 0 ? (
            <div className="text-center text-slate-500 py-8">
              No presets found.
            </div>
          ) : (
            <div className="space-y-3">
              {presets.map((preset) => (
                <div
                  key={preset.id}
                  className="flex items-center justify-between bg-slate-950 border border-slate-800 rounded-xl p-4 hover:border-slate-700 transition-colors"
                >
                  <div
                    className="flex-1 min-w-0 mr-4 cursor-pointer"
                    onClick={() => onEditPreset(preset)}
                  >
                    <h3 className="text-slate-200 font-medium truncate">
                      {preset.name}
                    </h3>
                    <p className="text-slate-500 text-xs mt-1">
                      {preset.rows.length} rows
                    </p>
                  </div>
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={() => onEditPreset(preset)}
                      className="p-2 text-slate-400 hover:text-indigo-400 hover:bg-indigo-500/10 rounded-lg transition-colors"
                      title="Edit Preset"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => setConfirmDelete(preset)}
                      disabled={deletingId === preset.id}
                      className="p-2 text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 rounded-lg transition-colors disabled:opacity-50"
                      title="Delete Preset"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="p-5 border-t border-slate-800/50 bg-slate-950/50">
          <button
            onClick={onCreatePreset}
            className="w-full bg-indigo-600 hover:bg-indigo-500 text-white px-6 py-3 rounded-xl font-bold transition-all shadow-lg shadow-indigo-900/20 active:scale-[0.98] flex items-center justify-center space-x-2"
          >
            <Plus className="w-5 h-5" />
            <span>Add Preset</span>
          </button>
        </div>

        {confirmDelete && (
          <div className="absolute inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-6">
            <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 max-w-sm shadow-2xl w-full">
              <h2 className="text-xl font-bold text-white mb-4">
                Delete Preset?
              </h2>
              <p className="text-slate-300 mb-6 text-sm">
                Are you sure you want to delete the preset "{confirmDelete.name}
                "? This action cannot be undone.
              </p>
              <div className="flex justify-end space-x-3">
                <button
                  onClick={() => setConfirmDelete(null)}
                  className="px-4 py-2 rounded-md text-sm font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => handleDelete(confirmDelete)}
                  disabled={deletingId === confirmDelete.id}
                  className="px-4 py-2 rounded-md text-sm font-medium bg-rose-600 text-white hover:bg-rose-500 transition-colors flex items-center justify-center disabled:opacity-50"
                >
                  {deletingId === confirmDelete.id ? "Deleting..." : "Delete"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
