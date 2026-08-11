import { create } from "zustand";
import type { MissionDetail, ScenarioRecord } from "./types";

interface DashboardState { scenario?:ScenarioRecord; mission?:MissionDetail; setScenario:(value:ScenarioRecord)=>void; setMission:(value?:MissionDetail)=>void; }
export const useDashboardStore=create<DashboardState>((set)=>({setScenario:(scenario)=>set({scenario}),setMission:(mission)=>set({mission})}));

