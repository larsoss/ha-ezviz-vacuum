"""Constants for the EZVIZ Robot Vacuum integration."""

from datetime import timedelta

DOMAIN = "ezviz_vacuum"

CONF_SERIAL = "serial"
# The EZVIZ session (session ID, refresh ID, API host); never the password.
CONF_TOKEN = "token"
# Version 1 entries borrowed the official EZVIZ integration's session.
CONF_LEGACY_SOURCE_ENTRY_ID = "source_entry_id"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)
# Polling while the robot cleans or returns, so the map path follows it.
ACTIVE_SCAN_INTERVAL = timedelta(seconds=10)
# Seconds between full device reports (settings, consumables, history).
DEVICE_REFRESH_INTERVAL = 300
# The cloud clean log (lifetime totals) is read this often, and after a clean.
CLEAN_LOG_REFRESH_INTERVAL = 1800
# Days to look back for the newest event of the app's event list; later
# refreshes only need the last two days.
EVENT_LOOKBACK_DAYS = 7
EVENT_RECENT_DAYS = 2

SERVICE_INSPECT = "inspect"
SERVICE_MAP_DIAGNOSTICS = "map_diagnostics"
SERVICE_CAMERA_DIAGNOSTICS = "camera_diagnostics"
SERVICE_REFRESH_CAMERA = "refresh_camera_snapshot"
SERVICE_FEATURE_REQUEST = "feature_request"
SERVICE_API_REQUEST = "api_request"

# Cleaning modes accepted by SweeperCleanTask/SweepMopMode and by the
# cleanMode field of cleaning actions (validated by the EZVIZ cloud schema).
CLEAN_MODES = ("sweep", "mop", "sweepAndMop", "sweepThenMop")

# Every robot feature the entities may write. The API refuses anything else;
# safety settings such as cliff detection are deliberately missing.
WRITABLE_FEATURES: frozenset[tuple[str, str]] = frozenset(
    {
        ("SweeperBaseStationMgr", "ChildLockSwitch"),
        ("SweeperCleanTask", "DustCollectionCfg"),
        ("SweeperCleanTask", "CleaningSolutionCfg"),
        ("SweeperCleanTask", "RotatingBrushSelfCleanSwitch"),
        ("SweeperCleanTask", "SweepMopMode"),
        ("SweeperCleanTask", "CarpetCleanCfg"),
        ("SweeperCleanTask", "CarpetTurboCleanSwitch"),
        ("SweeperCleanTask", "WashMopCfg"),
        ("SweeperCleanTask", "DryMopDuration"),
        ("SweeperCleanTask", "ParticulateCleanEnhanceCfg"),
        ("SweeperCleanTask", "EdgeDeepCleanCfg"),
        ("SweeperCleanTask", "CleanPlan"),
        ("SweeperMgr", "RestPlan"),
        ("SweeperMgr", "RestMode"),
        ("SweeperMgr", "PetModeSwitch"),
        ("SweeperMgr", "SmartDirtDetectionCfg"),
        ("SweeperMgr", "ValleyCharge"),
        ("SoundSetting", "PromptToneVolume"),
    }
)

# Robot actions the entities may send. Map cleaning settings are changed this
# way (as the EZVIZ app does); writing the stored feature does not reach the
# robot.
# The two ways models change the cleaning settings of a room: the RS20 sends one
# room, the RE4 sends every room of the map at once.
ROOM_SETTING_ACTIONS: frozenset[str] = frozenset(
    {"SetRoomCustomCleanCfg", "ModifyRoomCustomCleanCfgBatch"}
)

SETTING_ACTIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("SweeperMapMgr", "SetFanModeOfStdClean"),
        ("SweeperMapMgr", "SetWaterQuantityOfStdClean"),
        ("SweeperMapMgr", "SetCleanTimesOfStdClean"),
        ("SweeperMapMgr", "SetCleanCfg"),
        ("SweeperMapMgr", "SetRoomCustomCleanCfg"),
        ("SweeperMapMgr", "ModifyRoomCustomCleanCfgBatch"),
        # RE7 Edge: suction and water for the whole map.
        ("SweeperMapMgr", "SetGlobalCleanCfg"),
    }
)
