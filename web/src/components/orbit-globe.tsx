"use client";

import { useEffect, useMemo, useRef } from "react";
import type * as Cesium from "cesium";

import type { OrbitSample, OrbitTrack } from "~/lib/types";

interface OrbitGlobeProps {
  track?: OrbitTrack;
  station: { name: string; latitude: number; longitude: number; altitudeM: number };
  target?: { name: string; latitude: number; longitude: number };
}

type SceneInputs = OrbitGlobeProps;

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
        text: `目标 · ${target.name}`,
        font: "11px sans-serif",
        pixelOffset: new C.Cartesian2(0, 20),
        fillColor: C.Color.fromCssColorString("#fde68a"),
      },
    });
  }

  if (setInitialCamera) {
    viewer.camera.setView({
      destination: C.Cartesian3.fromDegrees(station.longitude, station.latitude, 8_200_000),
    });
  }
}

function formatDuration(milliseconds: number) {
  const totalMinutes = Math.max(0, Math.round(milliseconds / 60_000));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

export function OrbitGlobe({ track, station, target }: OrbitGlobeProps) {
  const element = useRef<HTMLDivElement>(null);
  const viewer = useRef<Cesium.Viewer | undefined>(undefined);
  const cesium = useRef<typeof Cesium | undefined>(undefined);
  const latestInputs = useRef<SceneInputs>({ track, station, target });
  latestInputs.current = { track, station, target };

  useEffect(() => {
    if (!element.current) return;
    let disposed = false;
    void (async () => {
      window.CESIUM_BASE_URL = process.env.NEXT_PUBLIC_CESIUM_BASE_URL ?? "/cesium/";
      const C = await import("cesium");
      if (disposed || !element.current) return;
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
        baseLayer: false,
        skyBox: false,
      });
      instance.scene.globe.baseColor = C.Color.fromCssColorString("#071722");
      instance.scene.backgroundColor = C.Color.fromCssColorString("#02080d");
      instance.scene.globe.enableLighting = true;
      viewer.current = instance;
      cesium.current = C;
      drawScene(instance, C, latestInputs.current, true);
    })();
    return () => {
      disposed = true;
      viewer.current?.destroy();
      viewer.current = undefined;
      cesium.current = undefined;
    };
  }, []);

  useEffect(() => {
    if (viewer.current && cesium.current) {
      drawScene(viewer.current, cesium.current, latestInputs.current, false);
    }
  }, [station, target, track]);

  const passStatus = useMemo(() => {
    if (!track) return { label: "等待轨道数据", value: "--" };
    const now = new Date(track.generated_at).getTime();
    const window = track.contact_windows[0];
    if (!window) return { label: "未来 24h", value: "无过站" };
    if (track.current.visible) {
      return { label: "距离 LOS", value: formatDuration(new Date(window.los).getTime() - now) };
    }
    return { label: "距离 AOS", value: formatDuration(new Date(window.aos).getTime() - now) };
  }, [track]);

  return (
    <div className="relative h-[400px] w-full overflow-hidden bg-[#02080d] sm:h-[430px] xl:h-[460px]">
      <div ref={element} className="absolute inset-0" aria-label="Cesium 轨道态势视图" />
      <div className="pointer-events-none absolute left-3 top-3 grid grid-cols-2 gap-2 sm:left-4 sm:top-4">
        <MapMetric
          label="地面站仰角"
          value={track ? `${track.current.elevation_deg.toFixed(1)}°` : "--"}
          active={track?.current.visible}
        />
        <MapMetric label={passStatus.label} value={passStatus.value} />
      </div>
      <div className="pointer-events-none absolute right-3 top-3 rounded-lg border border-white/10 bg-slate-950/75 px-3 py-2 text-right backdrop-blur sm:right-4 sm:top-4">
        <div className="text-[9px] tracking-[.16em] text-slate-500 uppercase">接入判定</div>
        <div className={`mt-1 text-xs ${track?.current.visible ? "text-emerald-300" : "text-slate-300"}`}>
          {track?.current.visible ? "几何可见" : "几何不可见"}
        </div>
        {track?.contact_mode === "deterministic" && <div className="mt-1 text-[9px] text-orange-300">任务链路使用确定性窗口</div>}
      </div>
      <div className="pointer-events-none absolute bottom-3 left-3 right-3 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-white/[.07] bg-slate-950/70 px-3 py-2 text-[9px] text-slate-400 backdrop-blur sm:left-4 sm:right-auto">
        <Legend color="#22d3ee" label="历史轨迹" />
        <Legend color="#67e8f9" label="未来轨迹" dashed />
        <Legend color="#4ade80" label="可见弧段" />
        <Legend color="#fb923c" label="地面站覆盖" />
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
  interface Window { CESIUM_BASE_URL: string }
}
