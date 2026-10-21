"""Task deadlines use Armenia's local clock and UTC for storage."""

from zoneinfo import ZoneInfo

TASK_TIMEZONE = ZoneInfo("Asia/Yerevan")
