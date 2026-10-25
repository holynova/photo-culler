# photo-culler — 手机照片批量清理工具（方案 B2）

PC 端评分管线 + 本地 Web 审片界面。手机照片/视频拷贝到 PC 后：

```
scan → analyze (打分/瑕疵/去重) → serve (Web 审片) → apply (安全移入回收站)
```

## 架构

```
photo-culler/
├── src/pcull/
│   ├── __init__.py
│   ├── db.py          # SQLite 索引 (photos/metrics/groups/decisions)
│   ├── scanner.py     # 目录扫描 + EXIF/尺寸/视频元信息
│   ├── analyzers/
│   │   ├── thumbs.py    # 缩略图缓存
│   │   ├── quality.py   # 模糊(Laplacian)/曝光/色彩 分析
│   │   ├── faces.py     # MediaPipe 闭眼检测 (可选依赖)
│   │   ├── dedup.py     # phash 感知哈希去重 + 连拍分组
│   │   └── video.py     # ffmpeg 抽帧 → 走图片质量分析
│   ├── scoring.py     # 综合分 + 清理建议 (keep/review/delete)
│   ├── apply.py       # 安全移动到回收站目录 + 移动清单
│   ├── server.py      # FastAPI: REST API + 静态审片 UI
│   └── cli.py         # pcull scan|analyze|serve|apply|status
├── static/            # 审片 UI (无构建步骤的原生 JS)
├── tests/             # pytest: 合成图片 fixture 驱动
├── tools/             # ffmpeg (复用 ai-video 的 BtbN 构建, 符号链接/复制)
└── docs/              # 截图
```

## 数据模型

- `photos`: id, rel_path, size, mtime, width, height, taken_at, is_video, duration, phash
- `metrics`: photo_id, blur, exposure, colorfulness, faces, eye_open_min, closed_eye, video_frames(json)
- `groups`: phash 聚类的重复/连拍组
- `decisions`: 用户标记 (keep/delete)，优先于机器建议
- `score/recommendation`: 综合分 0-100 + 理由列表 ["模糊","闭眼","过暗","重复组非最佳"...]

## 打分规则 (MVP)

| 检测 | 方法 | 建议影响 |
|---|---|---|
| 模糊 | 下采样灰度 Laplacian 方差 (对数归一化) | 低 → review/delete 候选 |
| 曝光 | 直方图裁剪比例 (过暗/过曝) | 极端 → review |
| 闭眼 | MediaPipe blendshapes eyeBlink (可选) | 有人脸且闭眼 → review/delete |
| 重复/连拍 | phash 汉明距离 ≤ 阈值 聚类 | 组内保留最高分，其余 → review |
| 神经评分 | pyiqa TOPIQ/NIMA (可选 extra，后续接入) | 替换/校准综合分 |

机器只给建议，**删除必须经 UI 人工标记**；apply 永远是移动到回收站目录而非直接删除。

## 分阶段计划 (每阶段带测试)

1. **Phase 1 扫描器**: 目录遍历 + EXIF + SQLite；测试：合成图片库索引正确
2. **Phase 2 分析器**: 模糊/曝光/色彩/闭眼/phash；测试：清晰 vs 高斯模糊图片分数显著分离；复制品聚类成组
3. **Phase 3 打分建议**: 规则引擎；测试：各类瑕疵图片得到预期建议与理由
4. **Phase 4 服务端**: FastAPI + API；测试：TestClient 覆盖各端点
5. **Phase 5 审片 UI**: 网格/筛选/排序/键盘流/分组对比/批量标记；浏览器截图 QA
6. **Phase 6 视频**: ffmpeg 抽帧评分 + 时长/体积排序；端到端演示库
7. **Phase 7 执行与收尾**: apply 移动+清单+撤销信息；README、PROJECTS.md、截图

## 用法 (目标)

```
.venv/Scripts/pcull scan   D:\phone-pics
.venv/Scripts/pcull analyze D:\phone-pics
.venv/Scripts/pcull serve   D:\phone-pics   # http://127.0.0.1:8787
.venv/Scripts/pcull apply   D:\phone-pics   # 移动标记项到 ../_pcull_trash/
```

## 范围外 (后续可选)

- pyiqa 神经评分接入（requirements-neural.txt，代码已预留接口）
- adb 脚本生成（直接清手机端）
- CLIP zero-shot 垃圾图分类、安卓原生客户端（方案 C）
