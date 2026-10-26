# EchoRadio one-shot segmenter (generated). Encodes a source into 10 s MPEG-TS/AAC
# segments as fast as possible, then exits. Used for fallback audio sets and for
# migrating v1 hourly recordings.
settings.log.file := false
settings.log.stdout := true
settings.log.level := 2

enc = %ffmpeg(format="mpegts", %audio(codec="aac", b="$bitrate", ar=44100, channels=2))

$source_def

clock.assign_new(sync="none", [s])

# Stop after this many segments (0 = until the source ends).
max_segments = $max_segments

def segment_name(m) =
  if max_segments > 0 and m.position >= max_segments then
    thread.run(delay=0.5, fun () -> shutdown())
  end
  $name_expr
end

output.file.hls(fallible=true, segment_duration=10., segments=1000000, segments_overhead=null,
  persist_at="state.json", playlist="main.m3u8", segment_name=segment_name,
  "$out_dir", [("index", enc)], s)

# Stop once the source has nothing left to play.
thread.run(delay=3., every=0.5, fun () -> if not s.is_ready() then shutdown() end)
