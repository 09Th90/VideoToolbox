# @version 2.5.1
<#
.SYNOPSIS
    一键部署 / 升级 AI 托管引擎（deepseek-harness）到 <程序根>\harness。

.DESCRIPTION
    harness 是**独立部署、内部零改动**的第三方原件（MIT）：
      · 本脚本只做三件事——解压官方 zip 到 harness\、装依赖、构建产物；
      · 不修改 harness 源码树里的任何文件（node_modules/lib/dist 属于生成物）；
      · 运行期状态（profile/凭据/配置补丁）由工具箱写进 data\harness-home，
        与 harness 目录完全隔离，升级 = 整目录替换，不动用户配置。

    环境变量（均可省略）：
      VT_HARNESS_ZIP   官方源码 zip 路径（默认 H:\deepseek-harness-master .zip）
      VT_HARNESS_SKIP_BUILD=1  跳过构建（只装依赖；headless 源码模式仍可用）

.NOTES
    · 需要 Node.js（>=22.19）；pnpm 走 corepack（版本由 harness/package.json 锁定）。
    · LEFTHOOK=0：harness 的 lefthook postinstall 会向上找到本仓库的 .git 并
      写入 git hooks + 根目录 lefthook.yml——必须屏蔽，否则污染工具箱仓库。
    · 依赖安装用 --ignore-scripts：本机上 esbuild 的 postinstall 校验会因
      Windows 下并发 spawn node.exe 的 EBUSY 偶发失败（二进制本身是好的），
      跳过生命周期脚本不影响构建（构建脚本另行显式执行）。
#>
param(
    [string]$Zip = $(if ($env:VT_HARNESS_ZIP) { $env:VT_HARNESS_ZIP } else { "H:\deepseek-harness-master .zip" }),
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$harness = Join-Path $root "harness"
$staging = Join-Path $env:TEMP ("vt-harness-stage-" + [guid]::NewGuid().ToString("N"))

function Need-Node {
    $node = Get-Command node -ErrorAction SilentlyContinue
    if (-not $node) { throw "未找到 node。 harness 需要 Node.js >= 22.19（https://nodejs.org/）" }
    $v = (& node --version).TrimStart("v")
    $parts = $v.Split(".")
    $major = [int]$parts[0]; $minor = if ($parts.Count -gt 1) { [int]$parts[1] } else { 0 }
    if ($major -lt 22 -or ($major -eq 22 -and $minor -lt 19)) {
        throw "Node 版本过低：$v（需要 >= 22.19）"
    }
    Write-Host "[ok] node $v"
}

Write-Host "== 1/4 解压 $Zip"
if (-not (Test-Path -LiteralPath $Zip)) { throw "找不到 zip：$Zip（可用 VT_HARNESS_ZIP 指定）" }
New-Item -ItemType Directory -Force -Path $staging | Out-Null
Expand-Archive -LiteralPath $Zip -DestinationPath $staging -Force
$inner = Join-Path $staging "deepseek-harness-master"
if (-not (Test-Path -LiteralPath $inner)) {
    $inner = (Get-ChildItem -LiteralPath $staging -Directory | Select-Object -First 1).FullName
}
if (-not (Test-Path -LiteralPath $inner)) { throw "zip 内找不到 harness 源码目录" }
New-Item -ItemType Directory -Force -Path $harness | Out-Null
# 摊平：zip 内是 deepseek-harness-master\，内容全部落到 harness\ 下
Get-ChildItem -LiteralPath $inner -Force | ForEach-Object {
    $dest = Join-Path $harness $_.Name
    if (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }
    Move-Item -LiteralPath $_.FullName -Destination $dest -Force
}
Write-Host "[ok] 已解压到 $harness"

Write-Host "== 2/4 检查 node"
Need-Node

Write-Host "== 3/4 安装依赖（pnpm install --frozen-lockfile --ignore-scripts）"
$env:COREPACK_ENABLE_DOWNLOAD_PROMPT = "0"
$env:COREPACK_ENABLE_STRICT = "0"
$env:LEFTHOOK = "0"          # 关键：屏蔽 lefthook 反向污染本仓库 git
Push-Location $harness
try {
    & corepack pnpm install --frozen-lockfile --ignore-scripts
    if ($LASTEXITCODE -ne 0) { throw "pnpm install 失败（码 $LASTEXITCODE）" }
} finally { Pop-Location }
Write-Host "[ok] 依赖就绪"

if ($SkipBuild -or $env:VT_HARNESS_SKIP_BUILD -eq "1") {
    Write-Host "== 4/4 跳过构建（按参数要求）"
} else {
    Write-Host "== 4/4 构建（pnpm run build，首次 5-15 分钟）"
    Push-Location $harness
    try {
        & corepack pnpm run build
        if ($LASTEXITCODE -ne 0) { throw "pnpm run build 失败（码 $LASTEXITCODE）" }
    } finally { Pop-Location }
    Write-Host "[ok] 构建完成"
}

Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "完成。 工具箱会在「AI 托管」接入就绪后自动出现「AI 托管」导航项；"
Write-Host "模型/密钥/接口地址取自「设置」页 AI 配置（无需在 harness 里再配 key）。"
