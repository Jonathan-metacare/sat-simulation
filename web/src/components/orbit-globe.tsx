"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type * as Cesium from "cesium";

import { translate } from "~/lib/i18n";
import type { Locale } from "~/lib/store";
import type { OrbitSample, OrbitTrack } from "~/lib/types";
import { desktopBridge } from "~/lib/desktop";

interface OrbitGlobeProps {
  track?: OrbitTrack;
  station: { name: string; latitude: number; longitude: number; altitudeM: number };
  target?: { name: string; latitude: number; longitude: number };
  locale?: Locale;
}

type SceneInputs = OrbitGlobeProps;

function loadCesium(): Promise<typeof Cesium> {
  // Keep Cesium outside Next's module graph.  CesiumUnminified/Cesium.js is a
  // classic browser script, not an ES module; appending it as a script avoids
  // both Next's WASM minification issue and the bare @cesium/engine imports
  // present in Cesium's Source tree.
  if (window.Cesium) return Promise.resolve(window.Cesium);
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-sat-sim-cesium="true"]');
    if (existing) {
      existing.addEventListener("load", () => window.Cesium ? resolve(window.Cesium) : reject(new Error("Cesium global was not initialized")), { once: true });
      existing.addEventListener("error", () => reject(new Error("Cesium script failed to load")), { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = "/cesium/Cesium.js";
    script.async = true;
    script.dataset.satSimCesium = "true";
    script.onload = () => window.Cesium ? resolve(window.Cesium) : reject(new Error("Cesium global was not initialized"));
    script.onerror = () => reject(new Error("Cesium script failed to load"));
    document.head.appendChild(script);
  });
}

function cartesian(C: typeof Cesium, sample: OrbitSample) {
  return C.Cartesian3.fromDegrees(sample.longitude, sample.latitude, sample.altitude_km * 1000);
}

function addGraticule(viewer: Cesium.Viewer, C: typeof Cesium) {
  const material = C.Color.fromCssColorString("#4f91a5").withAlpha(0.13);
  for (let latitude = -60; latitude <= 60; latitude += 30) {
    viewer.entities.add({
      polyline: {
        positions: Array.from({ length: 73 }, (_, index) =>
          C.Cartesian3.fromDegrees(-180 + index * 5, latitude, 1000)
        ),
        width: 1,
        material,
      },
    });
  }
  for (let longitude = -180; longitude < 180; longitude += 30) {
    viewer.entities.add({
      polyline: {
        positions: Array.from({ length: 37 }, (_, index) =>
          C.Cartesian3.fromDegrees(longitude, -90 + index * 5, 1000)
        ),
        width: 1,
        material,
      },
    });
  }
}

function visibleSegments(samples: OrbitSample[]) {
  const segments: OrbitSample[][] = [];
  let active: OrbitSample[] = [];
  for (const sample of samples) {
    if (sample.visible) active.push(sample);
    else if (active.length) {
      segments.push(active);
      active = [];
    }
  }
  if (active.length) segments.push(active);
  return segments;
}

