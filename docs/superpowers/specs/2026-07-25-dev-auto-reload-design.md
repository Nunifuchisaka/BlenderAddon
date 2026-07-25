# 開発時の自動リロード環境 設計

## 背景・目的

`NuniAvatarToolkit` はビルド工程を持たず、フォルダをZIP圧縮したものがそのまま配布物になる。そのため開発中にコードを修正するたびに、

1. `NuniAvatarToolkit` フォルダをZIP圧縮し直す
2. Blenderの環境設定で旧アドオンを削除する
3. 新しいZIPをインストールして有効化する

という手順が必要で、確認サイクルが遅い。

これを解消し、**リポジトリ内のファイルを保存するだけでBlender側に自動反映される**開発環境を用意する。

### 対象範囲

- 開発者（管理人）のローカル環境のみを対象とする。配布物には一切含めない。
- 対象OSはWindows（開発機がWindows 11）。
- 対象Blenderは開発機にインストール済みの 5.0 / 5.2。

## 全体構成

```
%LOCALAPPDATA%\NuniAvatarToolkitDev\        ← Blenderに登録する開発用スクリプトディレクトリ
  └ addons\
      ├ NuniAvatarToolkit   → E:\git\BlenderAddon\NuniAvatarToolkit へのジャンクション
      └ nuni_dev_reload\    → E:\git\BlenderAddon\tools\nuni_dev_reload へのジャンクション
```

リポジトリ側には以下を追加する（いずれも配布ZIPには含まれない）:

```
tools/
  ├ setup-dev-link.ps1        セットアップスクリプト
  ├ teardown-dev-link.ps1     後始末スクリプト
  └ nuni_dev_reload/
      └ __init__.py           自動リロード監視アドオン
```

配布ZIPは `NuniAvatarToolkit/` フォルダのみを圧縮するため、`tools/` は自動的に除外される。

## 設計判断の記録

### なぜBlenderのアドオンフォルダ内に直接ジャンクションを張らないか

