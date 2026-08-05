@echo off
cd /d "%~dp0"
call run_app.bat prod
exit /b %errorlevel%
