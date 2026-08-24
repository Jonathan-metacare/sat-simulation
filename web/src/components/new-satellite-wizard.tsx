"use client";

import { useState } from "react";
import { LoaderCircle, Upload, X } from "lucide-react";

import { api } from "~/lib/api";
import { translate } from "~/lib/i18n";
import type { ScenarioRecord } from "~/lib/types";
import type { Locale } from "~/lib/store";

type Props = {
  locale: Locale;
  onClose(): void;
  onCompleted(scenario: ScenarioRecord): Promise<void> | void;
};

const inputClass = "mt-1.5 w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-300/45";

export function NewSatelliteWizard({ locale, onClose, onCompleted }: Props) {
  const t = (key: Parameters<typeof translate>[1]) => translate(locale, key);
  const [step, setStep] = useState(0);
  const [satelliteName, setSatelliteName] = useState("");
  const [tleLine1, setTleLine1] = useState("");
  const [tleLine2, setTleLine2] = useState("");
  const [stationName, setStationName] = useState("");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [altitude, setAltitude] = useState("0");
  const [file, setFile] = useState<File>();
  const [centerLatitude, setCenterLatitude] = useState("");
  const [centerLongitude, setCenterLongitude] = useState("");
  const [pixelSize, setPixelSize] = useState("0.0001");
  const [crs, setCrs] = useState("EPSG:4326");
  const [createdScenario, setCreatedScenario] = useState<ScenarioRecord>();
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string>();

  const isRaster = Boolean(file?.name.toLowerCase().match(/\.(tif|tiff)$/));
  const validSatellite = Boolean(satelliteName.trim() && tleLine1.trim() && tleLine2.trim());
  const validStation = Boolean(
    stationName.trim() && [latitude, longitude, altitude].every((value) => Number.isFinite(Number(value)))
    && Number(latitude) >= -90 && Number(latitude) <= 90
    && Number(longitude) >= -180 && Number(longitude) <= 180,
  );
  const validScene = Boolean(file && (isRaster || (
    [centerLatitude, centerLongitude, pixelSize].every((value) => Number.isFinite(Number(value)))
    && Number(centerLatitude) >= -90 && Number(centerLatitude) <= 90
    && Number(centerLongitude) >= -180 && Number(centerLongitude) <= 180
    && Number(pixelSize) > 0 && crs.trim()
  )));

  const createAndImport = async () => {
    if (!validScene) return;
    setWorking(true); setError(undefined);
    try {
      let scenario = createdScenario;
      if (!scenario) {
        scenario = await api.createSatellite({
          satellite_name: satelliteName.trim(), tle_line1: tleLine1.trim(), tle_line2: tleLine2.trim(),
          ground_station_name: stationName.trim(), latitude: Number(latitude), longitude: Number(longitude), altitude_m: Number(altitude),
        });
        setCreatedScenario(scenario);
      }
      const geo = isRaster ? undefined : {
        centerLatitude: Number(centerLatitude), centerLongitude: Number(centerLongitude), pixelSize: Number(pixelSize), crs: crs.trim(),
      };
      await api.validateScene(file!, scenario.config.scene_id, geo);
      await api.importScene(file!, scenario.config.scene_id, scenario.config.id, geo);
      const records = await api.scenarios();
      const readyScenario = records.find((item) => item.config.id === scenario.config.id);
      if (!readyScenario?.config.scene_ready) throw new Error("Scene import did not mark the satellite ready.");
      await onCompleted(readyScenario);
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally { setWorking(false); }
  };

  const steps = [t("satellite.stepSatellite"), t("satellite.stepStation"), t("satellite.stepScene")];
  return <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="new-satellite-title">
    <section className="panel w-full max-w-md rounded-2xl p-5 shadow-2xl shadow-cyan-950/50">
      <div className="flex items-start justify-between gap-4"><div><h2 id="new-satellite-title" className="text-lg font-medium text-slate-50">{t("satellite.createTitle")}</h2><p className="mt-1 text-xs leading-5 text-slate-500">{t("satellite.createDescription")}</p></div><button onClick={onClose} disabled={working} className="rounded-lg border border-white/10 p-2 text-slate-400 hover:text-cyan-100"><X size={16} /></button></div>
      <div className="mt-5 grid grid-cols-3 gap-2">{steps.map((label, index) => <div key={label} className={`rounded-lg border px-2 py-2 text-center text-[10px] ${index === step ? "border-cyan-300/45 bg-cyan-300/10 text-cyan-100" : index < step ? "border-emerald-300/25 text-emerald-200" : "border-white/[.07] text-slate-500"}`}>{index + 1}. {label}</div>)}</div>
      {step === 0 && <div className="mt-5 space-y-4"><Field label={t("satellite.name")} value={satelliteName} onChange={setSatelliteName} /><Field label={t("satellite.tleLine1")} value={tleLine1} onChange={setTleLine1} /><Field label={t("satellite.tleLine2")} value={tleLine2} onChange={setTleLine2} /></div>}
      {step === 1 && <div className="mt-5 grid gap-4 sm:grid-cols-2"><div className="sm:col-span-2"><Field label={t("satellite.stationName")} value={stationName} onChange={setStationName} /></div><Field label={t("satellite.latitude")} value={latitude} onChange={setLatitude} type="number" /><Field label={t("satellite.longitude")} value={longitude} onChange={setLongitude} type="number" /><Field label={t("satellite.altitude")} value={altitude} onChange={setAltitude} type="number" /></div>}
      {step === 2 && <div className="mt-5 space-y-4"><div className="rounded-xl border border-emerald-300/25 bg-emerald-300/[.06] p-4"><div className="flex items-center gap-2 text-sm text-cyan-100"><Upload size={15} />{t("satellite.scene")}</div><p className="mt-2 text-xs leading-5 text-slate-500">{t("satellite.sceneHint")}</p><input className="mt-4 block w-full text-xs text-slate-300" type="file" accept=".tif,.tiff,.png,.jpg,.jpeg,image/tiff,image/png,image/jpeg" onChange={(event) => setFile(event.target.files?.[0])} /></div>{file && !isRaster && <div className="grid gap-4 sm:grid-cols-2"><Field label={t("satellite.centerLatitude")} value={centerLatitude} onChange={setCenterLatitude} type="number" /><Field label={t("satellite.centerLongitude")} value={centerLongitude} onChange={setCenterLongitude} type="number" /><Field label={t("satellite.pixelSize")} value={pixelSize} onChange={setPixelSize} type="number" /><Field label="CRS" value={crs} onChange={setCrs} /></div>}{createdScenario && <p className="rounded-lg border border-orange-300/25 bg-orange-300/10 px-3 py-2 text-xs text-orange-100">{t("satellite.sceneRetry")}</p>}</div>}
      {error && <p className="mt-4 rounded-lg border border-orange-300/25 bg-orange-300/10 px-3 py-2 text-xs text-orange-200">{error}</p>}
      <div className="mt-6 flex justify-end gap-2">{step > 0 && !createdScenario && <button disabled={working} onClick={() => setStep((current) => current - 1)} className="rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-300">{t("satellite.previous")}</button>}{step < 2 ? <button disabled={working || (step === 0 ? !validSatellite : !validStation)} onClick={() => setStep((current) => current + 1)} className="rounded-lg border border-cyan-300/50 bg-cyan-300/15 px-3 py-2 text-xs text-cyan-100 disabled:opacity-40">{t("satellite.next")}</button> : <button disabled={working || !validScene} onClick={() => void createAndImport()} className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-300/50 bg-cyan-300/15 px-3 py-2 text-xs text-cyan-100 disabled:opacity-40">{working && <LoaderCircle size={14} className="animate-spin" />}{working ? t("satellite.creating") : t("satellite.create")}</button>}</div>
    </section>
  </div>;
}

function Field({ label, value, onChange, type = "text" }: { label: string; value: string; onChange(value: string): void; type?: string }) {
  return <label className="block text-xs text-slate-400">{label}<input type={type} value={value} onChange={(event) => onChange(event.target.value)} className={inputClass} /></label>;
}
