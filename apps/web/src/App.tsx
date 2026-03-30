import React, { useEffect, useState, useRef, useCallback } from "react";
import { SystemState, Side, Preset } from "./types";
import TopBar from "./components/TopBar";
import SidePanel from "./components/SidePanel";
import CreatePresetModal from "./components/CreatePresetModal";
import ManagePresetsModal from "./components/ManagePresetsModal";
import * as api from "./services/api";
import { Toaster, toast } from "sonner";

const WS_URL =
  import.meta.env.VITE_WS_URL || "ws://localhost:8000/api/v1/ui/ws";

export default function App() {
  const [systemState, setSystemState] = useState<SystemState | null>(null);
  const [serverConnected, setServerConnected] = useState(false);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [showManageModal, setShowManageModal] = useState(false);
  const [showPresetModal, setShowPresetModal] = useState(false);
  const [presetToEdit, setPresetToEdit] = useState<Preset | null>(null);

  const wsRef = useRef<WebSocket | null>(null);

  const fetchPresets = useCallback(async () => {
    try {
      const data = await api.getPresets();
      setPresets(data);
    } catch (e) {
      console.error("Failed to fetch presets", e);
    }
  }, []);

  useEffect(() => {
    const connectWs = () => {
      const ws = new WebSocket(WS_URL);
      ws.onopen = () => setServerConnected(true);
      ws.onclose = () => {
        setServerConnected(false);
        setTimeout(connectWs, 3000);
      };
      ws.onmessage = (e) => {
        try {
          const data: SystemState = JSON.parse(e.data);
          setSystemState(data);
        } catch (err) {
          console.error("Failed to parse WS message", err);
        }
      };
      wsRef.current = ws;
    };
    connectWs();

    fetchPresets();

    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, [fetchPresets]);

  const handleSavePreset = async (
    name: string,
    rows: any[],
    presetId?: string,
  ) => {
    let res;
    if (presetId) {
      res = await api.updatePreset(presetId, name, rows);
    } else {
      res = await api.createPreset(name, rows);
    }

    if (!res.ok) {
      const errorData = await res.json().catch(() => null);
      throw new Error(errorData?.detail || "API rejected the request");
    }
    const updated = await api.getPresets();
    setPresets(updated);
  };

  const openCreatePreset = () => {
    setPresetToEdit(null);
    setShowManageModal(false);
    setShowPresetModal(true);
  };

  const openEditPreset = (preset: Preset) => {
    setPresetToEdit(preset);
    setShowManageModal(false);
    setShowPresetModal(true);
  };

  const closePresetModal = () => {
    setShowPresetModal(false);
    setPresetToEdit(null);
    setShowManageModal(true); // Go back to manage modal
  };

  return (
    <div className="h-screen bg-slate-950 text-slate-300 font-sans flex flex-col overflow-hidden selection:bg-indigo-500/30">
      <Toaster
        theme="dark"
        position="top-center"
        toastOptions={{
          className: "bg-slate-900 border border-slate-800 text-slate-200",
        }}
      />
      <TopBar
        state={systemState}
        serverConnected={serverConnected}
        eaConnected={systemState?.ea_connected || false}
        onCreatePreset={() => setShowManageModal(true)}
      />

      <div className="flex-1 flex flex-col md:flex-row overflow-hidden min-h-0">
        <div className="flex-1 border-r border-slate-800/50 relative overflow-hidden flex flex-col bg-slate-900/40 min-h-0">
          <SidePanel
            side="buy"
            state={systemState}
            presets={presets}
            onRefreshPresets={fetchPresets}
          />
        </div>
        <div className="flex-1 relative overflow-hidden flex flex-col bg-slate-900/40 min-h-0">
          <SidePanel
            side="sell"
            state={systemState}
            presets={presets}
            onRefreshPresets={fetchPresets}
          />
        </div>
      </div>

      {showManageModal && (
        <ManagePresetsModal
          presets={presets}
          onClose={() => setShowManageModal(false)}
          onRefresh={fetchPresets}
          onEditPreset={openEditPreset}
          onCreatePreset={openCreatePreset}
        />
      )}

      {showPresetModal && (
        <CreatePresetModal
          presetToEdit={presetToEdit}
          onClose={closePresetModal}
          onSave={handleSavePreset}
        />
      )}
    </div>
  );
}
