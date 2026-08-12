"use client";

import { useEffect, useMemo, useState } from "react";
import { Braces, CheckCircle2, Copy, FileDigit, Radio } from "lucide-react";

import { api, protocolStreamURL } from "~/lib/api";
import type { NodeKind, ProtocolFrameTrace, ProtocolTransaction } from "~/lib/types";

const nodeLabels: Record<NodeKind, string> = {
  ground: "地面站", platform: "星务平台", optical: "光学载荷", gpu: "GPU Payload",
};

function formatBytes(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

export function ProtocolInspector({ missionId, runId, node }: {
  missionId?: string; runId?: string; node?: NodeKind;
}) {
  const [transactions, setTransactions] = useState<ProtocolTransaction[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [frames, setFrames] = useState<ProtocolFrameTrace[]>([]);

  const reload = async () => {
    if (!missionId) return;
    const rows = await api.protocolTransactions(missionId);
    const ordered = [...rows].sort((left, right) =>
      new Date(left.started_at).getTime() - new Date(right.started_at).getTime()
    );
    setTransactions(ordered);
    setSelectedId((current) => current && ordered.some((row) => row.id === current)
      ? current : ordered[0]?.id);
  };

  useEffect(() => { void reload(); }, [missionId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!runId) return;
    const source = new EventSource(protocolStreamURL(runId));
    source.addEventListener("protocol", () => void reload());
    source.addEventListener("protocol_frame", () => {
      if (selectedId) void api.protocolFrames(selectedId).then(setFrames);
    });
    return () => source.close();
  }, [runId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!selectedId) { setFrames([]); return; }
    void api.protocolFrames(selectedId).then(setFrames).catch(() => setFrames([]));
  }, [selectedId, transactions]);

  const visible = useMemo(() => node ? transactions.filter((row) =>
    row.source_node === node || row.target_node === node
  ) : transactions, [node, transactions]);
  const selected = transactions.find((row) => row.id === selectedId && visible.includes(row))
    ?? visible[0];

  useEffect(() => {
    if (selected && selected.id !== selectedId) setSelectedId(selected.id);
  }, [selected, selectedId]);

  return <div className="panel overflow-hidden rounded-2xl">
    <div className="flex items-center justify-between border-b border-white/[.06] px-4 py-3">
      <h2 className="flex items-center gap-2 text-sm font-medium"><Radio size={16} className="text-cyan-300" />协议观察器</h2>
      <span className="text-[10px] text-slate-500">事务 · 解码正文 · SIMF 帧</span>
    </div>
    <div className="min-h-[360px] p-3">
      <div className="mb-3 flex gap-2 overflow-x-auto pb-1">
        {visible.map((row) => <button key={row.id} onClick={() => setSelectedId(row.id)}
          className={`min-w-[190px] flex-1 rounded-lg border px-3 py-2 text-left transition ${selected?.id === row.id ? "border-cyan-300/35 bg-cyan-300/10" : "border-transparent bg-black/10 hover:bg-white/[.035]"}`}>
          <div className="flex items-center justify-between text-[10px]"><span className="text-cyan-200">{row.message_type}</span><span className={row.status === "running" ? "text-orange-300" : "text-emerald-300"}>{row.status}</span></div>
          <div className="mt-1 text-xs text-slate-300">{nodeLabels[row.source_node]} → {nodeLabels[row.target_node]}</div>
          <div className="mt-1 flex gap-3 text-[9px] text-slate-600"><span>{row.protocol}</span><span>{formatBytes(row.total_bytes)}</span><span>{row.frame_count} 帧</span></div>
        </button>)}
        {!visible.length && <div className="w-full py-10 text-center text-xs text-slate-600">{node ? "当前节点尚无协议事务。" : "当前任务尚无协议事务。"}</div>}
      </div>
      <div className="min-w-0">
        {selected ? <>
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Metric label="链路" value={selected.link} /><Metric label="方向" value={selected.direction} />
            <Metric label="重传" value={String(selected.retry_count)} /><Metric label="CRC 失败" value={String(selected.crc_failures)} />
          </div>
          <div className="mb-4 rounded-xl border border-white/[.06] bg-black/20">
            <div className="flex items-center justify-between border-b border-white/[.05] px-3 py-2 text-xs text-slate-300"><span className="flex items-center gap-2"><Braces size={14} />协议正文</span><button onClick={() => navigator.clipboard.writeText(JSON.stringify(selected.payload.decoded_json ?? selected.payload.summary, null, 2))} className="flex items-center gap-1 text-[10px] text-cyan-300"><Copy size={12} />复制</button></div>
            <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap break-all p-3 font-mono text-[11px] leading-5 text-slate-400">{JSON.stringify(selected.payload.decoded_json ?? selected.payload.summary, null, 2)}</pre>
            {selected.payload.redacted && <div className="border-t border-orange-300/15 px-3 py-2 text-[10px] text-orange-200">敏感字段已递归脱敏</div>}
          </div>
          <div className="max-h-64 overflow-y-auto rounded-xl border border-white/[.06]">
            <table className="w-full table-fixed text-left text-[10px]"><thead className="sticky top-0 bg-[#0a1b28] text-slate-500"><tr><th className="w-[14%] p-2">序号</th><th className="w-[24%]">类型</th><th className="w-[14%]">负载</th><th className="w-[18%]">CRC32C</th><th className="w-[10%]">尝试</th><th className="w-[20%]">ACK / NAK</th></tr></thead><tbody>{frames.map((frame) => <tr key={frame.id} className="border-t border-white/[.045] text-slate-400"><td className="p-2 font-mono">{frame.sequence}/{frame.total}</td><td className="break-words">{frame.message_type}</td><td>{formatBytes(frame.payload_bytes)}</td><td className={`break-all ${frame.crc_valid ? "text-emerald-300" : "text-red-300"}`}>{frame.crc32c ?? "--"}</td><td>{frame.attempt + 1}</td><td className="break-words">{frame.ack_status}{frame.missing_sequences.length ? ` [${frame.missing_sequences.join(", ")}]` : ""}</td></tr>)}</tbody></table>
            {!frames.length && <div className="p-6 text-center text-xs text-slate-600">旧事务仅有汇总数据，或帧尚未到达。</div>}
          </div>
        </> : <div className="flex min-h-72 items-center justify-center text-xs text-slate-600"><FileDigit size={16} className="mr-2" />选择协议事务查看正文和帧。</div>}
      </div>
    </div>
  </div>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-white/[.055] bg-black/15 px-3 py-2"><div className="text-[9px] uppercase tracking-wider text-slate-600">{label}</div><div className="mt-1 flex items-center gap-1 font-mono text-xs text-slate-200"><CheckCircle2 size={11} className="text-emerald-300" />{value}</div></div>;
}
