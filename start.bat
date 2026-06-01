@echo off
start "law-qa backend" cmd /k "cd /d %~dp0backend && python main.py"
start "law-qa frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
