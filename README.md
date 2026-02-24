# BiliDown 工具集

B站视频下载与PPT截图提取工具集。

## 脚本列表

| 脚本 | 功能 |
|------|------|
| [biliDown.py](biliDown.py) | B站视频下载器 |
| [pickImgFromVideo.py](pickImgFromVideo.py) | PPT/录屏视频关键帧提取器 |

---

## biliDown.py

B站视频下载脚本，支持单视频、合集下载及时间裁剪。

### 功能特性

- 支持 BV号 和 AV号 格式URL
- 支持单视频和合集视频下载
- 支持时间范围裁剪（需 ffmpeg）
- 支持1080P高清下载
- 支持中文文件名

### 依赖

```bash
pip install requests
```

时间裁剪功能需要安装 [ffmpeg](https://ffmpeg.org/) 并添加到 PATH。

### 使用方法

```bash
# 基本下载
python biliDown.py "https://www.bilibili.com/video/BV1xxxx"

# 指定输出目录
python biliDown.py "https://www.bilibili.com/video/BV1xxxx" -o "./my_videos"

# 裁剪视频（从30秒到90秒）
python biliDown.py "https://www.bilibili.com/video/BV1xxxx" -s 30 -e 90
python biliDown.py "https://www.bilibili.com/video/BV1xxxx" -s 00:00:30 -e 00:01:30

# 仅设置起始时间（下载到视频末尾）
python biliDown.py "https://www.bilibili.com/video/BV1xxxx" -s 130

# 下载整个合集
python biliDown.py "https://www.bilibili.com/video/BV1xxxx" -c

# 下载合集指定范围（第2到第5P）
python biliDown.py "https://www.bilibili.com/video/BV1xxxx" -p 2 -P 5

# 下载指定分P
python biliDown.py "https://www.bilibili.com/video/BV1xxxx?p=3"
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `url` | B站视频URL（必需） |
| `-o, --output` | 输出目录，默认 `./downloads` |
| `-s, --start` | 起始时间，格式：`HH:MM:SS` 或 `MM:SS` 或秒数 |
| `-e, --end` | 结束时间，格式同上 |
| `-p, --start-p` | 合集起始P号 |
| `-P, --end-p` | 合集结束P号 |
| `-c, --collection` | 下载整个合集 |

---

## pickImgFromVideo.py

从PPT录屏视频中智能提取关键帧截图。

### 功能特性

- 使用感知哈希(pHash)检测PPT页面切换
- 自适应阈值，自动调整检测灵敏度
- 智能选取最清晰的关键帧
- 支持批量处理多个视频
- 支持中文路径和文件名
- 自动生成处理报告

### 依赖

```bash
pip install opencv-python numpy
```

### 使用方法

**方式一：修改脚本配置运行**

```python
if __name__ == "__main__":
    config = VideoConfig(
        min_scene_duration=1.0,    # 每页最小持续时间(秒)
        hash_threshold=0.92,       # 相似度阈值(0-1，越大越敏感)
        check_interval=10          # 检查间隔
    )

    processor = PPTVideoProcessor(config)

    # 处理单个视频
    processor.process_single(Path("视频路径.mp4"), Path("输出目录"))

    # 批量处理
    processor.process_batch(
        input_dir="downloads",      # 视频目录
        output_dir="screenshots"    # 输出目录
    )
```

**方式二：作为模块导入**

```python
from pickImgFromVideo import PPTVideoProcessor, VideoConfig
from pathlib import Path

config = VideoConfig(
    min_scene_duration=1.0,
    hash_threshold=0.85
)

processor = PPTVideoProcessor(config)

# 处理单个视频
result = processor.process_single(
    Path("my_video.mp4"),
    Path("output")
)

# 批量处理
results = processor.process_batch(
    input_dir="./videos",
    output_dir="./screenshots"
)
```

### 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `min_scene_duration` | 1.0 | 最小场景持续时间(秒)，避免检测到动画过渡 |
| `hash_threshold` | 0.85 | 感知哈希相似度阈值，越小越敏感 |
| `check_interval` | 10 | 每N帧检查一次，影响处理速度 |

### 输出结构

```
screenshots/
├── 视频1/
│   ├── 视频1_page01_t3.5s.png
│   ├── 视频1_page02_t8.2s.png
│   └── ...
├── 视频2/
│   └── ...
└── processing_report.json
```

### 调优建议

- **检测不到切换**：降低 `hash_threshold`（如 0.75）
- **检测到过多切换**：提高 `hash_threshold`（如 0.92）或增加 `min_scene_duration`
- **处理速度慢**：增加 `check_interval`