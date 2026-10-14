# リリース前レビューへの対応

2026年10月13日。対象は初回公開版 NuniAvatarToolkit **1.0.0**。修正前の基準は `main` の [56c34dc62d38afc67cfe2fe90871f709476582f9](https://github.com/Nunifuchisaka/BlenderAddon/commit/56c34dc62d38afc67cfe2fe90871f709476582f9)（未公開の1.0.0候補）です。

元の指摘 **R01〜R23（P1 7件、P2 16件）** に対し、編集データの同期、変更前の入力検証、使用中データの保護、幾何判定・診断・更新処理を修正しました。安全に処理できない構成は説明付きで変更前に中止します。共有・リンクデータの自動ローカル化、absoluteキーの時間評価、任意の服モディファイアの逆変換を追加したという意味ではありません。

## 指摘と修正の対応

重要度は修正前レビューの分類を引き継いでいます。テスト欄は、変更後の安全な期待値を確認する回帰スクリプトへのリンクです。

| ID / 元の重要度 | 修正後の動作 | 主な実装 | 回帰確認 |
| --- | --- | --- | --- |
| R01 / P1 | cleanupのスキャン・削除候補を編集データの同期後に計算し、編集中の有効なキーを保持する。 | [cleanup操作][s-cleanup-op] | [編集したキーの保持][t-cleanup] |
| R02 / P1 | 隠れ面の選択・削除、cleanup、ボーンウェイト、服フィットで共有Meshへの変更を拒否する。解析用の読み取りは維持する。 | [共通事前検証][s-context]、[隠れ面API][s-hidden]、[ウェイト][s-bone]、[服フィット][s-cloth-op] | [隠れ面][t-hidden]、[cleanup][t-cleanup]、[ウェイト][t-bone]、[服][t-cloth] |
| R03 / P1 | ビューポート無効・Excludeの参照を評価済み形状として使用しない。評価キャッシュが残る場合も有効な所属経路を確認する。 | [評価入力検証][s-mesh]、[隠れ面API][s-hidden] | [未評価入力・キャッシュ][t-core]、[隠れ面の中止と復元][t-hidden] |
| R04 / P1 | Solidify・Wireframe等の素材番号依存モディファイアがありスロット削除候補がある場合、cleanupを他の削除より前に中止する。スキャンにも理由を表示する。 | [cleanup参照保護][s-cleanup-utils]、[操作順序][s-cleanup-op] | [生成面の素材・無変更][t-cleanup] |
| R05 / P1 | 素材番号依存モディファイアがある重複スロット統合を変更前に拒否し、生成面の素材を保つ。単純なスロット統合は継続する。 | [統合の事前検証][s-merge-op]、[未対応構成][s-merge-utils] | [Solidify・Wireframe・単純統合][t-cleanup] |
| R06 / P1 | Object側で割り当てた実効マテリアルからUV・カラー属性の参照を収集し、使用中属性を保持する。 | [実効参照収集][s-cleanup-utils] | [ObjectマテリアルのUV・カラー][t-cleanup] |
| R07 / P1 | 親から継承した反転を含め、ワールド行列の行列式が負の場合に三角形の向きを補正する。反転した体・服でも内外判定を維持する。 | [BVH構築][s-mesh] | [反転・混在Mesh][t-core]、[実フィット・貫通選択][t-cloth] |
| R08 / P2 | 面マスクで保護頂点を含む面を除外する。ANY判定でも保護頂点とその面を削除しない。 | [隠れ面API][s-hidden] | [ANYと除外グループ][t-hidden] |
| R09 / P2 | ObjectとMesh双方のリンク・オーバーライド・編集可能性を検査し、変更前に拒否する。保存後に失われる変更やcleanupの途中削除を防ぐ。 | [共通事前検証][s-context]、[ウェイト][s-bone]、[服の検証][s-cloth-utils] | [リンクデータ拒否][t-cleanup]、[ウェイト][t-bone]、[服][t-cloth] |
| R10 / P2 | 別IDのドライバー制御に使われるキーを保護する。数値インデックス参照では、参照番号を保つため前方のキーも保持する。 | [キーの参照収集][s-cleanup-utils]、[アニメーション所有者走査][s-cleanup-op] | [Key・Mesh・Object経由のドライバー][t-cleanup] |
| R11 / P2 | absoluteシェイプキーの服は未対応として変更前に拒否する。成功表示だけを返す状態を防ぐ。 | [服の構成検証][s-cloth-utils] | [absoluteキーの無変更][t-cloth] |
| R12 / P2 | 編集同期後の頂点数でウェイト・座標を計算する。計算成功後にキーを書き込み、失敗時は追加キーや上書き結果、ポーズ、選択・モードを復元する。 | [フィット・書込復元][s-cloth-op] | [頂点増減・計算失敗・部分書込][t-cloth] |
| R13 / P2 | 有効な服側モディファイアを許可リストで検証する。Displace等の未対応変形は変更前に拒否する。 | [服のモディファイア検証][s-cloth-utils] | [未対応変形の無変更][t-cloth] |
| R14 / P2 | 服が現在のビューレイヤーに所属し、編集可能・表示可能であることを処理前に確認する。評価失敗時もコンテキストを復元する。 | [共通事前検証][s-context]、[フィット][s-cloth-op] | [Exclude・未評価入力][t-cloth] |
| R15 / P2 | 基礎回転・スケールを保ってlocationだけを変更し、評価後のボーン位置と線形変換を事後検証する。条件を満たせない制約・ドライバーでは元のチャンネルを復元して中止する。 | [位置変換][s-align-utils]、[事後検証][s-align-op] | [制約・親・デルタ変換][t-bone] |
| R16 / P2 | 基準・対象Armatureの編集モードを変更前に拒否する。未同期のボーン位置で一致判定しない。 | [ボーン位置検証][s-align-utils] | [編集モードの保持][t-bone] |
| R17 / P2 | `use_deform=False` のボーンを実行時に拒否し、既存ウェイトを保持する。ボーンの変形設定を自動変更しない。 | [ウェイト事前検証][s-bone] | [非変形ボーン・結合後追従][t-bone] |
| R18 / P2 | 候補画像を一時データでデコードし、読込後のsize・has_dataも確認する。壊れた候補を成功に数えず元パスを保持し、再試行可能にする。 | [画像の検証・再リンク][s-texture] | [壊れた候補・キャッシュ・再試行][t-diagnostics] |
| R19 / P2 | 診断対象の根・祖先・子の除外／render非表示経路を確認する。複数所属の有効経路と重複警告の抑制も扱う。 | [コレクション経路診断][s-diag-utils] | [根・祖先・複数経路][t-diagnostics] |
| R20 / P2 | reference key（Basis）を含む全シェイプキーのNaN/Infを検査し、エラーとして報告する。 | [キー座標診断][s-diag-utils] | [Basis破損・OBJ出力][t-diagnostics] |
| R21 / P2 | 評価後のマテリアルスロット数を集計する。Geometry Nodesの追加素材と重複スロットを含む。 | [評価後の統計][s-diag-utils] | [GN素材・FBX・重複スロット][t-diagnostics] |
| R22 / P2 | Meshに加えてArmatureの負／不均一スケールと未適用回転を診断する。デルタ変換も対象とする。 | [変換診断][s-diag-op] | [Armature変換][t-diagnostics] |
| R23 / P2 | トップパッケージの再読込時に子モジュールを再構築し、ヘルパー・コピーされた参照・登録クラスを更新する。旧登録を解除し、reportを先に登録する順序を維持する。 | [登録・更新処理][s-init] | [実ZIP更新・登録解除][t-lifecycle] |

## 追加した安全条件

- **服フィットの既存キー:** Basisの上書き、自分自身をrelative_keyにするキー、mute中のキー、値1.0を含まないslider範囲を変更前に拒否する。自分以外の相対キーを使う既存キーでは、相対参照に合わせて座標を補正する。[実装][s-cloth-op]、[回帰確認][t-cloth]、[相対キー効果の既存テスト][t-review-fixes]。
- **共有データ:** fake userは他Objectの利用として数えない。実Object間の共有は変更前に拒否し、利用者がシングルユーザー化してから実行する。貫通チェックも共有Bodyへの面選択を拒否するが、読み取り用の共有服は利用できる。[事前検証][s-context]、[服・貫通回帰][t-cloth]。
- **評価キャッシュと表示経路:** モニター無効、コレクションのビューポート無効、Excludeでは、古い評価済み参照が残っていても使用しない。複数所属で有効な経路があれば利用できる。眼アイコンによる一時非表示の参照は許可し、編集対象の表示可能性は別途確認する。[評価入力検証][s-mesh]、[回帰確認][t-core]。
- **不正な変換:** BVH入力のNaN/Inf・スケール0、服の逆変換不能、位置合わせの親スケール0を検出して中止する。失敗したフィットや位置合わせは途中結果・コンテキストを残さない。[共通幾何処理][s-mesh]、[服][t-cloth]、[位置合わせ][t-bone]。
- **生成面の素材:** Solidifyに加えてWireframeの`material_offset`依存も保護する。cleanup・統合とも自動的な素材番号再配置は行わず、未対応スタックでは変更前に拒否する。無効化中のモディファイアも再有効化後の素材を保つため対象とする。[cleanup][s-cleanup-utils]、[統合][s-merge-utils]、[有効・無効Wireframeの無変更確認][t-cleanup]。

## 配布・更新

[配布スクリプト](../../tools/build-release.ps1)は相対パスを`/`へ正規化してから、休止中の`features/texture_bake/`、`__pycache__/`、`*.pyc`を除外します。ルートの[LICENSE](../../LICENSE)をZIPの`NuniAvatarToolkit/LICENSE`へ同梱し、版数は[bl_info][s-init]から読み取ります。`-OutputDirectory`で出力先を指定でき、省略時は従来通りリポジトリ直下です。

LinuxのPowerShell 7.4.7で実際のZIPを生成し、通常以外のキャッシュファイルも除外されること、LICENSEの内容、ZIP内の区切りを確認しました。修正前のZIPから修正後のZIPへの同一セッション更新も確認しました。Windows PowerShell（Windows 11）でも配布ZIPを生成し、55ファイル・トップが`NuniAvatarToolkit/`・区切りが`/`・LICENSE同梱で、`texture_bake`・`__pycache__`・`*.pyc`を含まないことを確認しました。[ライフサイクルテスト][t-lifecycle]では、一時的なZIP・ユーザー設定を使い、3回の有効化／無効化、子ヘルパー・機能コード・登録クラスの更新、直接reload時の登録解除を検証します。

## 検証結果

Linux上の **Blender 4.2.0、4.3.2、5.2.0 LTS** で、既存4本と追加7本、計**11本×3版＝33組すべて成功**。Blender外のunittestは**28件成功**しました。Wireframe保護の追加後はcleanup回帰を3版で再実行し、各版14ケースが成功しています。この3回は33組とは別の追加実行です。

加えて、版数を1.0.0に統合した後の状態で、Windows 11上の **Windows版 Blender 5.2.0 LTS** でも全11スクリプトとunittest 28件の成功を確認しました（2026年10月14日）。

| スクリプト | 主な確認範囲 |
| --- | --- |
| [blender_core_release_safety.py][t-core] | 反転法線、実評価入力、表示経路キャッシュ、fake user、不正変換 |
| [blender_hidden_release_safety.py][t-hidden] | 共有・リンクBody、除外頂点、未評価参照、失敗時の復元 |
| [blender_cleanup_release_safety.py][t-cleanup] | 編集同期、共有・リンク拒否、属性・ドライバー、生成素材、スロット操作 |
| [blender_cloth_release_safety.py][t-cloth] | 反転、キー構成、編集頂点数、書込復元、未対応構成、貫通選択 |
| [blender_bone_release_safety.py][t-bone] | ウェイト事前検証、結合後追従、位置合わせの制約・親・変換保持 |
| [blender_texture_diagnostics_release_safety.py][t-diagnostics] | 画像読込、コレクション経路、Basis、評価素材、Rig変換 |
| [blender_release_lifecycle_smoke.py][t-lifecycle] | ZIP導入・更新、子コード反映、RNA登録・解除 |
| [blender_hidden_mesh_smoke.py](../../tests/blender_hidden_mesh_smoke.py) | 公開APIと独立バックアップ |
| [blender_bone_follow_smoke.py](../../tests/blender_bone_follow_smoke.py) | 通常のウェイト・結合・追従 |
| [blender_review_fixes_smoke.py][t-review-fixes] | 既存の参照・相対キー等の回帰 |
| [blender_review_rest_smoke.py](../../tests/blender_review_rest_smoke.py) | 既存の各機能・入力検証の回帰 |

unittestは[test_safety_utils.py](../../tests/test_safety_utils.py)と[test_bone_follow_utils.py](../../tests/test_bone_follow_utils.py)です。Blenderスクリプトの回数とunittestのケース数は別集計です。追加回帰は「欠陥が起きる」期待値から、対象外データの保持・無変更での拒否・評価後の結果維持を確認する期待値へ変えています。

リポジトリ直下で再実行できます。

```sh
python -m unittest discover -s tests -p 'test_*.py'
for test in tests/blender*.py; do
  blender --background --factory-startup --threads 2 --python-exit-code 1 --python "$test" || exit $?
done
```

4.2.0・5.2.0はBlender公式配布のLinuxバイナリ、4.3.2は作業環境に導入済みのLinux版を使用しました。**macOS実機、Windows版の4.2〜4.3系、対話GUIの描画・Undo、Unity/VRChatへの実インポートは未検証**です。標準FBX/OBJの確認はBlender内で行い、ゲームエンジン側の動作まで確認した結果ではありません。ここに記載した条件の回帰確認であり、任意のアバター・制約・モディファイアへの対応を保証するものではありません。

[s-init]: ../../NuniAvatarToolkit/__init__.py
[s-context]: ../../NuniAvatarToolkit/core/context_utils.py
[s-mesh]: ../../NuniAvatarToolkit/core/mesh_eval.py
[s-hidden]: ../../NuniAvatarToolkit/features/hidden_mesh/api.py
[s-cleanup-op]: ../../NuniAvatarToolkit/features/cleanup/operators.py
[s-cleanup-utils]: ../../NuniAvatarToolkit/features/cleanup/utils.py
[s-merge-op]: ../../NuniAvatarToolkit/features/merge/operators.py
[s-merge-utils]: ../../NuniAvatarToolkit/features/merge/utils.py
[s-cloth-op]: ../../NuniAvatarToolkit/features/cloth_fit/operators.py
[s-cloth-utils]: ../../NuniAvatarToolkit/features/cloth_fit/utils.py
[s-bone]: ../../NuniAvatarToolkit/features/bone_follow/utils.py
[s-align-utils]: ../../NuniAvatarToolkit/features/armature_align/utils.py
[s-align-op]: ../../NuniAvatarToolkit/features/armature_align/operators.py
[s-texture]: ../../NuniAvatarToolkit/features/texture_relink/utils.py
[s-diag-utils]: ../../NuniAvatarToolkit/features/diagnostics/utils.py
[s-diag-op]: ../../NuniAvatarToolkit/features/diagnostics/operators.py
[t-core]: ../../tests/blender_core_release_safety.py
[t-hidden]: ../../tests/blender_hidden_release_safety.py
[t-cleanup]: ../../tests/blender_cleanup_release_safety.py
[t-cloth]: ../../tests/blender_cloth_release_safety.py
[t-bone]: ../../tests/blender_bone_release_safety.py
[t-diagnostics]: ../../tests/blender_texture_diagnostics_release_safety.py
[t-lifecycle]: ../../tests/blender_release_lifecycle_smoke.py
[t-review-fixes]: ../../tests/blender_review_fixes_smoke.py
