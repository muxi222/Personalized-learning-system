Add-Type -AssemblyName System.Drawing
$assetDirectory = Join-Path $PSScriptRoot '../public'
New-Item -ItemType Directory -Path $assetDirectory -Force | Out-Null
$bitmap = New-Object System.Drawing.Bitmap 264, 300
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.Clear([System.Drawing.Color]::Transparent)
$paper = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml('#ffffff'))
$back = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml('#edf3fc'))
$shadow = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml('#e5edf9'))
$blue = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml('#85aaf0'))
$line = New-Object System.Drawing.Pen ([System.Drawing.ColorTranslator]::FromHtml('#dde6f4')), 5
$border = New-Object System.Drawing.Pen ([System.Drawing.ColorTranslator]::FromHtml('#d8e3f4')), 2
$green = New-Object System.Drawing.Pen ([System.Drawing.ColorTranslator]::FromHtml('#61b4a0')), 5
try {
  $graphics.FillRectangle($back, 62, 28, 157, 230)
  $graphics.FillRectangle($shadow, 43, 43, 159, 233)
  $graphics.FillRectangle($paper, 35, 35, 157, 230)
  $graphics.DrawRectangle($border, 35, 35, 157, 230)
  $graphics.FillRectangle($blue, 57, 61, 69, 8)
  $graphics.DrawLine($line, 57, 90, 169, 90)
  $graphics.DrawLine($line, 57, 103, 147, 103)
  foreach ($row in @(132, 173, 214)) {
    $graphics.DrawRectangle($border, 57, $row, 15, 15)
    $graphics.DrawLine($line, 87, ($row + 4), 169, ($row + 4))
    $graphics.DrawLine($line, 87, ($row + 17), 139, ($row + 17))
  }
  $graphics.DrawLine($green, 57, 177, 64, 184)
  $graphics.DrawLine($green, 64, 184, 78, 169)
  $bitmap.Save((Join-Path $assetDirectory 'exam-sheet.png'), [System.Drawing.Imaging.ImageFormat]::Png)
} finally {
  $graphics.Dispose()
  $bitmap.Dispose()
  foreach ($resource in @($paper, $back, $shadow, $blue, $line, $border, $green)) { $resource.Dispose() }
}
