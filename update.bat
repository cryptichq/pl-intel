@echo off
echo.
echo  ================================================
echo   PL INTEL - WEEKLY UPDATE
echo  ================================================
echo.

cd /d "%~dp0"

echo [1/8] Logging last week's results...
python tracker.py --update
echo.

echo [2/8] Fetching live fixtures...
python live_fixtures.py
echo.

echo [3/8] Updating player stats...
python playerstats.py --scrape
echo.

echo [4/8] Enriching fixtures...
python enrich.py
echo.

echo [5/8] Running predictions...
python pl.py --predict
echo.

echo [6/8] Finding value bets...
python valuefinder.py
echo.

echo [7/8] Generating website...
python playerstats.py --predict
python site.py
copy /y pl_intel.html index.html
echo.

echo [8/8] Pushing to GitHub...
git add index.html
git commit -m "Weekly update %date%"
git push origin master
echo.

echo  ================================================
echo   DONE! Site live at:
echo   https://cryptichq.github.io/pl-intel
echo  ================================================
echo.
pause
