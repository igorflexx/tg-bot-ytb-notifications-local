@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo This project uses local mode on Windows.
call "%~dp0runlocalwin.cmd"
exit /b %errorlevel%
