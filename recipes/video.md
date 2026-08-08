# Recipe: Video

source_type: video
description: Platform videos (Bilibili, YouTube, Douyin) and local video files.

required_capabilities:
  - subtitle.fetch
  - metadata.fetch

optional_capabilities:
  - media.download
  - media.probe
  - audio.extract
  - video.keyframes
  - speech.transcribe
  - image.observe
  - chart.interpret
  - layout.understand

complete_when:
  - subtitles_or_transcript_available
  - metadata_title_and_duration_recorded
  - keyframes_extracted_if_visual_content_significant

remote_processing:
  policy_required: true

degradation:
  - priority: 1
    capability: metadata.fetch
    condition: default
    note: "Platform metadata — title, duration, format."
  - priority: 2
    capability: subtitle.fetch
    condition: subtitles_available
    note: "Extract or download subtitles. May require platform authentication. When subtitle.fetch fails, speech.transcribe (priority 4, ASR) is the automatic fallback — a successful ASR transcript satisfies complete_when: subtitles_or_transcript_available. Do NOT mark the ingest as partial for missing subtitles when ASR produced a valid transcript."
  - priority: 3
    capability: video.keyframes
    condition: media_file_available
    note: "Extract representative frames at scene changes or intervals."
  - priority: 4
    capability: speech.transcribe
    condition: audio_extractable
    note: "ASR when no subtitles available. Local or remote Provider."
  - priority: 5
    capability: human.supply
    condition: all_automated_failed
notes: |
  Bilibili: yt-dlp with Cookie (7/10 verified). AgentKey API returns metadata
  (title, BV, aid/cid) but NO subtitle body — metadata_only, not text success.
  YouTube: blocked in PRC network environment. Douyin: not yet tested.
  Local video: ffmpeg extracts audio and keyframes. Agent-runtime understands
  visual content from keyframes. ASR generates transcript from audio.
  Without video files or keyframes, content is limited to subtitles + metadata.
  Video capability is the most complex — last to fully automate.
