@echo off
cd /d "E:\Du an 1"
set "II_OVERNIGHT_SCAN_START=17:00"
set "II_OVERNIGHT_SCAN_END=07:00"
set "II_OVERNIGHT_SCAN_TZ=Asia/Ho_Chi_Minh"
"C:\Users\Admin\AppData\Local\Programs\Python\Python312\python.exe" "E:\Du an 1\scripts\run_overnight_scan_tick.py" --batch-size 40 --workers 3 --universe-mode dynamic_liquid
