# yt-dlp Provider

视频元数据与字幕下载。Bilibili Cookie 字幕 7/10 已验证。

## 调用

```bash
yt-dlp --write-auto-subs --sub-langs 'zh.*,ai-zh,en.*' --skip-download <url>
```

## 输出

- 字幕 .srt / .vtt → subtitle artifact
- 元数据 JSON → metadata artifact

## 限制

不负责 ASR、OCR、关键帧理解、Candidate 生成。
