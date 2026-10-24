#!/bin/bash
echo "=== 3. Journal 30 days ==="
# We only want the last 500 lines to avoid massive output in terminal, wait the user wanted specifically to identify every time the service stopped/failed etc over the 30 days. Let's dump the grep results.
journalctl -u telegram-poster-api --since "30 days ago" --no-pager > /tmp/jnl.log

echo "=== 4. Transitions in last 30 days ==="
grep -Ei "stopped|failed|crashed|exited|restarted|starting|started|kill|term" /tmp/jnl.log

echo "=== 5. Warnings/Errors in Journal ==="
journalctl -u telegram-poster-api -p warning..alert --since "30 days ago" --no-pager

echo "=== 13. Systemctl Restart/Timeout settings ==="
systemctl show telegram-poster-api -p Restart -p RestartSec -p TimeoutStartSec -p TimeoutStopSec --no-pager

echo "=== 15. Server reboots ==="
journalctl --list-boots --no-pager

echo "=== 17. Flask/Python Errors ==="
grep -Ei "error|exception|traceback|failed|killed|shutdown|stopped|terminated|exit" /tmp/jnl.log
