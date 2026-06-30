# anim-studio M0 — add NK's cloned voice to the rendered clips and mux (loop video to voice length).
# Run from the anim-studio folder:  .\build_proof.ps1
$ErrorActionPreference = "Stop"

# $studio defaults to this script's own folder; voice ref defaults to a sibling dots-pilot checkout.
# Override either by setting $env:ANIM_STUDIO / $env:DOTS_REF before running.
$studio = if ($env:ANIM_STUDIO) { $env:ANIM_STUDIO } else { $PSScriptRoot }
$genai  = "$env:USERPROFILE\.conda\envs\genai\python.exe"
$ff     = "$env:USERPROFILE\.conda\envs\skill45video\Library\bin\ffmpeg.exe"
$ref    = if ($env:DOTS_REF) { $env:DOTS_REF } else { "$studio\..\dots-pilot\nk_en.wav" }
$voice  = "$studio\voice\proof_en.wav"
$line   = "Forty-five rupees. Forty-five days. Three lessons a day. This is Skill45."

Write-Host "[1/2] generating NK's cloned voice line..." -ForegroundColor Cyan
& $genai "$studio\make_voice.py" --text $line --ref $ref --lang en --out $voice --steps 16

Write-Host "[2/2] muxing voice into both aspects (looping video to voice length)..." -ForegroundColor Cyan
foreach ($a in @("16x9","9x16")) {
  $inV = "$studio\out\proof.$a.mp4"
  $outV = "$studio\out\proof.$a.voiced.mp4"
  & $ff -y -stream_loop -1 -i $inV -i $voice -map 0:v:0 -map 1:a:0 -shortest -c:v libx264 -pix_fmt yuv420p -preset veryfast -crf 20 -c:a aac -b:a 192k $outV
  Write-Host "  -> $outV"
}
Write-Host "DONE. Play: out\proof.16x9.voiced.mp4  and  out\proof.9x16.voiced.mp4" -ForegroundColor Green
