# Changelog

## 1.2.0

RE4 support and a lot of polish, found and tested on real RE4 robots by
@RBrNx (#3, #4) and @larsoss (#5, #6, #7, #8). The beta sections below list
each step.

Robots
- RE4: start, pause, stop and dock, room cleaning, carpet boost, do not
  disturb and per-room suction, water and passes now work. The integration
  detects each model's commands by itself and falls back when a robot refuses
  one.
- Lifetime totals (area, time, number of cleanings) and the last clean on
  robots that do not report them themselves, from the cloud clean log.
- The cleaning path is drawn at the right size on every robot; the scale is
  detected from the map.

Rooms
- Room names match the EZVIZ app, in Home Assistant's language (about 30
  languages). Some English names change, e.g. Hallway → Corridor; entity IDs
  stay the same.
- Per-room settings only for rooms that are on the map, under their map names.
  Rooms the app still calls "Room N" are created disabled.
- New option **Room devices**: each room's settings as a device of its own,
  linked to the robot (Settings → Devices & services → EZVIZ Robot Vacuum →
  Configure).

New sensors
- **Last event**: the newest message of the app's Events tab, in Home
  Assistant's language.
- **Last error** shows the app's own explanation; **Last error time** changes
  with every new error.
- **Charging status**: waiting to charge (off-peak) or charging.

Other
- Settings a robot does not have no longer appear as unavailable entities.
- Dutch translation (@larsoss).
- Debug logging shows each robot command and the robot's answer.

## 1.1.1b12 (beta)

Changes since 1.1.1b10 (1.1.1b11 was not published).

- New option **Room devices** (Settings → Devices & services → EZVIZ Robot
  Vacuum → Configure): each room's suction, water level and passes become a
  device of their own, linked to the robot, instead of being listed on the
  robot's page. Off by default. Entity IDs stay the same; turning it off moves
  the entities back and removes the empty room devices (#8).
- Last event and Last error are in Home Assistant's language, like the app;
  they came in English because the default request headers ask for English
  (#8).

## 1.1.1b10 (beta)

Changes since 1.1.1b9, by @larsoss (#8), found and tested on his RE4.

- Per-room suction, water and passes work on the RE4: like its app, the
  integration sends every room of the map in one `ModifyRoomCustomCleanCfgBatch`
  call, instead of the one-room `SetRoomCustomCleanCfg` the robot refused with
  code 1048579. Rooms left over in the settings but not on the map are left out.
  A model that refuses one form of the call is tried with the other.
- Per-room settings are created only for rooms that are on the map and have a
  name there, under that name.
- Rooms that still have the app's default name ("Room 13") are often not
  real rooms; their per-room entities are created disabled, and are enabled
  once the room gets a name in the app (entities you disabled yourself stay
  disabled). Entities of rooms that are no longer on the map are not deleted;
  they show as no longer provided and can be deleted by hand. The integration
  reloads by itself when the rooms of the map change.
- A "Charging status" sensor shows whether the robot is waiting to charge (the
  RE4 waits for the off-peak hours while its task is already "charging") or
  charging.
- A "Last event" sensor shows the newest message of the EZVIZ app's event list
  (faults such as "Side brush stuck" and notices such as "Cleaning completed"),
  in Home Assistant's language, with the time, the code and the last five
  events as attributes. It is read from the cloud's message list together with
  the clean log.
- "Last error" shows the app's explanation for a robot error code from the live
  task ("The wheel is suspended, please put the device on the ground to start
  it" instead of "Robot error 0xe0010025"): the message of the event list that
  arrives within a few seconds of the error is used. The event list is read
  again for up to five minutes after a new error until the message is found.
  An error that was already active when Home Assistant started uses the newest
  fault message of the last six hours, and a code explained once is remembered.
  The RE4 code `0xe0010025` is known as "The wheel is suspended".
- A "Last error time" sensor (timestamp) changes with every new error. The text
  of "Last error" stays the same when the same error comes back, so Home
  Assistant does not show a new entry for it.
- A docked RE4 that waits for the off-peak hours is shown as `waiting_charge` by
  "Current task" instead of `charging` (the original task name is in the
  `robot_task` attribute), so it agrees with "Charging status".
- "On base station" is on while the robot is charging or on a station task: the
  RE4 reports `isOnBasestation` as 0 while it sits on its dock. Numeric 1/0
  flags now also count for the docked activity.

## 1.1.1b9 (beta)

Changes since 1.1.1b6 (1.1.1b7 and 1.1.1b8 were not published).

- Standard room names use the EZVIZ app's own names, in Home Assistant's
  language (about 30 languages, 28 room types), so they match the app. Some
  English names change, e.g. Hallway → Corridor; entity IDs stay the same.
  Names typed in the app are kept as written (#5).
- Per-room suction and water send only the settings the robot has, like the
  app (the RE4 has no per-room passes) (#4).
- Settings the robot does not report get no entity, instead of one that is
  always unavailable (for example cleaning mode on the RE4).
- Last error shows the robot's current error when the robot keeps no error
  history (RE4).

## 1.1.1b6 (beta)

Changes since 1.1.1b4 (1.1.1b5 was not published).

- Total cleaned area, cleaning time and number of cleanings, and the last
  clean, on robots that do not report them themselves (RE4): read from the
  cloud clean log, like the app's clean log page. Robots that report them
  keep their own values (#5).
- Debug logging shows each robot command and the robot's answer, to compare
  with the EZVIZ app.

## 1.1.1b4 (beta)

- Do not disturb works on the RE4, which keeps it in its own setting. By
  @larsoss (#7).

## 1.1.1b3 (beta)

- Standard room names follow Home Assistant's language (English, German,
  Spanish, French, Italian, Dutch or Polish) (#5).

## 1.1.1b2 (beta)

- Carpet boost works on the RE4, which stores it as a 0/1 flag. By @larsoss
  (#6).
- Dutch translation. By @larsoss (#6).

## 1.1.1b1 (beta)

RE4 support, found and tested on real RE4 hardware by @RBrNx (#3, #4).

- Start, pause and stop work on robots that use `CleanCtrl` (RE4); they take
  an object payload, not a bare command (#5).
- Rooms are read from the room cleaning settings when the robot does not
  report its room list, so room cleaning works on the RE4.
- Room names come from the map's room layer, so the RE4 shows real names
  instead of "Room N".
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
