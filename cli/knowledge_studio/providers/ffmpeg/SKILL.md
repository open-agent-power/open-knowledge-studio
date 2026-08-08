# FFmpeg Provider

媒体探测与处理。不负责 ASR、OCR、Candidate 生成。

## 关键帧

```bash
ffmpeg -i video.mp4 -vf "select=gt(scene\,0.4)" -vsync vfr frames/%04d.png
```
