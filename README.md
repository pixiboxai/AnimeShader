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
2. **Tạo shader** — `Create`, rồi `Assign to Selection`.
3. **Chọn preset** — `genshin_like`, `gbfr_like`, hoặc `mmd_like`.
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

## Outline: hai đường, dùng đường nào

Technique `AnimeOutline` vẽ outline bằng **pass thứ hai** trong cùng một effect.
Cả hai pass đều khai `drawContext = "colorPass"`, và Autodesk không tài liệu hoá
việc Maya có chạy cả hai hay không. Nếu Maya chỉ chạy pass đầu thì outline biến
mất — im lặng, không lỗi, không diagnostics.

Nên có đường thứ hai không phụ thuộc vào điều đó: **hull nhân đôi**. Mỗi mesh
được gắn thêm một mesh con, nối `outMesh → inMesh`, gán technique `OutlineOnly`.
Mỗi effect chỉ còn một colorPass.

Trong UI, nhóm `Outline Fallback`:

| Nút | Việc |
|---|---|
| `Build Hulls` | tạo hull cho mesh đang chọn, chuyển shader chính về `Anime`, copy các uniform outline sang shader hull |
| `Remove` / `Remove All` | gỡ hull của selection / của cả scene |
| `Sync Params` | copy lại uniform outline sau khi chỉnh tay (hai shader là hai node riêng) |

Không dùng UI:

```python
from gntshader.core import outline, shader

outline.build_selection()          # hull cho mọi mesh đang chọn
shader.set_technique(node, "Anime")  # tắt pass outline của shader chính
outline.sync_params(node)          # đẩy thiết lập outline sang shader hull
```

Vài điểm về cách hull được dựng, vì chúng quyết định hull "sống" hay "chết":

- Hull lấy mesh qua **plug** chứ không phải bản sao tĩnh, nên skinning, UV set
  và color set chảy theo — smooth normal đã bake dùng lại được, không cần
  scriptJob đồng bộ.
- Hull là **con của chính transform nguồn**, nên world matrix trùng nhau. Nhờ
  vậy `gWorldXf` và toạ độ object-space mà outline noise lấy mẫu giống hệt
  đường multi-pass — fallback *trùng* look chứ không phải xấp xỉ. Ẩn hoặc xoá
  nhân vật cũng kéo theo outline.
- Hull tắt `castsShadows` / `receiveShadows` (nó phình to hơn mesh thật) và đặt
  display type `reference` để không click trúng trong viewport.

Đừng bật cả hai cùng lúc: `AnimeOutline` + hull sẽ vẽ outline hai lần. `Build
Hulls` tự chuyển shader chính về `Anime` để tránh việc đó.

---

## Cấu trúc

```
shaders/GNTAnime.ogsfx      shader chính (3 technique: Anime, AnimeOutline, OutlineOnly)
scripts/gntshader/
    core/env.py             đường dẫn, tên color set
    core/plugin.py          nạp glslShader, kiểm tra renderer
    core/shader.py          tạo/gán/query node GLSLShader, head basis
    core/outline.py         hull nhân đôi (fallback outline một pass)
    core/presets.py         lưu & nạp preset JSON
    utils/mesh.py           bake smooth normal (port từ SmoothNormal.cs)
    utils/qt.py             shim PySide2 / PySide6
    ui/main_window.py       cửa sổ công cụ
presets/*.json              3 preset khởi điểm
validate.py                 kiểm tra shader compile (chạy trong Maya GUI)
install.py                  ghi file .mod vào thư mục modules của Maya
GNTShader.mod               mẫu module (install.py tự sinh bản có đường dẫn thật)
```

---

## Vertex streams

Shader đọc một color set và một UV set phụ, **thứ tự tạo quyết định binding**:

| Binding | Set | Nội dung |
|---|---|---|
| COLOR0 | color set `GNT_paint` | R = hệ số dày outline, G = AO |
| TEXCOORD1 | UV set `GNT_smoothNormal` | smooth normal tangent-space, mã hoá octahedral thành 2 float |

Smooth normal nằm ở UV set chứ không phải color set thứ hai — lý do ở bảng
"Hai ràng buộc của Maya" bên dưới. `Prepare Selected Meshes` tạo đúng thứ tự,
nút `Check Colour Sets` kiểm tra lại.

---

## Trạng thái

**v0.1** — đã chạy thử trong Maya 2024 (OpenGL Core Profile).

Đã xác minh:

- Effect **compile sạch**, diagnostics rỗng — 2 technique (`Anime`, `AnimeOutline`),
  97 uniform, 14 UI group, 3 slot đèn bind đúng.
- Vertex stream bind đủ: `Position, Normal, Color0, Tangent, Binormal, TexCoord0, TexCoord1`.
- Bake smooth normal chạy đạt trên cube / sphere / torus; round-trip octahedral sai số 0.

Chạy lại bất cứ lúc nào:

```python
PROJECT_ROOT = r"D:/path/to/GNTShader"
exec(open(PROJECT_ROOT + "/validate.py").read())
```

Kết quả cũng được ghi ra `validate_result.txt` cạnh repo.

**Chưa xác minh** — hai điểm cần nhìn viewport bằng mắt:

1. **Multi-pass outline** — chưa rõ Maya có chạy cả hai pass cùng `drawContext = "colorPass"`
   hay không. Không còn là rủi ro chặn đường: nếu Maya bỏ pass thứ hai thì dùng hull nhân
   đôi (`Build Hulls`), mỗi effect một colorPass. Vẫn nên xác minh để biết đường nào là
   mặc định — multi-pass rẻ hơn một draw call và một mesh node cho mỗi object.
2. **Backface culling** — nếu bật trên object thì outline biến mất, vì pass outline giữ
   mặt sau bằng `gl_FrontFacing` chứ không phải bằng render state (OGSFX không có).
   Điều này đúng cho cả hai đường, vì hull cũng chạy `PS_Outline`.

Chạy `check_hull_fallback()` sau `validate.py` để dựng hull trên cube probe và kiểm tra
đường fallback biên dịch sạch.

### Hai ràng buộc của Maya đã phải xử lý

| Vấn đề | Cách xử lý |
|---|---|
| OGSFX không có render-state block, nên không viết được `Cull Front` | Đẩy hull ra rồi `if (gl_FrontFacing) discard;` trong pixel shader |
| `glslShader` chỉ bind **một** colour stream — khai báo `COLOR1` compile được nhưng varying bị bỏ im lặng | Encode smooth normal octahedral thành 2 float, nhét vào UV set thứ hai (`TEXCOORD1`) |

---

## Hướng tiếp theo

- Xác minh trong Maya GUI, sửa lỗi compile nếu có
- ~~Fallback outline bằng mesh nhân đôi~~ — xong, xem mục Outline ở trên
- Shader riêng cho mắt (parallax iris, highlight xoay theo camera)
- Xuất preset sang Unity URP để khớp look giữa Maya và engine
