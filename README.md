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

## Cấu trúc

```
shaders/GNTAnime.ogsfx      shader chính (2 technique: Anime, AnimeOutline)
scripts/gntshader/
    core/env.py             đường dẫn, tên color set
    core/plugin.py          nạp glslShader, kiểm tra renderer
    core/shader.py          tạo/gán/query node GLSLShader, head basis
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

Shader đọc hai color set, **thứ tự tạo quyết định binding**:

| Binding | Color set | Nội dung |
|---|---|---|
| COLOR0 | `GNT_paint` | R = hệ số dày outline, G = AO |
| COLOR1 | `GNT_smoothNormal` | RGB = smooth normal ở tangent space |

`Prepare Selected Meshes` tạo đúng thứ tự. Nút `Check Colour Sets` để kiểm tra lại.

---

## Trạng thái

**v0.1** — đã chạy thử trong Maya 2024 (OpenGL Core Profile).

Đã xác minh:

- Effect **compile sạch**, diagnostics rỗng — 2 technique (`Anime`, `AnimeOutline`),
  97 uniform, 14 UI group, 3 slot đèn bind đúng.
- Vertex stream bind đủ: `Position, Normal, Color0, Tangent, Binormal, TexCoord0, TexCoord1`.
- Bake smooth normal chạy đạt trên cube / sphere / torus; round-trip octahedral sai số 0.
- **Outline pass chạy thật.** Maya *có* thực thi cả hai pass cùng khai báo
  `drawContext = "colorPass"`. Đo bằng cách đếm pixel: cùng một probe, đổi technique,
  pixel đỏ đi từ **0 → 625**, vùng phủ từ 7604 → 8189. Không cần fallback nhân đôi mesh.

Chạy lại bất cứ lúc nào:

```python
PROJECT_ROOT = r"D:/path/to/GNTShader"
exec(open(PROJECT_ROOT + "/validate.py").read())
```

Kết quả cũng được ghi ra `validate_result.txt` cạnh repo.

Chạy lại phép đo outline bất cứ lúc nào (không cần nhìn viewport — nó render hai lần
rồi đếm pixel đỏ):

```python
PROJECT_ROOT = r"D:/path/to/GNTShader"
exec(open(PROJECT_ROOT + "/verify_outline.py").read())
```

Kết quả ghi ra `verify_outline_result.txt`.

**Còn phải lưu ý:**

- **Backface culling** — nếu bật trên object thì outline biến mất, vì pass outline giữ
  mặt sau bằng `gl_FrontFacing` chứ không phải bằng render state (OGSFX không có).
- **Chưa đo** mức độ smooth normal thực sự vá được vết nứt viền ở cạnh cứng so với
  dùng normal thường.

### Hai ràng buộc của Maya đã phải xử lý

| Vấn đề | Cách xử lý |
|---|---|
| OGSFX không có render-state block, nên không viết được `Cull Front` | Đẩy hull ra rồi `if (gl_FrontFacing) discard;` trong pixel shader |
| `glslShader` chỉ bind **một** colour stream — khai báo `COLOR1` compile được nhưng varying bị bỏ im lặng | Encode smooth normal octahedral thành 2 float, nhét vào UV set thứ hai (`TEXCOORD1`) |

---

## Hướng tiếp theo

- Xác minh trong Maya GUI, sửa lỗi compile nếu có
- Fallback outline bằng mesh nhân đôi
- Shader riêng cho mắt (parallax iris, highlight xoay theo camera)
- Xuất preset sang Unity URP để khớp look giữa Maya và engine