function drawScene(
  viewer: Cesium.Viewer,
  C: typeof Cesium,
  inputs: SceneInputs,
  setInitialCamera: boolean,
) {
  viewer.entities.removeAll();
  addGraticule(viewer, C);

  const { station, target, track } = inputs;
  const stationPosition = C.Cartesian3.fromDegrees(
    station.longitude,
    station.latitude,
    station.altitudeM,
  );
  viewer.entities.add({
    name: station.name,
    position: stationPosition,
    point: {
      pixelSize: 10,
      color: C.Color.fromCssColorString("#fb923c"),
      outlineColor: C.Color.WHITE,
      outlineWidth: 1,
    },
    label: {
      text: station.name,
      font: "12px ui-monospace, monospace",
      pixelOffset: new C.Cartesian2(0, -20),
      fillColor: C.Color.fromCssColorString("#fdba74"),
      showBackground: true,
      backgroundColor: C.Color.fromCssColorString("#07111f").withAlpha(0.82),
    },
  });

  if (track) {
    viewer.entities.add({
      position: stationPosition,
      ellipse: {
        semiMajorAxis: track.visibility_radius_m,
        semiMinorAxis: track.visibility_radius_m,
        material: C.Color.fromCssColorString("#fb923c").withAlpha(0.07),
        outline: true,
        outlineColor: C.Color.fromCssColorString("#fb923c").withAlpha(0.45),
      },
    });
    viewer.entities.add({
      polyline: {
        positions: track.history.map((sample) => cartesian(C, sample)),
        width: 2,
        material: C.Color.fromCssColorString("#22d3ee").withAlpha(0.42),
      },
    });
    viewer.entities.add({
      polyline: {
        positions: [track.current, ...track.forecast].map((sample) => cartesian(C, sample)),
        width: 2,
        material: new C.PolylineDashMaterialProperty({
          color: C.Color.fromCssColorString("#67e8f9").withAlpha(0.78),
          dashLength: 14,
        }),
      },
    });
    for (const segment of visibleSegments(track.forecast)) {
      if (segment.length < 2) continue;
      viewer.entities.add({
        polyline: {
          positions: segment.map((sample) => cartesian(C, sample)),
          width: 4,
          material: C.Color.fromCssColorString("#4ade80").withAlpha(0.9),
        },
      });
    }

    const satellitePosition = cartesian(C, track.current);
    viewer.entities.add({
      name: track.satellite_name,
      position: satellitePosition,
      point: {
        pixelSize: 12,
        color: C.Color.fromCssColorString("#22d3ee"),
        outlineColor: C.Color.WHITE,
        outlineWidth: 2,
      },
      label: {
        text: track.satellite_name,
        font: "12px ui-monospace, monospace",
        pixelOffset: new C.Cartesian2(0, -22),
        fillColor: C.Color.fromCssColorString("#a5f3fc"),
        showBackground: true,
        backgroundColor: C.Color.fromCssColorString("#07111f").withAlpha(0.82),
      },
    });
    viewer.entities.add({
      polyline: {
        positions: [
          C.Cartesian3.fromDegrees(track.current.longitude, track.current.latitude, 0),
          satellitePosition,
        ],
        width: 1,
        material: C.Color.fromCssColorString("#22d3ee").withAlpha(0.28),
      },
    });
    if (track.current.visible) {
      viewer.entities.add({
        polyline: {
          positions: [stationPosition, satellitePosition],
          width: 2,
          material: new C.PolylineGlowMaterialProperty({
            color: C.Color.fromCssColorString("#4ade80"),
            glowPower: 0.18,
          }),
        },
      });
    }
  }

  if (target) {
    const targetPosition = C.Cartesian3.fromDegrees(target.longitude, target.latitude, 20);
    viewer.entities.add({
      name: target.name,
      position: targetPosition,
      point: {
        pixelSize: 7,
        color: C.Color.fromCssColorString("#facc15"),
        outlineColor: C.Color.fromCssColorString("#fef9c3"),
        outlineWidth: 1,
      },
      ellipse: {
        semiMajorAxis: 55_000,
        semiMinorAxis: 55_000,
        material: C.Color.fromCssColorString("#facc15").withAlpha(0.08),
        outline: true,
        outlineColor: C.Color.fromCssColorString("#facc15").withAlpha(0.55),
      },
      label: {
        text: `${translate(inputs.locale ?? "zh", "orbit.target")} · ${target.name}`,
        font: "11px sans-serif",
        pixelOffset: new C.Cartesian2(0, 20),
        fillColor: C.Color.fromCssColorString("#fde68a"),
      },
    });
  }

  if (setInitialCamera) {
    viewer.camera.setView({
      destination: C.Cartesian3.fromDegrees(station.longitude, station.latitude, 12_000_000),
    });
  }
}

