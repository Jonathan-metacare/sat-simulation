import { create } from "zustand";

import type { MissionDetail, ScenarioRecord } from "./types";

interface DashboardState {
  scenario?: ScenarioRecord;
  mission?: MissionDetail;
  setScenario: (value: ScenarioRecord) => void;
  setMission: (value?: MissionDetail) => void;
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
}));
