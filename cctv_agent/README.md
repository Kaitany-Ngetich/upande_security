# Upande Security – CCTV site agent

One per site (farm, factory, office…). Runs on a small box **inside the site
network**, next to the recorders. It is the only thing that talks to the
cameras; ERPNext never reaches into the site.

```
recorders (Hikvision / Dahua / ONVIF) ──► agent ──HTTPS out──► ERPNext (events, heartbeats)
                                   └──► MediaMTX ──WebRTC/HLS──► browser (token from ERPNext)
```

## What it does
- **Events**: subscribes to each recorder's event stream, turns brand events
  into the normalised schema (plate reads, line crossing, intrusion, doors,
  access control, tamper, video loss…), corrects the recorder's clock error,
  and sends them to ERPNext in signed batches. Every event is written to a
  local SQLite buffer first, so an internet outage loses nothing.
- **Config**: pulls cameras, recorders and settings from ERPNext every minute
  (`CCTV Server`, `CCTV Camera`); nothing about cameras is configured here.
- **Live view**: keeps MediaMTX's `live/<camera>/<sub|main>` paths in step with
  ERPNext; streams are pulled only while someone watches, never recorded.
- **Playback**: `pb/<camera>/<start>_<end>` makes MediaMTX run the recorder's
  own playback for exactly that range (`cctv_agent.playback`).
- **Access**: MediaMTX asks the agent about every viewer; only a valid,
  unexpired token from ERPNext for that exact path is let in.
- **Health**: recorder reachability and clock drift, reported to ERPNext.

## Site survey (do this first)
Before installing anything, find out what a site's recorders are and how they fit:

```
pip install .            # or use the Docker image
python -m cctv_agent.survey --scan                                   # ONVIF devices on this network
python -m cctv_agent.survey --brand Hikvision --host 192.168.1.64 --user admin   # asks for the password
```

It writes `survey-<host>.html` (send it to the integration team) and `.json`
(import it in ERPNext: CCTV Site Survey list > *Import survey from laptop*).
Once the agent runs, the same survey is the *Run site survey* button on the
CCTV Server form.

The report covers: device model, firmware, serial, CPU/memory/uptime; every
camera (model, IP, online, main/sub codec, resolution, fps, recording mode,
events); disks and their health; the events Upande Security can use (plates,
line crossing, intrusion, faces...); clock and NTP; the device's own exception
log (disk errors, video loss, network drops, abnormal reboots, failed logins);
every API call made and whether it answered; and a verdict - Ready, Ready
with fixes, Not ready - with the fixes listed. Passwords never appear in it.

## Install on a site box
1. In ERPNext: create the **CCTV Site Agent** (site, gateway URL, signing
   secret), an API user with **only** the *CCTV Agent* role, the **CCTV Server**
   records (brand, address, a least-privilege recorder account) and cameras.
2. On the box (Docker + Compose installed, NTP on):
   ```
   cp agent.example.yml agent.yml        # set id and erp_url
   mkdir secrets && chmod 700 secrets    # erp_api_key, erp_api_secret, agent_hmac
   docker compose up -d --build
   ```
3. Publish MediaMTX's viewer ports (8889 WebRTC, 8888 HLS) **only** through an
   HTTPS tunnel / VPN (e.g. Cloudflare Tunnel or WireGuard) and put that URL in
   *CCTV Site Agent > Media Gateway URL*. Never port-forward the recorders.

## Verify on real hardware before trusting
The adapter paths and event formats follow the vendors' published APIs, but
firmware varies. For each recorder model: live main/sub, playback of a known
time, event arrival (plate / line / motion), snapshot, clock offset, and
reconnect after a reboot. Replace the sample payloads in `tests/` with
captures from the pilot recorders.

## Develop
```
uv venv && uv pip install -e '.[test]'
.venv/bin/pytest -q
```