`%APPDATA%\Blender Foundation\Blender\<ver>\scripts\addons\` 配下にジャンクションを置くと、Blenderの環境設定で当該アドオンの「削除」を押したときに `shutil.rmtree` が実行される。Windowsのジャンクションに対する `shutil.rmtree` の挙動はPythonのバージョンによって差があり、ジャンクションを辿って**リンク先の実体（リポジトリ本体）を削除する**危険がある。

Blenderが管理するアドオンディレクトリの外に開発用スクリプトディレクトリを別途用意し、そこを Preferences → File Paths → Script Directories に登録することで、Blenderの「アドオン削除」操作の対象外にする。

### なぜ開発用ディレクトリをリポジトリ外（`%LOCALAPPDATA%`）に置くか

リポジトリ内に `.blender-dev/` のような開発用ディレクトリを作ると、`.gitignore` への追加が必要になり、リポジトリを走査する各種ツールがジャンクション越しに同じファイルを二重に見る可能性がある。開発機固有の設定はリポジトリ外に置くほうが素直。

### なぜ `bpy.ops.script.reload()` を使わないか

`bpy.ops.script.reload()` は全スクリプトを再読み込みするため重く、監視アドオン自身も再読み込みの巻き添えになって `bpy.app.timers` に登録したタイマーが失われる。対象パッケージのモジュールだけを `sys.modules` から削除して再有効化する方式なら、監視アドオンは別モジュールとして生き残り、監視が継続する。

### なぜ既存の実体コピーを削除するか

`%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\NuniAvatarToolkit`（ZIPインストールで作られた実体コピー）を残したままスクリプトディレクトリを追加すると、同名パッケージが2箇所に存在する。Blenderがどちらを読むかは検索順に依存し、「修正したのに反映されない」原因になる。セットアップ時に削除する。

## コンポーネント

### `tools/nuni_dev_reload/__init__.py` — 自動リロード監視アドオン

レガシー形式の `bl_info` を持つ単一パッケージのアドオン。

**定数:**

- `WATCH_PACKAGE = "NuniAvatarToolkit"` — 監視・リロード対象のパッケージ名
- `POLL_INTERVAL = 1.0` — 監視間隔（秒）

**動作:**

- `register()` で `bpy.app.timers.register(_poll, first_interval=POLL_INTERVAL, persistent=True)` を登録する。`persistent=True` により新規ファイル読み込み後もタイマーが維持される。
- `_poll()` は監視対象パッケージのディレクトリを `os.walk` で走査し、全 `.py` ファイルの `st_mtime` の最大値と件数を組にしたシグネチャを求める。前回のシグネチャと異なれば変更ありと判定する。
  - mtimeだけでなくファイル件数も見るのは、ファイル削除を検知するため。
  - 監視対象のパスは `addon_utils.modules()` から解決するのではなく、この監視アドオン自身の `__file__` を基準に、同じ `addons` ディレクトリ内の `WATCH_PACKAGE` フォルダとして解決する。ジャンクション経由でもリポジトリ側の実ファイルのmtimeが読める。
- 変更を検知したら以下を実行する:
  ```python
  addon_utils.disable(WATCH_PACKAGE, default_set=False)
  for name in [n for n in sys.modules
               if n == WATCH_PACKAGE or n.startswith(WATCH_PACKAGE + ".")]:
      del sys.modules[name]
  addon_utils.enable(WATCH_PACKAGE, default_set=False)
  ```
  - `default_set=False` によりユーザー設定（どのアドオンを有効にするか）を書き換えない。
  - リロードの成否をコンソールに出力する（`print`）。成功時は `[nuni_dev_reload] reloaded NuniAvatarToolkit`、失敗時は例外のトレースバックを出す。
- リロード中に例外が発生しても監視は止めない。構文エラーのあるコードを保存した場合、コンソールにエラーが出るだけで、修正して保存し直せば次のポーリングで復帰する。
- `_poll()` は常に `POLL_INTERVAL` を返してタイマーを継続させる。
- `unregister()` で `bpy.app.timers.unregister(_poll)` を呼ぶ（登録されている場合のみ）。
- 監視対象パッケージが存在しない場合（ジャンクション未作成など）は、何もせずタイマーだけ継続する。

**シグネチャ状態の保持:**

モジュールレベルの変数に持つ。監視アドオン自身はリロード対象外なので、状態が失われることはない。初回ポーリング時は「前回値なし」としてシグネチャを記録するだけで、リロードは行わない。

### `tools/setup-dev-link.ps1` — セットアップスクリプト

**パラメータ:**

- `-BlenderVersion` — 対象Blenderバージョン。既定値 `"5.2"`。
- `-RepoRoot` — リポジトリルート。既定値はスクリプト自身の親ディレクトリ（`tools/` の親）。

**処理:**

1. 対象Blenderの実行ファイル `C:\Program Files\Blender Foundation\Blender <BlenderVersion>\blender.exe` の存在を確認する。無ければエラー終了。
2. 開発用スクリプトディレクトリ `%LOCALAPPDATA%\NuniAvatarToolkitDev\addons` を作成する（既存なら何もしない）。
3. ジャンクションを作成する。既存のジャンクションがあれば作り直す:
   - `<devdir>\addons\NuniAvatarToolkit` → `<RepoRoot>\NuniAvatarToolkit`
   - `<devdir>\addons\nuni_dev_reload` → `<RepoRoot>\tools\nuni_dev_reload`
   - 作成には `New-Item -ItemType Junction` を使う。ジャンクションは管理者権限を必要としない（シンボリックリンクと異なる点）。
4. Blenderのアドオンフォルダ `%APPDATA%\Blender Foundation\Blender\<BlenderVersion>\scripts\addons\NuniAvatarToolkit` が**実体ディレクトリとして**存在する場合、削除する。
   - ジャンクションだった場合は `Remove-Item` で参照だけを削除する（リンク先は消さない）。
   - 削除前に、そのパスがジャンクションか実体かを `(Get-Item $path).LinkType` で判定する。
5. Blenderをヘッドレスで起動し、スクリプトディレクトリの登録とアドオンの有効化を行う:
   ```
   blender.exe --background --python-expr "<スクリプト>"
   ```
   実行するPythonの内容:
   - 既に同じパスが `bpy.context.preferences.filepaths.script_directories` に登録済みでなければ `bpy.ops.preferences.script_directory_add(directory=<devdir>)` を実行する。
   - `bpy.ops.preferences.addon_refresh()` でアドオン一覧を再走査する。
   - `addon_utils.enable("nuni_dev_reload", default_set=True)` と `addon_utils.enable("NuniAvatarToolkit", default_set=True)` を実行する。
   - `bpy.ops.wm.save_userpref()` で設定を保存する。
   - 各ステップの結果を `print` し、PowerShell側で出力を表示する。
6. 完了メッセージとして、作成したジャンクションのパスと、次に何をすればよいか（Blenderを起動すれば自動リロードが有効）を表示する。

**冪等性:** 何度実行しても安全に同じ状態になるよう書く。既存のジャンクション・登録済みスクリプトディレクトリ・有効化済みアドオンは、いずれも重複させない。

### `tools/teardown-dev-link.ps1` — 後始末スクリプト

開発環境を元に戻すためのスクリプト。パラメータは `setup-dev-link.ps1` と同じ `-BlenderVersion`。

**処理:**

1. Blenderをヘッドレスで起動し、以下を行う:
   - `addon_utils.disable("NuniAvatarToolkit", default_set=True)` と `addon_utils.disable("nuni_dev_reload", default_set=True)` で両アドオンを無効化する。
   - `bpy.context.preferences.filepaths.script_directories` を列挙し、パスが開発用スクリプトディレクトリと一致する要素のインデックスを求め、`bpy.ops.preferences.script_directory_remove(index=<そのインデックス>)` を実行する。該当が無ければ何もしない。
   - `bpy.ops.wm.save_userpref()` で保存する。
2. `%LOCALAPPDATA%\NuniAvatarToolkitDev` 配下のジャンクションを削除する。削除前に `LinkType` を確認し、ジャンクションであることを確かめてから削除する（実体ディレクトリだった場合は警告を出して中断する）。
3. `%LOCALAPPDATA%\NuniAvatarToolkitDev` ディレクトリ自体を削除する。

リポジトリ側のファイルには一切触れない。

## エラーハンドリング

| 状況 | 挙動 |
|---|---|
| 指定バージョンのBlenderが見つからない | セットアップスクリプトがエラーメッセージを出して終了 |
| ジャンクション作成先に実体ディレクトリが既にある | 内容を消さないため警告を出して中断する（手動での確認を促す） |
| Blenderのヘッドレス起動が失敗する | 終了コードを確認し、標準出力・標準エラーを表示して終了 |
| 監視対象パッケージが存在しない | 監視アドオンは何もせずポーリングを継続する |
| リロード中に構文エラー等の例外が発生 | コンソールにトレースバックを出力し、監視は継続する |
| Blender起動中にジャンクションを張り替えた | 次のポーリングで検知され、リロードされる |

## 既知の限界

- **`bl_info` の変更は反映されない。** Blenderは `bl_info` をアドオン一覧の走査時に読み込むため、バージョン番号や説明文の変更は自動リロードでは反映されない。`bpy.ops.preferences.addon_refresh()` またはBlender再起動が必要。
- **PropertyGroupの構造変更は不安定になりうる。** プロパティの追加・削除・型変更を行った場合、既存のシーンに残った古いプロパティ定義と衝突することがある。この場合はBlenderを再起動する。
- **`core/report.py` の `bpy.types` クラス定義を変更した場合も同様。** 各featureのPropertyGroupが `AMT_ReportLine` を参照しているため、登録順の都合で再登録が失敗することがある。この場合もBlender再起動で解消する。
- リロードは自動で行われるが、**ビューポート上の表示は次の再描画まで更新されないことがある。** サイドバーのパネルにマウスを乗せる等で再描画される。

これらはいずれも「うまくいかなかったらBlenderを再起動する」で解決する。自動リロードは日常的な小さな修正の確認サイクルを速くするためのものであり、あらゆる変更に対応することは目指さない。

## テスト方針

- 自動テストは無し（プロジェクト全体方針）。
- 開発機（Windows 11 / Blender 5.2）で以下を確認する:
  - `setup-dev-link.ps1` を実行し、ジャンクションが作成され、Blenderのスクリプトディレクトリに登録され、両アドオンが有効になること。
  - Blenderを起動した状態で `NuniAvatarToolkit` 配下の `.py` を編集・保存し、数秒以内にコンソールへリロードのログが出て、変更がパネルに反映されること（例: パネルの `bl_label` を変えて表示名が変わること）。
  - 構文エラーのあるコードを保存したとき、コンソールにトレースバックが出るが監視が止まらないこと。修正して保存し直せば復帰すること。
  - `setup-dev-link.ps1` を2回続けて実行しても壊れないこと（冪等性）。
  - `teardown-dev-link.ps1` を実行すると、ジャンクションと設定が除去され、**リポジトリ側のファイルが無傷であること**。
  - 従来通り `NuniAvatarToolkit` フォルダをZIP圧縮した配布物に `tools/` が含まれないこと。

## スコープ外

- macOS / Linux への対応は行わない（開発機がWindowsのみ）。
- Blender 5.0 でも同じスクリプトが `-BlenderVersion 5.0` で動くようにはするが、動作確認は 5.2 でのみ行う。
- VS Code拡張（Blender Development等）との連携は行わない。
- 配布ZIPの自動生成は本設計の対象外とする（別途必要になれば追加する）。
- 監視アドオンをBlenderのUIから設定変更できるようにはしない（監視間隔・対象パッケージはコード内の定数）。
