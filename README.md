# GNTShader

Anime / cel shader chạy real-time trong **Maya Viewport 2.0**, viết bằng OGSFX (GLSL),
đóng gói thành Maya module có UI và preset.

Mô hình shading tổng hợp hai trường phái anime real-time: **specular nhuộm màu qua ramp,
rim mask theo hướng lên, rim mũi/má theo hướng camera, outline đứt nét bằng noise** (kiểu
Granblue Fantasy Relink), và **face SDF shadow theo hướng đèn** (kiểu Genshin). Hai cách làm
mặt bổ sung nhau nên shader hỗ trợ cả hai.

---

## Cài đặt

Chạy trong Script Editor của Maya (tab Python), sửa đường dẫn thành nơi bạn clone repo:

```python
PROJECT_ROOT = r"D:/path/to/GNTShader"
exec(open(PROJECT_ROOT + "/install.py").read())
```

Script ghi `GNTShader.mod` vào thư mục modules của Maya và thêm luôn vào `sys.path`
để dùng được ngay, không cần khởi động lại.

Sau đó:

```python
import gntshader
gntshader.show()
```

Yêu cầu: Maya 2024 hoặc 2027, plugin `glslShader`, và Viewport 2.0 đặt ở
**OpenGL Core Profile** (`Preferences > Display > Viewport 2.0 > Rendering engine`).

---

## Quy trình dùng

1. **Chuẩn bị mesh** — chọn mesh → `Prepare Selected Meshes`.
   Bake smooth normal (trung bình theo trọng số góc, đưa về tangent space) vào color set
   để viền outline không bị nứt ở cạnh cứng.
2. **Tạo shader** — chọn effect ở dropdown `Effect` (`GNTAnime.ogsfx` cho thân/tóc/mặt,
   `GNTAnimeEye.ogsfx` cho mắt), bấm `Create`, rồi `Assign to Selection`.
3. **Chọn preset** — danh sách chỉ hiện preset hợp với effect đang chạy, nên không áp
   nhầm preset mắt lên shader thân.
4. **Chỉnh chi tiết** — bấm `Attr Editor`. Toàn bộ tham số đã được nhóm sẵn
   (Base / Shading / ILM / Specular / Hair / Face / Rim / Emission / MatCap / Outline).
5. **Mặt** — chọn joint đầu → `Link (live)` để shader biết hướng trước/phải của đầu.
   Cần cho cả face rim (GBFR) lẫn SDF shadow (Genshin).

Không dùng UI:

```python
from gntshader.core import shader, presets
from gntshader.utils import mesh

mesh.prepare_selection()
node, sg = shader.create()
shader.assign(node)
presets.apply(node, "gbfr_like")
```

---

## Cấu trúc

```
shaders/GNTAnime.ogsfx      shader thân/tóc/mặt (2 technique: Anime, AnimeOutline)
shaders/GNTAnimeEye.ogsfx   shader mắt (technique AnimeEye)
scripts/gntshader/
    core/env.py             đường dẫn, tên color set
    core/plugin.py          nạp glslShader, kiểm tra renderer
    core/shader.py          tạo/gán/query node GLSLShader, head basis
    core/presets.py         lưu & nạp preset JSON
    utils/mesh.py           bake smooth normal (port từ SmoothNormal.cs)
    utils/qt.py             shim PySide2 / PySide6
    ui/main_window.py       cửa sổ công cụ
presets/*.json              4 preset khởi điểm
tests/                      test headless
validate.py                 kiểm tra shader compile (chạy trong Maya GUI)
install.py                  ghi file .mod vào thư mục modules của Maya
GNTShader.mod               mẫu module (install.py tự sinh bản có đường dẫn thật)
```

---

## Shader mắt

Mắt cần mô hình riêng nên tách thành `GNTAnimeEye.ogsfx`, không nhồi vào shader chính:

- **Iris parallax** — dịch UV iris theo hướng nhìn trong tangent space, làm mống mắt như
  nằm sau giác mạc. `ParallaxSign` đổi giữa lõm (mặc định) và lồi.
