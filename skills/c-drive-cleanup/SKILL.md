---
name: c-drive-cleanup
description: Windows Cドライブの不要ファイルを高速かつ安全にスキャン・クリーンアップし、さらにDocker/WSL2仮想ディスクの未使用領域を物理的に圧縮して解放するスキル。
---

# C-Drive Cleanup & WSL2/Docker Optimization Skill

Windows OS環境において、Cドライブの容量を劇的に（数GB〜100GB以上）安全に解放し、開発環境（Docker/WSL2等）の無駄な占有スペースを物理的に縮小するための再利用可能なスキルです。

## 1. 超高速ディスクスキャンの掟 (G1)
Windows環境における `os.walk` や PowerShellの `Get-ChildItem` を使った単純な再帰走査は、ファイル数が多い場合に極めて低速（数分〜数十分）であり、スタックやタイムアウトの原因になります。

- **解決策**: Windows標準のファイル同期ユーティリティである `robocopy` のドライラン（一覧表示）機能を活用します。
- **実行コマンド**:
  ```cmd
  robocopy "<対象フォルダ>" "C:\temp_dummy" /L /S /NFL /NDL /R:0 /W:0
  ```
  - `/L`: 実際にはコピーせず、リストアップのみ行う（極めて高速）。
  - `/S`: サブディレクトリもスキャン対象とする。
  - `/NFL` / `/NDL`: ファイル名・フォルダ名をログに書き出さない（I/Oオーバーヘッドを削減）。
  - `/R:0` / `/W:0`: エラー時の再試行回数と待機時間を0にし、スタックを防止。
- **出力パース**:
  出力される最後の統計テーブル（日本語環境では `バイト:`、英語環境では `Bytes:`）の行から、実データサイズを読み取ります。
  ※PowerShell内の `$_.Length` などの特殊変数は、エージェント実行環境で意図せず展開・破損するため、`cmd.exe /c` または `python -c "import subprocess; ..."` 経由で呼び出すのが最も確実です。

## 2. 徹底クリーンアップ対象の選定と安全基準 (G2)
空き容量100GB以上を目指す際、削除すべき対象と安全に削除するための判定基準です。

### A. 自動削除が可能な安全キャッシュ（ユーザー合意前提）
1. **ユーザー一時ファイル (Temp)**:
   - パス: `%USERPROFILE%\AppData\Local\Temp` の中身。
   - ※使用中（ロック中）のファイルはスキップし、それ以外を再帰的に削除します。
2. **Downloads フォルダの不要一時ファイル**:
   - パス: `%USERPROFILE%\Downloads` の中身。
   - ※画像やドキュメントなどの個人データは保護し、**再ダウンロード可能な特定の拡張子**（`.exe`, `.msi`, `.apk`, `.zip`, `.rar`, `.7z`, `.iso` など）のみを狙って再帰削除します。
3. **ブラウザおよびアプリケーションキャッシュ**:
   - 以下のパス配下の `Cache` または `Code Cache` フォルダの中身（ログイン情報や設定は残します）。
     - Google Chrome: `%USERPROFILE%\AppData\Local\Google\Chrome\User Data\Default\Cache` など
     - Microsoft Edge: `%USERPROFILE%\AppData\Local\Microsoft\Edge\User Data\Default\Cache` など
     - MSTeams: `%USERPROFILE%\AppData\Local\Packages\MSTeams_8wekyb3d8bbwe\LocalCache` など
     - Office: `%USERPROFILE%\AppData\Local\Microsoft\Office\16.0\OfficeFileCache`

## 3. Docker / WSL2 仮想ディスク圧縮の掟 (G3)
Docker（WSL2）内で `docker system prune -a --volumes` を実行して数GB〜数十GBの未使用データをクリーンアップしても、Windows側の仮想ディスクファイル（`*.vhdx`）の物理サイズは自動で縮小されず、Cドライブを占有したままになります。

- **解決策**: `wsl --shutdown` を実行して停止させた後、Windows標準の `diskpart` を用いて、実在する `.vhdx` に対し `compact vdisk`（物理的圧縮）を実行します。
- **対象となる仮想ディスクの実在パス**:
  環境によって階層が異なるため、必ず `dir /s /b C:\Users\<ユーザー名>\AppData\Local\Docker\wsl\*.vhdx` などで実在するパスを確認します。
  - 例1: `C:\Users\<user>\AppData\Local\Docker\wsl\disk\docker_data.vhdx` (データ実体：大容量)
  - 例2: `C:\Users\<user>\AppData\Local\Docker\wsl\main\ext4.vhdx` (メインディストリビューション)

- **diskpart用自動スクリプトの組み立て**:
  ```text
  select vdisk file="<確認した実在パス>"
  attach vdisk readonly
  compact vdisk
  detach vdisk
  exit
  ```

## 4. バッチファイル強靭化（Robust）の鉄則 (G4)
管理者権限が必要な処理（diskpartや休止状態の操作等）をユーザーにバッチファイルとして提供する場合、Windows特有の文字コード（UTF-8 vs Shift-JIS / cp932）不整合による誤作動（「コマンドが見つかりません」パースエラー）を完全に防ぐ必要があります。

1. **バッチ内は完全英語（英数字のみ）で記述する**:
   日本語（全角文字）を一切含めないことで、エンコードによるコマンド誤認を100%排除します。
2. **コマンドのフルパス指定**:
   重要な外部コマンド（`wsl`, `diskpart`等）は、PATHの破損に影響されないよう絶対パス（`C:\Windows\System32\wsl.exe` など）で直接呼び出します。
