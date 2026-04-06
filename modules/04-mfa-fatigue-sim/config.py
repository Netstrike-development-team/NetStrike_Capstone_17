#  MFA Fatigue Simulator 
#  Configuration File
#  Edit these values to change attack behavior

# The API runs on this port on local machine
API_PORT = 5050

# How many push attempts before the API approves the request.
# This simulates a fatigued employee finally tapping "Approve".
APPROVAL_THRESHOLD = 4

# Full URL of the mock API endpoint
TARGET_URL = "http://localhost:5050/api/push"

# Who the attacker is targeting (fake employee ID)
TARGET_USER = "AyaAshleyPatrick@simcorp.com"

# How many push notifications to send in one run
BURST_SIZE = 10

# Seconds to wait between each push
# Lower = more aggressive. Real fatigue attacks use 1-3 seconds.
INTERVAL_SECONDS = 15

# Where to save the log file
LOG_FILE = "logs/push_events.json"