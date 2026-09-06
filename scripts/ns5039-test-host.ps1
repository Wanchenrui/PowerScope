param(
    [Parameter(Mandatory=$true)][string]$Firmware,
    [Parameter(Mandatory=$true)][string]$Compiler
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$fw = (Resolve-Path -LiteralPath $Firmware).Path
$cc = (Resolve-Path -LiteralPath $Compiler).Path
$output = Join-Path $root 'build/t03-core.exe'
$fixture = Join-Path $root 'build/t03-info.hex'
Push-Location $root
try {
    & $cc -std=c11 -Wall -Wextra -Werror -Wno-error=unused-but-set-variable -Itests/firmware_ns5039 "-I$fw/user/include" "-I$fw/user/source" "-I$fw/ns800rt/common" -include tests/firmware_ns5039/address_seam.h tests/firmware_ns5039/test_core.c "$fw/user/source/wave_codec.c" -o $output
    if ($LASTEXITCODE -ne 0) { throw "NS5039 host compile failed: $LASTEXITCODE" }
    & $output $fixture
    if ($LASTEXITCODE -ne 0) { throw "NS5039 host checks failed: $LASTEXITCODE" }
    $expected = (Get-Content tests/fixtures/ns5039-get-info.json -Raw | ConvertFrom-Json).frame_hex
    if ((Get-Content -LiteralPath $fixture -Raw).Trim() -ne $expected) { throw 'Actual C GetInfo differs from committed fixture' }
} finally { Pop-Location }