function formatDuration(milliseconds: number) {
  const totalMinutes = Math.max(0, Math.round(milliseconds / 60_000));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

export function OrbitGlobe({ track, station, target, locale = "zh" }: OrbitGlobeProps) {
  const element = useRef<HTMLDivElement>(null);
  const viewer = useRef<Cesium.Viewer | undefined>(undefined);
  const cesium = useRef<typeof Cesium | undefined>(undefined);
  const [desktopIonToken, setDesktopIonToken] = useState<string>();
  const [renderError, setRenderError] = useState(false);
  const latestInputs = useRef<SceneInputs>({ track, station, target });
  latestInputs.current = { track, station, target, locale };

  useEffect(() => {
    const bridge = desktopBridge();
    if (bridge) void bridge.getSettings().then((saved) => setDesktopIonToken(saved.cesiumIonToken));
  }, []);

  useEffect(() => {
    if (!element.current) return;
    let disposed = false;
    void (async () => {
      try {
        window.CESIUM_BASE_URL = process.env.NEXT_PUBLIC_CESIUM_BASE_URL ?? "/cesium/";
        const C = await loadCesium();
        if (disposed || !element.current) return;
        const ionAccessToken = desktopIonToken || process.env.NEXT_PUBLIC_CESIUM_ION_ACCESS_TOKEN;
        if (ionAccessToken) C.Ion.defaultAccessToken = ionAccessToken;
        const instance = new C.Viewer(element.current, {
        animation: false,
        timeline: false,
        geocoder: false,
        homeButton: false,
        sceneModePicker: false,
        navigationHelpButton: false,
        baseLayerPicker: false,
        fullscreenButton: false,
        infoBox: false,
        selectionIndicator: false,
        // Asset 2 is Cesium Ion World Imagery.  In offline mode the built-in
        // GridImageryProvider is entirely local: it deliberately makes the
        // deterministic simulation globe visible without a network or token.
        baseLayer: ionAccessToken
          ? C.ImageryLayer.fromProviderAsync(C.IonImageryProvider.fromAssetId(2))
          : new C.ImageryLayer(new C.GridImageryProvider({
            cells: 12,
            color: C.Color.fromCssColorString("#1e6476").withAlpha(0.72),
            glowColor: C.Color.fromCssColorString("#0b2c39").withAlpha(0.45),
            backgroundColor: C.Color.fromCssColorString("#112f3d").withAlpha(1),
          })),
        terrain: ionAccessToken ? C.Terrain.fromWorldTerrain() : undefined,
        skyBox: false,
      });
        instance.scene.globe.show = true;
        instance.scene.globe.baseColor = C.Color.fromCssColorString(ionAccessToken ? "#183c4d" : "#112f3d");
        instance.scene.backgroundColor = C.Color.fromCssColorString("#02080d");
        instance.scene.globe.enableLighting = false;
        viewer.current = instance;
        cesium.current = C;
        setRenderError(false);
        drawScene(instance, C, latestInputs.current, true);
      } catch (error) {
        if (!disposed) {
          console.error("Cesium local globe initialization failed", error);
          setRenderError(true);
        }
      }
    })();
    return () => {
      disposed = true;
      viewer.current?.destroy();
      viewer.current = undefined;
      cesium.current = undefined;
    };
  }, [desktopIonToken]);

  useEffect(() => {
    if (viewer.current && cesium.current) {
      drawScene(viewer.current, cesium.current, latestInputs.current, false);
    }
  }, [station, target, track]);

  const passStatus = useMemo(() => {
    if (!track) return { label: translate(locale, "orbit.waiting"), value: "--" };
    const now = new Date(track.generated_at).getTime();
    const window = track.contact_windows[0];
    if (!window) return { label: translate(locale, "orbit.next24"), value: translate(locale, "orbit.noPass") };
    if (track.current.visible) {
      return { label: translate(locale, "orbit.toLos"), value: formatDuration(new Date(window.los).getTime() - now) };
    }
    return { label: translate(locale, "orbit.toAos"), value: formatDuration(new Date(window.aos).getTime() - now) };
  }, [locale, track]);

  return (
    <div className="relative h-[360px] w-full flex-1 overflow-hidden bg-[#02080d] sm:h-[390px] xl:h-auto xl:min-h-[420px]">
      <div ref={element} className="absolute inset-0" aria-label={translate(locale, "ground.orbit")} />
      {renderError && <div className="absolute inset-0 grid place-items-center bg-[#071722] text-xs text-cyan-100">{translate(locale, "orbit.renderError")}</div>}
      <div className="pointer-events-none absolute left-3 top-3 grid grid-cols-2 gap-2 sm:left-4 sm:top-4">
        <MapMetric
          label={translate(locale, "orbit.elevation")}
          value={track ? `${track.current.elevation_deg.toFixed(1)}°` : "--"}
          active={track?.current.visible}
        />
        <MapMetric label={passStatus.label} value={passStatus.value} />
      </div>
      <div className="pointer-events-none absolute right-3 top-3 rounded-lg border border-white/10 bg-slate-950/75 px-3 py-2 text-right backdrop-blur sm:right-4 sm:top-4">
        <div className="text-[9px] tracking-[.16em] text-slate-500 uppercase">{translate(locale, "orbit.access")}</div>
        <div className={`mt-1 text-xs ${track?.current.visible ? "text-emerald-300" : "text-slate-300"}`}>
          {track?.current.visible ? translate(locale, "orbit.visible") : translate(locale, "orbit.notVisible")}
        </div>
        {track?.contact_mode === "deterministic" && <div className="mt-1 text-[9px] text-orange-300">{translate(locale, "orbit.deterministic")}</div>}
      </div>
      <div className="pointer-events-none absolute bottom-3 left-3 right-3 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-white/[.07] bg-slate-950/70 px-3 py-2 text-[9px] text-slate-400 backdrop-blur sm:left-4 sm:right-auto">
        <Legend color="#22d3ee" label={translate(locale, "orbit.history")} />
        <Legend color="#67e8f9" label={translate(locale, "orbit.forecast")} dashed />
        <Legend color="#4ade80" label={translate(locale, "orbit.visibleArc")} />
        <Legend color="#fb923c" label={translate(locale, "orbit.coverage")} />
      </div>
    </div>
  );
}

function MapMetric({ label, value, active }: { label: string; value: string; active?: boolean }) {
  return (
    <div className="min-w-24 rounded-lg border border-white/10 bg-slate-950/75 px-3 py-2 backdrop-blur">
      <div className="text-[9px] tracking-[.12em] text-slate-500 uppercase">{label}</div>
      <div className={`mt-1 font-mono text-xs ${active ? "text-emerald-300" : "text-cyan-100"}`}>{value}</div>
    </div>
  );
}

function Legend({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return <span className="flex items-center gap-1.5"><i className={`block h-0 w-4 border-t-2 ${dashed ? "border-dashed" : ""}`} style={{ borderColor: color }} />{label}</span>;
}

declare global {
  interface Window {
    CESIUM_BASE_URL: string;
    Cesium?: typeof Cesium;
  }
}
