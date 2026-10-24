@echo off
title AUDEN
cd /d "%~dp0"
python auden.py %*
if errorlevel 1 pause
