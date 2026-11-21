# 图像流工作流：商品图批量处理

## 流程
```
原图上传 → 背景检测 → 抠图/背景替换 → 尺寸规范化 → 水印/品牌元素叠加 → 质检(分辨率/清晰度) → 输出多平台尺寸
```

## 节点说明
1. **质检前置**：分辨率低于 1000px 的图片标记为"需重拍"。
2. **背景统一**：白底图按平台要求（如 Amazon 纯白背景）处理。
3. **多尺寸输出**：主图 1:1、详情图 9:16 与 3:4，按平台规格导出。
4. **并发控制**：批量任务使用队列，限制并发数避免接口限流。

## 示例代码（Python 批处理骨架）
```python
from pathlib import Path
from PIL import Image

SIZES = {"main": (2000, 2000), "detail": (1200, 1600)}

def to_white_background(img: Image.Image) -> Image.Image:
    # 示意：实际可接入抠图模型（如 rembg）
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
    return bg

def process(src: Path, out_dir: Path):
    img = Image.open(src)
    if min(img.size) < 1000:
        return f"{src.name}: 分辨率不足，需重拍"
    for name, size in SIZES.items():
        out = to_white_background(img).resize(size, Image.LANCZOS)
        out.save(out_dir / f"{src.stem}_{name}.jpg", quality=92)
    return f"{src.name}: OK"

if __name__ == "__main__":
    out = Path("output"); out.mkdir(exist_ok=True)
    for p in Path("input").glob("*.jpg"):
        print(process(p, out))
```

## 运行说明
**环境要求**：Python 3.9+，`pip install pillow`。

**目录准备**：在脚本同级目录建立 `input/` 文件夹，放入待处理的 **`.jpg`** 文件（脚本只匹配 `*.jpg`）。运行后会自动创建 `output/`。

**运行方式**：
```bash
python process_images.py   # 将上方示例保存为该文件名
```

**可调参数**：
- `SIZES`：输出尺寸字典，可按平台规格修改。
- `process` 中的 `1000`：最小边长阈值，低于该值判定为需重拍。
- 白底合成仅为示意；若需精确抠图，可替换为 `rembg` 等模型。

## 示例输入输出
**输入**：`input/` 目录下两张图片

| 文件 | 尺寸 |
|---|---|
| `good.jpg` | 1200 × 1500 |
| `small.jpg` | 800 × 800 |

**控制台输出**（已实际运行验证）：
```text
good.jpg: OK
small.jpg: 分辨率不足，需重拍
```

**输出目录 `output/`**：
| 文件 | 尺寸 | 模式 |
|---|---|---|
| `good_main.jpg` | 2000 × 2000 | RGB，白底 |
| `good_detail.jpg` | 1200 × 1600 | RGB，白底 |

`small.jpg` 因最短边 800 < 1000 未生成任何输出文件。