- **Highlight trượt theo người xem** — `HighlightFollowView` từ 0 (dính chặt vào mesh)
  đến 1 (trượt như phản chiếu thật). Có xoay, có scale, và catchlight thứ hai nhỏ hơn.
- **Iris ramp** dọc, **limbal ring**, pupil chỉnh được size/softness.
- **Bóng mí mắt** — gradient tối dần ở đỉnh nhãn cầu.
- `Unlit` để tắt hẳn ảnh hưởng đèn scene, kiểu mắt phẳng của anime.

Trong UI: chọn `GNTAnimeEye.ogsfx` ở dropdown `Effect` rồi `Create`. Bằng Python:

```python
from gntshader.core import shader, presets, env
node, sg = shader.create(name="GNTEye", shader_file=env.EYE_SHADER,
                         technique="AnimeEye")
shader.assign(node)
presets.apply(node, "eye_default")
```

Preset giờ có trường `shader` ghi rõ nó thuộc effect nào. Áp preset mắt lên shader thân
thì mọi key đều trượt và look sẽ sai mà không báo gì — nên `presets.apply()` cảnh báo
khi preset không khớp shader đang chạy, và test `test_shader_contract.py` chặn từ đầu.

---

## Vertex streams

| Stream | Nguồn | Nội dung |
|---|---|---|
| `COLOR0` | color set `GNT_paint` | R = hệ số dày outline, G = AO |
| `TEXCOORD0` | UV set gốc của mesh | UV texture |
| `TEXCOORD1` | UV set `GNT_smoothNormal` | smooth normal, octahedral, tangent space |

**Bind theo tên, không theo thứ tự.** Maya cho mỗi stream một attribute
`<stream>_Source` chứa chuỗi kiểu `uv:map1` / `color:colorSet`. Mặc định đúng là những
tên đó — mà mesh production hiếm khi đặt tên vậy: mesh GGXrd tôi thử có `UV1`, `UV2`, `Col`,
nên nếu dựa vào thứ tự thì shader sẽ đọc `UV2` của nhân vật thay cho smooth normal và đọc
`Col` thay cho paint set, **sai hoàn toàn mà không báo lỗi gì**.

`shader.assign()` tự gọi `bind_streams()` để nối đích danh. Gọi tay khi cần:

```python
from gntshader.core import shader
shader.bind_streams(node, "body_geo")
print(shader.stream_bindings(node))
```

## Normal map

Cel shading và normal map vốn xung khắc: dải bóng là một ngưỡng cứng, nên xáo trộn normal
sẽ **xé vụn đường terminator thành lốm đốm**. Genshin và GGXrd phần lớn giữ dải bóng chạy
theo normal hình học, chỉ để normal map điều khiển highlight.

Nên shader tách làm hai: `N` (có chi tiết) dùng cho specular / rim / matcap, còn `Nband`
dùng cho ngưỡng cel — bị kéo về normal hình học theo núm **`Affects Cel Band`**.

| `Affects Cel Band` | stddev độ sáng | Nghĩa là |
|---|---|---|
| 0.00 | 24.00 | terminator sạch tuyệt đối, khối chỉ hiện ở specular |
| 0.25 *(mặc định)* | 26.12 | có khối nhẹ ở dải bóng |
| 0.50 | 31.79 | |
| 1.00 | 45.77 | normal map cắt thẳng vào dải bóng, terminator vỡ |

`Normal Strength` đo được +3% / +7% / +12% chi tiết ở mức 0.5 / 1.0 / 2.0.

### Không gian normal map

`Normal Space`: **0 = Tangent, 1 = Object, 2 = World**.

Tangent space bám theo bề mặt nên sống sót qua biến dạng — đó là lý do nó là mặc định cho
nhân vật có skinning. Object và world space lưu **hướng tuyệt đối**: rẻ hơn (không cần
khung tangent) và miễn nhiễm với UV seam xấu, nhưng chúng được bake theo **một tư thế duy
nhất**.

