@echo off
title AUDEN - setup
cd /d "%~dp0"
python auden.py --setup
if errorlevel 1 pause
