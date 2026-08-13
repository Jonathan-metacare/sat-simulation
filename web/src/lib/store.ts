import { create } from "zustand";

import type { MissionDetail, ScenarioRecord } from "./types";

export type Locale = "zh" | "en";
export type ThemeMode = "dark" | "light";

interface DashboardState {
  scenario?: ScenarioRecord;
  mission?: MissionDetail;
  locale: Locale;
  theme: ThemeMode;
  setScenario: (value: ScenarioRecord) => void;
  setMission: (value?: MissionDetail) => void;
  setLocale: (value: Locale) => void;
  setTheme: (value: ThemeMode) => void;
}

function lastSequence(mission?: MissionDetail) {
  return mission?.events.reduce((maximum, event) => Math.max(maximum, event.sequence), 0) ?? 0;
}

function isOlderMission(current: MissionDetail, incoming: MissionDetail) {
  const currentSequence = lastSequence(current);
  const incomingSequence = lastSequence(incoming);
  if (incomingSequence !== currentSequence) return incomingSequence < currentSequence;
  return new Date(incoming.updated_at).getTime() < new Date(current.updated_at).getTime();
}

export const useDashboardStore = create<DashboardState>((set) => ({
  locale: "zh",
  theme: "dark",
  setScenario: (scenario) => set({ scenario }),
  setMission: (mission) => set((current) => {
    if (
      mission
      && current.mission?.command.id === mission.command.id
      && isOlderMission(current.mission, mission)
    ) {
      return current;
    }
    return { mission };
  }),
  setLocale: (locale) => set({ locale }),
  setTheme: (theme) => set({ theme }),
}));