Đo bằng map phẳng `(0,0,1)` trên quả cầu, đèn chiếu vào mặt trước:

| Chế độ | stddev | Ghi chú |
|---|---|---|
| Tắt | 39.77 | |
| Tangent | 39.75 | **bằng đúng lúc tắt** — map phẳng là no-op, đúng như phải thế |
| Object | 0.00 | cả vật nhận một normal hằng số |
| World | 0.00 | như trên |

Xoay quả cầu 90° quanh Y:

| Chế độ | % sáng | |
|---|---|---|
| Object | 0.0% | normal **xoay theo vật**, quay khỏi đèn nên vào bóng |
| World | 100% | **không đổi**, phớt lờ phép xoay |

Đó chính là ranh giới cần nhớ: object space đi theo vật, world space thì không. Cả hai
đều **hỏng khi mesh bị skinning** — nhân vật động thì dùng tangent space.

Với object/world space, `Normal Strength` là hệ số **pha trộn** với normal hình học
(0…1), không phải hệ số nhân thành phần ngang như ở tangent space.

`Flip Green` cho normal map kiểu DirectX (Unreal, nhiều bake game). Maya và Substance
xuất kiểu OpenGL nên để tắt. Sai cờ này thì mọi vết lõm thành vết lồi. Chỉ có tác dụng
với tangent space.

Normal map **phải nạp ở colour space `Raw`**, không phải sRGB:

```python
shader.set_texture(node, "NormalMap", "D:/tex/normal.png", colour_space="Raw")
```

## Texture

Uniform texture **không phải string** — Maya sinh ra chúng dưới dạng `float3` connectable
(`_Type = "texture"`), nên phải nối một `file` node vào:

```python
shader.set_texture(node, "AlbedoMap", "D:/tex/base.png")
shader.set_texture(node, "LightMap", "D:/tex/ilm.png", colour_space="Raw")
```

`set_param()` tự nhận ra và chuyển hướng khi bạn đưa vào một đường dẫn.

---

## Trạng thái

**v0.1** — đã chạy thử trong Maya 2024 (OpenGL Core Profile).

Đã xác minh:

- Effect **compile sạch**, diagnostics rỗng — 2 technique (`Anime`, `AnimeOutline`),
  97 uniform, 14 UI group, 3 slot đèn bind đúng.
- Vertex stream bind đủ: `Position, Normal, Color0, Tangent, Binormal, TexCoord0, TexCoord1`.
- Bake smooth normal chạy đạt trên cube / sphere / torus; round-trip octahedral sai số 0.
- **Cả hai shader compile sạch** trong Maya 2024: `GNTAnime.ogsfx` 2 technique / 97 uniform,
  `GNTAnimeEye.ogsfx` 1 technique / 47 uniform, diagnostics rỗng.
- **Outline pass chạy thật.** Maya *có* thực thi cả hai pass cùng khai báo
  `drawContext = "colorPass"`. Đo bằng cách đếm pixel: cùng một probe, đổi technique,
  pixel đỏ đi từ **0 → 1033**. Không cần fallback nhân đôi mesh.
- **Viền sạch hoàn toàn**, đo trên cube (mọi cạnh đều cứng), với mặc định hiện tại:

  | | Viền (ngoài silhouette) | Nứt (trong silhouette) |
  |---|---|---|
  | Normal thường | 1003 px | **159 px** |
  | Smooth normal | 964 px | **0 px** |

  Lưu ý cách đo: đẩy theo face normal làm 6 mặt tách rời, và khe giữa chúng cũng lòi đỏ —
  nên **tổng** diện tích đỏ là chỉ số sai, nó đếm vết nứt như thể là viền. Phải tách đỏ
  ngoài silhouette (viền thật) khỏi đỏ trong silhouette (nứt).

