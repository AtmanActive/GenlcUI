"""GNet command IDs (CIDs).

Deliberately incomplete. This module lists only commands GenlcUI actually
sends, and the omissions are a safety invariant rather than an oversight:

    CID_STORE_USER_PARS, CID_STORE_CALIBRATION, CID_START_VOLUME,
    CID_ERASE_FLASH, CID_WRITE_FLASH, CID_FIRMWARE_UPDATE, ...

Those write to speaker flash, which is where a GLM calibration lives. A user
who has calibrated with GLM5 must be able to run this application without any
risk of losing that work, so the commands that could destroy it are simply not
present in the codebase. Everything below is runtime-only and leaves flash
untouched.

If you are adding a feature that seems to need one of the omitted commands,
that is a decision for the user to make explicitly, not a detail to slip into
a patch.
"""

# Discovery and addressing
CID_RACE = 0xFE             # broadcast; unassigned monitors answer with serial
CID_SET_RID = 0x02          # assign a runtime address to a serial
CID_STAY_ONLINE = 0x04      # keepalive; see HEARTBEAT_INTERVAL_S

# Status
CID_POLL = 0x08
CID_BAR_CODE = 0x19
CID_HARDWARE_QUERY = 0x22
CID_SOFTWARE_QUERY2 = 0x39
CID_MIC_SERIAL = 0x51

# Control
CID_VOLUME_GLM = 0x1F       # broadcast master volume, sint24 linear
CID_WAKEUP = 0x3A
CID_BYPASS_QUERY = 0x2B     # monitor state. See STATE_* below.

# Measured against real hardware: an assigned address stops answering after
# ~2-3s of bus silence, and STAY_ONLINE at 250ms prevented that across a 34s
# idle. See docs/PROTOCOL.md.
LEASE_TIMEOUT_S = 2.0
HEARTBEAT_INTERVAL_S = 0.25

# Monitors refresh measurements about once a second and return a bare ACK in
# between; the adapter's knob and mic update every sample.
MONITOR_POLL_INTERVAL_S = 1.0
ADAPTER_POLL_INTERVAL_S = 0.05

# Background rescan, so a speaker switched on after launch appears by itself.
# The poll loop only visits monitors it already knows about, so without this
# nothing would ever notice a new one. Cheap: a RACE that finds nothing is a
# single timed-out request (~30ms), and a full discovery of three monitors was
# measured at 0.068s.
DISCOVERY_INTERVAL_S = 2.0

# CID_BYPASS_QUERY carries a monitor STATE, not an LED colour.
#
# genlc models this byte as {bit 0: mute, bits 1-2: LED colour}, so calling
# bypass(led_color="red") sends value 2 -- which does not paint an LED. What
# it actually does, observed on real hardware:
#
#     value 0x02  ->  LED goes steady red
#                     audio KEEPS PLAYING at its current level
#                     the monitor stops responding to volume control
#     value 0x00  ->  restores normal operation, knob works again
#
# So 0x02 freezes the volume stage. It is NOT a mute.
#
# Note the trap: the GLM 5 manual (Table 5) lists "steady red = Muted from
# GLM", and that reading is wrong here -- audio was never silenced. Either
# the label means "GLM's volume path is muted" rather than "the audio is
# muted", or the table is simplified. Observed behaviour beat the manual, and
# the manual beat genlc's naming; trust them in that order.
#
# Working hypothesis (the user's, and it fits every observation): a real GLM
# mute sets BOTH bits -- 0x01 silences the audio, 0x02 locks the volume stage,
# and 0x03 together is what the manual calls "Muted from GLM". We sent 0x02
# alone, i.e. half a mute: the lock without the silence, which is exactly the
# LED-says-muted-but-audio-plays state observed. UNTESTED; do not send 0x01 or
# 0x03 to the user's hardware without asking first.
#
# Consequently there is NO verified mute command. Do not use 0x02 for one.
# Mute in the UI is set_volume(-130.0), which is fully understood, reversible,
# and lands at the documented bottom of the fader.
STATE_NORMAL = 0x00     # verified: restores normal operation

# Used by "identify this speaker": lights the LED steady red so you can tell
# which cabinet you are naming. NOT cosmetic -- this is the same value that
# froze the author's volume control, so it must always be time limited and
# always restored to STATE_NORMAL. See Session.start_identify.
STATE_IDENTIFY = 0x02

# 0x02, 0x04, 0x06 are deliberately unnamed. 0x02 is known to break volume
# control; the other two are untested. Nothing in the UI should reach them.
