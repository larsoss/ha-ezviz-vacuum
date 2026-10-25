# Changelog

## 1.1.1b1 (beta)

RE4 support, found and tested on real RE4 hardware by @RBrNx (#3, #4).

- Start, pause and stop work on robots that use `CleanCtrl` (RE4); they
  take an object payload, not a bare command (#5).
- Rooms are read from the room cleaning settings when the robot does not
  report its room list, so room cleaning works on the RE4.
- Room names come from the map's room layer, so the RE4 shows real names
  instead of "Room N". Preset names with a number (`Room 4`) and the laundry
  room are translated.
- The "On base station" sensor accepts robots that report it as 0/1.
- The cleaning path is drawn at the right size on robots that store it at
  ten times the map's resolution; the scale is detected from the map itself.

## 1.1.0

The integration now signs in to EZVIZ on its own instead of borrowing the
official EZVIZ integration's session.

- New setup: EZVIZ email or phone number, password and server, with the
  verification-code step when EZVIZ asks for one. Only the session token is
  stored, never the password.
- Re-authentication when the session expires. Existing robots ask to sign in
  once after updating; entities, room mapping and settings are kept.
- The official EZVIZ integration is no longer needed.
- Robot requests use the integration's own HTTP session and only public parts
  of pyezvizapi, which is now a declared requirement.

## 1.0.0

The integration is now **EZVIZ Robot Vacuum** (`ezviz_vacuum`) and supports
EZVIZ's current robots. Upgrading from 0.x needs the integration to be added
again; see the README.

- Renamed from `ezviz_rs20pro` / EZVIZ RS20 to `ezviz_vacuum` / EZVIZ Robot
  Vacuum; services are now `ezviz_vacuum.*`. The repository moved to
  `stefanelul2000/ha-ezviz-vacuum`.
- Support for the RS20 Pro, RS2, RE4, RE4C, RE4 Plus, RE4C Plus, RE5, RE5 Plus,
  RE5S Plus and RE7 Edge, built from the EZVIZ app's own plugins (untested).
  Robots that use different command names (some RS2 units, the RE7 Edge) are
  detected and handled automatically.
- A robot named in the EZVIZ app keeps that name in Home Assistant; only the
  default model name gets the "EZVIZ" prefix.
- Cleaning mode options are now `sweep`, `mop`, `sweep_and_mop` and
  `sweep_then_mop`, as Home Assistant requires.
- Issue forms for model reports, bugs and feature requests.
- GitHub checks: HACS, Hassfest, Ruff, tests on Python 3.13 and 3.14,
  translation keys, and a release zip.

## 0.7.0

- Live map: a new **Map** image entity draws the active map with coloured,
  named rooms, walls, obstacles, the dock, the robot and the path of the
  current clean. Layers are downloaded only when they change, and the path is
  cleared once the robot is docked.
- The live task is polled every 10 seconds while the robot cleans or returns.
- Suction, water level, passes and room settings are now changed the way the
  EZVIZ app does it, so they take effect immediately, even mid-clean. Room
  cleaning no longer overrides them with each room's stored values.
- A paused clean shows as paused, and starting it again resumes it instead of
  being refused.
- Return to dock uses the robot's recharge command and works again.
- Refusals from the robot are explained in English.
- The raw API request service can send JSON bodies and headers.
- Removed the enhanced obstacle recognition switch, which the robot refuses,
  and the voice assistant switch.
- README rewritten.

## 0.6.0

First release of this fork, now named EZVIZ RS20.

- Settings: suction level on the vacuum, cleaning mode, water level, cleaning
  passes, per-room suction, water and passes, do not disturb, schedules,
  carpet options, mop washing and drying, dust collection frequency, feature
  switches, voice volume and off-peak charging.
- Sensors: lifetime totals, battery cycles, consumable hours, dirty water tank
  filter, current task, task duration, relocation failures, last error, last
  cleaning run and Wi-Fi signal; binary sensors for being on the base station
  and do not disturb.
- The vacuum state follows the robot's live task, and errors are described in
  English.
- Rooms and room cleaning use the robot's active map; room cleaning uses the
  selected cleaning mode.
- The device shows the real model and firmware; other EZVIZ robot vacuums are
  detected.
- Several robots can be added; services take an optional serial.
- Failed commands are reported as errors instead of failing silently.
- The full device report is polled every 5 minutes instead of every 30
  seconds.
- Admin-only raw request services for protocol discovery.
- All texts in English; translations updated for all six languages.
- Removed unused cloud replay and stream code.

## 0.5.1

- Add an original repository-local brand icon for HACS.
- Sort manifest keys according to Home Assistant validation requirements.

## 0.5.0

- Add base-station status sensors for mop washing, mop drying, dust collection,
  water-tank draining and the optional plumbing module.
- Add safe station setting switches for child lock, automatic dust collection,
  automatic cleaning-solution dosing and rotating-brush self-cleaning.
- Add English, Polish, German, French, Spanish and Italian translations.
- Add HACS packaging, documentation, tests and GitHub validation workflows.
- Keep the robot camera privacy-first: snapshots are captured only on request.

## 0.4.2

- Add native room cleaning, on-demand camera snapshots, maintenance sensors and
  diagnostics for the RS20 Pro cloud protocol.