- **`OutlineZOffset` mặc định 2**, tìm ra bằng cách quét:

  | zOffset | Viền | Nứt |
  |---|---|---|
  | 0 | 964 | 69 |
  | 1 | 964 | 8 |
  | **2** | 964 | **0** |
  | 5 · 10 · 40 | 964 | 0 |

  Đơn vị là số nguyên (1 đơn vị = 0.0001 clip space) cho dễ chỉnh. Dương đẩy vỏ hull ra
  xa, âm kéo ra trước (viền luôn nằm trên).

  Hai biện pháp này **bổ sung nhau, không thay thế**: z-offset trị tranh chấp depth ở
  cạnh gần song song hướng nhìn; smooth normal trị lỗ hổng hình học do mặt tách rời.
  Normal thường vẫn còn 159 px nứt *dù đã có z-offset*, vì đó là lỗ thật.

Chạy lại bất cứ lúc nào:

```python
PROJECT_ROOT = r"D:/path/to/GNTShader"
exec(open(PROJECT_ROOT + "/validate.py").read())
```

Kết quả cũng được ghi ra `validate_result.txt` cạnh repo.

### Test

Phần không cần GPU thì test được headless, không cần mở Maya. Cả hai đều trả exit code
nên cắm vào CI được.

**Lint shader** — Python thuần, bắt lỗi *trước* khi phải mở Maya:

```bash
python tests/test_shader_lint.py
```

Maya chỉ parse effect khi Viewport 2.0 có draw context thật, nên shader vừa viết xong sẽ
nằm im không ai kiểm cho tới lúc có người mở GUI. Linter khoả lấp phần đó: token sampler
Maya thật sự nhận, varying gọi qua `VS_OUT`/`PS_IN` mà attribute block không khai báo,
vertex input thiếu trong `APPDATA`, pass nối vào block không tồn tại, và pixel output có
được ghi không.

Token sampler là bài học có thật: `CLAMP_TO_BORDER` không xuất hiện trong bất kỳ shader
nào Maya ship, và OGSFX không có cú pháp đặt border colour. Danh sách token hợp lệ giờ
nằm trong linter chứ không nằm trong trí nhớ ai cả.

**Khớp tên giữa shader / preset / UI** — cũng Python thuần:

```bash
python tests/test_shader_contract.py
```

Lý do tồn tại: key preset không khớp uniform thì lúc chạy bị bỏ qua kèm một cảnh báo rất
dễ trôi, preset trông như đã áp dụng mà look thực ra sai. Test đối chiếu mọi key preset,
mọi slider trong UI, và tên uniform mà code Python gọi, với uniform thật khai báo trong
`.ogsfx`. Kèm chốt chặn hồi quy: cấm khai báo `COLOR1` trong `APPDATA`.

**Bake smooth normal** — cần `mayapy` (dùng OpenMaya, không cần GUI):

```bash
"C:/Program Files/Autodesk/Maya2024/bin/mayapy.exe" tests/test_mesh_roundtrip.py
```

Kiểm 5 loại mesh (cube toàn cạnh cứng, sphere, torus, cylinder, cone có đỉnh suy biến):
octahedral round-trip, bake → đọc lại từ mesh → giải mã đúng phép toán của shader, và
UV set / colour set có rơi đúng vào `TEXCOORD1` / `COLOR0` không. Sai số lớn nhất hiện
là **0.000000** ở cả 5 loại.

Phần cần GPU thì chạy trong Maya. Đo outline (render hai lần rồi đếm pixel đỏ, không cần
nhìn viewport):

```python
PROJECT_ROOT = r"D:/path/to/GNTShader"
exec(open(PROJECT_ROOT + "/verify_outline.py").read())
```

Kết quả ghi ra `verify_outline_result.txt`.

**Còn phải lưu ý:**

- **Backface culling** — nếu bật trên object thì outline biến mất, vì pass outline giữ
  mặt sau bằng `gl_FrontFacing` chứ không phải bằng render state (OGSFX không có).
- Bake và shader đều trực chuẩn hoá khung tangent (Gram-Schmidt) trước khi mã hoá /
  giải mã. Trên primitive của Maya thì **không cần** — đo được tangent lệch vuông góc
  đúng 0.0000°. Giữ lại để phòng mesh nhân vật unwrap tay có UV méo; nếu gặp viền dày
  mỏng thất thường thì đây là chỗ đáng nghi đầu tiên.
