param(
    [string]$Compiler = 'gcc',
    [switch]$Install
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$output = Join-Path $root 'build/native'
New-Item -ItemType Directory -Force $output | Out-Null
$cc = (Get-Command $Compiler -ErrorAction Stop).Source
function Invoke-Compiler([string[]]$Arguments) {
    & $cc @Arguments
    if ($LASTEXITCODE -ne 0) { throw "C compiler failed (exit $LASTEXITCODE)" }
}
Push-Location $root
try {
    & $cc --version
    $sources = @(Get-ChildItem power_core/src/*.c | ForEach-Object FullName)
    $common = @('-O2', '-std=c11', '-Wall', '-Wextra', '-I', 'power_core/include')
    Invoke-Compiler ($common + @('-shared') + $sources + @('-o', "$output/power_core.dll"))
    Invoke-Compiler ($common + @('-shared', 'tests/mock_mcu.c', 'mcu_debug_stub/debug_monitor.c', '-o', "$output/mock_mcu.dll"))
    foreach ($test in Get-ChildItem power_core/tests/test_*.c) {
        $exe = Join-Path $output ($test.BaseName + '.exe')
        Invoke-Compiler ($common + @($test.FullName) + $sources + @('-o', $exe))
        & $exe
        if ($LASTEXITCODE -ne 0) { throw "$($test.Name) failed (exit $LASTEXITCODE)" }
    }
    Invoke-Compiler ($common + @('tests/native_abi_probe.c') + @('-o', "$output/native_abi_probe.exe"))
    if ($Install) {
        Copy-Item "$output/power_core.dll", "$output/mock_mcu.dll" $root -Force
    }
    Get-FileHash "$output/power_core.dll", "$output/mock_mcu.dll"
} finally {
    Pop-Location
}
