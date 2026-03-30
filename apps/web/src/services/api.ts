import { GridSettings, Preset, Side } from "../types";

const API_BASE =
  import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1/ui";

export const controlSide = async (
  side: Side,
  is_on: boolean,
  is_cyclic: boolean,
) => {
  return fetch(`${API_BASE}/control/${side}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_on, is_cyclic }),
  });
};

export const ackAlert = async (side: Side, index: number) => {
  return fetch(`${API_BASE}/ack-alert/${side}/${index}`, {
    method: "POST",
  });
};

export const updateSettings = async (side: Side, settings: GridSettings) => {
  return fetch(`${API_BASE}/settings/${side}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
};

export const getPresets = async (): Promise<Preset[]> => {
  try {
    const res = await fetch(`${API_BASE}/presets`);
    if (!res.ok) return [];
    return res.json();
  } catch (e) {
    console.error("Failed to fetch presets", e);
    return [];
  }
};

export const createPreset = async (name: string, rows: any[]) => {
  return fetch(`${API_BASE}/presets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, rows }),
  });
};

export const loadPreset = async (presetId: string, side: Side) => {
  return fetch(`${API_BASE}/presets/${presetId}/load/${side}`, {
    method: "POST",
  });
};

export const updatePreset = async (
  presetId: string,
  name: string,
  rows: any[],
) => {
  return fetch(`${API_BASE}/presets/${presetId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, rows }),
  });
};

export const deletePreset = async (presetId: string) => {
  return fetch(`${API_BASE}/presets/${presetId}`, {
    method: "DELETE",
  });
};