- Mọi con số ở trên đo trên primitive. **Chưa chạy trên mesh nhân vật thật** — nơi UV
  unwrap tay, có skinning, và normal map cùng tác động.

### Ba ràng buộc của Maya đã phải xử lý

| Vấn đề | Cách xử lý |
|---|---|
| OGSFX không có render-state block, nên không viết được `Cull Front` | Đẩy hull ra rồi `if (gl_FrontFacing) discard;` trong pixel shader |
| `glslShader` chỉ bind **một** colour stream — khai báo `COLOR1` compile được nhưng varying bị bỏ im lặng | Encode smooth normal octahedral thành 2 float, nhét vào UV set thứ hai (`TEXCOORD1`) |
| **Maya cache effect đã compile theo đường dẫn file** — sửa `.ogsfx` rồi gán cho node mới vẫn có thể nhận bản build cũ, không cảnh báo gì | `set_shader_file()` xoá attribute rồi mới đặt lại, buộc compile lại |

Cái thứ ba nguy hiểm nhất vì nó im lặng: nó từng làm hỏng nguyên một đợt đo — shader
đang chạy là bản cũ, còn số liệu thì trông y như một lỗi dấu trong công thức. Nếu bạn sửa
shader mà viewport không đổi gì, nghi chỗ này trước tiên.

### Khai báo đèn phải có `Space = "World"`

Uniform đèn bắt buộc mang **cả `UIName` lẫn `Space = "World"`**, đúng như
`AutodeskUberShader.ogsfx`. Thiếu `Space` trên `DIRECTION` thì Maya không phân loại được
tham số, và **GLSL nhận giá trị 0** — đèn trong scene không đóng góp gì hết, trong khi
Attribute Editor vẫn hiện số liệu hoàn toàn bình thường.

Triệu chứng: xoay đèn không thay đổi gì, và nhân vật vẫn sáng đều kể cả khi đèn ở sau
lưng — vì toàn bộ độ sáng đến từ `ShadowColor` và `AmbientColor` chứ không từ đèn.

Đo trước khi sửa: quả cầu đọc **0% sáng ở mọi hướng đèn**. Sau khi sửa: 89.7% khi đèn
chiếu vào mặt, 0.0% khi đèn ở sau lưng.

Lưu ý chẩn đoán: attribute **vẫn** hiện kiểu `matrix` và `GLSLShader -q -li` **vẫn** báo
`undefined` kể cả sau khi đã sửa. Đó là triệu chứng, không phải nguyên nhân — đừng đuổi
theo chúng như tôi đã làm.

### Bóng vẫn sáng là do `ShadowColor`, không phải rò sáng

Cel shading dùng bóng là một **màu**, không phải chỗ tối. Với `ShadowColor` mặc định
(0.62, 0.58, 0.68), nhân vật nằm hoàn toàn trong bóng vẫn sáng ~62%. Đo phân rã trên
nhân vật khi đèn ở sau lưng:

| Thành phần | Đóng góp độ sáng |
|---|---|
| `ShadowColor` | **125.7** (75%) |
| `AmbientColor` | 34.7 (21%) |
| Rim | 6.2 (4%) |
| Specular | 0 |

Muốn bóng sâu hơn thì hạ `ShadowColor` trước, rồi `AmbientColor`. `RimFollowLight` mặc
định 0.25 nghĩa là rim vẫn giữ 75% cường độ ở phía không có đèn — nâng lên gần 1.0 nếu
muốn rim chỉ xuất hiện bên được chiếu sáng.

---

## Hướng tiếp theo

- Xác minh trong Maya GUI, sửa lỗi compile nếu có
- Fallback outline bằng mesh nhân đôi
- Shader riêng cho mắt (parallax iris, highlight xoay theo camera)
- Xuất preset sang Unity URP để khớp look giữa Maya và engine
