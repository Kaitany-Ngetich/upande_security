import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Loader2, Maximize2, RotateCw } from "lucide-react";
import { isError, type Envelope } from "@/lib/frappe";
import type { StreamTicket } from "@/lib/cctv-api";
import { cn } from "@/lib/utils";

/**
 * Plays one stream from the site's media gateway (MediaMTX).
 *
 * WebRTC via WHEP first (sub-second delay); HLS where the browser plays it
 * natively (Safari / iOS) if WebRTC fails. The ticket - a short-lived token
 * for exactly this camera and path - comes from ERPNext each time a stream
 * starts; the browser never sees a camera address or password.
 */
async function startWhep(url: string, video: HTMLVideoElement): Promise<RTCPeerConnection> {
  const pc = new RTCPeerConnection({ iceServers: [] });
  pc.addTransceiver("video", { direction: "recvonly" });
  pc.addTransceiver("audio", { direction: "recvonly" });
  pc.ontrack = (e) => {
    if (video.srcObject !== e.streams[0]) video.srcObject = e.streams[0];
  };
  await pc.setLocalDescription(await pc.createOffer());
  // Wait (briefly) for ICE candidates so the single offer carries them.
  await new Promise<void>((resolve) => {
    if (pc.iceGatheringState === "complete") return resolve();
    const t = setTimeout(resolve, 1500);
    pc.addEventListener("icegatheringstatechange", () => {
      if (pc.iceGatheringState === "complete") {
        clearTimeout(t);
        resolve();
      }
    });
  });
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/sdp" }, body: pc.localDescription?.sdp });
  if (!res.ok) {
    pc.close();
    throw new Error(res.status === 401 ? "The viewing pass was refused or has expired." : `The camera gateway answered ${res.status}.`);
  }
  await pc.setRemoteDescription({ type: "answer", sdp: await res.text() });
  return pc;
}

type State = { kind: "connecting" } | { kind: "playing" } | { kind: "error"; message: string };

export function VideoPlayer({
  getTicket,
  label,
  className,
  muted = true,
  onTicket,
  overlay,
}: {
  /** Asks ERPNext for a ticket; called on mount and on retry. */
  getTicket: () => Promise<Envelope<StreamTicket>>;
  label: string;
  className?: string;
  muted?: boolean;
  onTicket?: (t: StreamTicket) => void;
  overlay?: React.ReactNode;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<State>({ kind: "connecting" });
  const [attempt, setAttempt] = useState(0);
  const ticketFn = useRef(getTicket);
  ticketFn.current = getTicket;
  const onTicketRef = useRef(onTicket);
  onTicketRef.current = onTicket;

  useEffect(() => {
    let pc: RTCPeerConnection | null = null;
    let cancelled = false;
    const el = video.current;
    setState({ kind: "connecting" });
    (async () => {
      const t = await ticketFn.current();
      if (cancelled || !el) return;
      if (isError(t)) return setState({ kind: "error", message: t.error });
      onTicketRef.current?.(t);
      try {
        pc = await startWhep(t.whep_url, el);
        if (cancelled) return pc.close();
        pc.onconnectionstatechange = () => {
          if (pc?.connectionState === "failed" || pc?.connectionState === "disconnected") {
            setState({ kind: "error", message: "The stream dropped." });
          }
        };
      } catch (e) {
        if (el.canPlayType("application/vnd.apple.mpegurl")) {
          el.src = t.hls_url;
        } else {
          return setState({ kind: "error", message: e instanceof Error ? e.message : "Could not reach the camera gateway." });
        }
      }
      el.play().catch(() => undefined);
    })();
    return () => {
      cancelled = true;
      pc?.close();
      if (el) {
        el.srcObject = null;
        el.removeAttribute("src");
      }
    };
  }, [attempt]);

  return (
    <div className={cn("relative overflow-hidden rounded-[var(--sd-radius)] bg-black", className)}>
      <video
        ref={video}
        className="h-full w-full object-contain"
        playsInline
        muted={muted}
        autoPlay
        aria-label={label}
        onPlaying={() => setState({ kind: "playing" })}
      />
      {state.kind === "connecting" && (
        <div className="absolute inset-0 flex items-center justify-center gap-2 text-[12px] text-white/80">
          <Loader2 className="h-4 w-4 animate-spin" /> Connecting…
        </div>
      )}
      {state.kind === "error" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-4 text-center text-[12px] text-white/85">
          <AlertTriangle className="h-5 w-5 text-[var(--sd-target)]" />
          <span>{state.message}</span>
          <button type="button" onClick={() => setAttempt((n) => n + 1)} className="inline-flex items-center gap-1 rounded-full bg-white/15 px-3 py-1 hover:bg-white/25">
            <RotateCw className="h-3 w-3" /> Try again
          </button>
        </div>
      )}
      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-center justify-between gap-2 bg-gradient-to-b from-black/60 to-transparent px-2 py-1.5 text-[12px] text-white">
        <span className="truncate font-medium">{label}</span>
        <button
          type="button"
          aria-label="Full screen"
          className="pointer-events-auto rounded p-1 hover:bg-white/20"
          onClick={() => video.current?.parentElement?.requestFullscreen?.()}
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
      </div>
      {overlay}
    </div>
  );
}
