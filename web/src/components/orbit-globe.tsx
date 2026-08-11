"use client";
import { useEffect, useRef } from "react";

export function OrbitGlobe({satelliteLongitude=112,satelliteLatitude=32}:{satelliteLongitude?:number;satelliteLatitude?:number}) {
  const element=useRef<HTMLDivElement>(null);
  useEffect(()=>{ if(!element.current)return; let disposed=false; let viewer:import("cesium").Viewer|undefined;
    void(async()=>{ window.CESIUM_BASE_URL=process.env.NEXT_PUBLIC_CESIUM_BASE_URL??"/cesium/"; const C=await import("cesium"); if(disposed||!element.current)return;
      viewer=new C.Viewer(element.current,{animation:false,timeline:false,geocoder:false,homeButton:false,sceneModePicker:false,navigationHelpButton:false,baseLayerPicker:false,fullscreenButton:false,infoBox:false,selectionIndicator:false,baseLayer:false,skyBox:false});
      viewer.scene.globe.baseColor=C.Color.fromCssColorString("#071722"); viewer.scene.backgroundColor=C.Color.fromCssColorString("#02080d");
      viewer.entities.add({name:"GS-DEMO-BEIJING",position:C.Cartesian3.fromDegrees(116.4074,39.9042,50),point:{pixelSize:9,color:C.Color.ORANGE,outlineColor:C.Color.WHITE,outlineWidth:1},label:{text:"北京模拟站",font:"12px sans-serif",pixelOffset:new C.Cartesian2(0,-18),fillColor:C.Color.ORANGE}});
      const orbit=Array.from({length:100},(_,i)=>C.Cartesian3.fromDegrees(-180+i*3.6,43*Math.sin(i/9),500000)); viewer.entities.add({polyline:{positions:orbit,width:1.5,material:C.Color.fromCssColorString("#39dff8").withAlpha(.65)}});
      viewer.entities.add({name:"SIM-OPTICAL-01",position:C.Cartesian3.fromDegrees(satelliteLongitude,satelliteLatitude,500000),point:{pixelSize:10,color:C.Color.CYAN,outlineColor:C.Color.WHITE,outlineWidth:2},label:{text:"SIM-OPTICAL-01",font:"12px sans-serif",pixelOffset:new C.Cartesian2(0,-20),fillColor:C.Color.CYAN}});
      viewer.camera.flyTo({destination:C.Cartesian3.fromDegrees(112,32,9500000),duration:0}); })();
    return()=>{disposed=true;viewer?.destroy();}; },[satelliteLatitude,satelliteLongitude]);
  return <div ref={element} className="h-full min-h-[360px] w-full" aria-label="Cesium 轨道视图"/>;
}
declare global{interface Window{CESIUM_BASE_URL:string;}}

