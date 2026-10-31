@echo off
rem Run the analysis (bin\analyze.js) on Windows, with Node.js 22 or later on the PATH. Installs the
rem packages the first time. Options as for bin\analyze.js:
rem
rem   analyze.cmd --server pvphq --server 25569
setlocal
where node >nul 2>nul || (echo Node.js 22 or later is needed: https://nodejs.org & exit /b 1)
for /f %%v in ('node -p "process.versions.node.split('.')[0]"') do if %%v LSS 22 (echo Node.js 22 or later is needed: https://nodejs.org & exit /b 1)
if not exist "%~dp0node_modules" (
  pushd "%~dp0"
  call npm ci --silent --no-audit --no-fund || (popd & exit /b 1)
  popd
)
node "%~dp0bin\analyze.js" %*
