import bpy


def _mesh_object_poll(self, obj):
    return obj.type == 'MESH'


class AMT_HiddenMeshProperties(bpy.types.PropertyGroup):
    body_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="ボディメッシュ",
        description="服の下に隠れている部分を検出したいアバターの体メッシュを指定してください",
        poll=_mesh_object_poll,
    )
    clothing_collection: bpy.props.PointerProperty(
        type=bpy.types.Collection,
        name="服コレクション",
        description=(
            "体を覆っている服メッシュをまとめたコレクションを指定してください。"
            "コレクション内(サブコレクション含む)の全メッシュオブジェクトが遮蔽物として扱われます"
        ),
    )
    ray_samples: bpy.props.IntProperty(
        name="サンプル数",
        description="各頂点から放射状に飛ばすレイの本数です。多いほど判定精度が上がりますが計算時間が増加します",
        default=24, min=4, max=256,
    )
    ray_epsilon_ratio: bpy.props.FloatProperty(
        name="オフセット比率",
        description=(
            "レイの発射位置を頂点の法線方向にずらすオフセット量を、体メッシュのバウンディングボックス対角線に対する"
            "比率で指定します。自己交差による誤判定を防ぐために使用します"
        ),
        default=0.0002, min=1e-6, max=0.01, precision=6,
    )
    face_select_mode: bpy.props.EnumProperty(
        name="判定モード",
        description="面を隠れ面として扱う条件を指定します",
        items=[
            ('ALL', "全頂点が隠れている面のみ",
             "面を構成する全ての頂点が隠れている場合のみ削除対象にします(推奨)。境界に穴が開きにくい安全な設定です"),
            ('ANY', "いずれかの頂点が隠れている面",
             "面を構成する頂点のいずれかが隠れていれば削除対象にします。より積極的に削除しますが境界付近に穴が開くことがあります"),
        ],
        default='ALL',
    )
    include_body_self_occlusion: bpy.props.BoolProperty(
        name="自身のメッシュも遮蔽物に含める",
        description=(
            "体メッシュ自身も遮蔽物として扱い、口の中や脇の下など、服とは関係なく自分の体で隠れている部分も"
            "削除対象にします。シェイプキーや口の開閉で見える範囲が変わる部分を誤って削除する可能性があるため、"
            "「除外頂点グループ」で保護するか、結果を必ず目視確認してください"
        ),
        default=False,
    )
    self_occlusion_min_distance_ratio: bpy.props.FloatProperty(
        name="自己遮蔽の最小距離比率",
        description=(
            "「自身のメッシュも遮蔽物に含める」が有効な場合に、体メッシュのバウンディングボックス対角線に対する"
            "比率で自己ヒットの最小距離を指定します。値が小さすぎると曲面部分が誤って隠れ扱いになることがあります"
        ),
        default=0.01, min=1e-5, max=0.5, precision=5,
    )
    exclude_vertex_group: bpy.props.StringProperty(
        name="除外頂点グループ",
        description=(
            "指定した頂点グループにウェイトが乗っている頂点は、判定結果に関わらず常に削除対象から除外されます。"
            "口の中・目の周りなど、シェイプキーで表情を変えたときに見える可能性がある部分の保護に使用してください"
        ),
        default="",
    )


_classes = (AMT_HiddenMeshProperties,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.amt_hidden_mesh = bpy.props.PointerProperty(type=AMT_HiddenMeshProperties)


def unregister():
    del bpy.types.Scene.amt_hidden_mesh
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
