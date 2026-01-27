
## Research: Silence Detection & Subtitle-Based Video Editing (2026-01-28)

### 1. SILENCE DETECTION IN AUDIO/VIDEO

#### A. Python Libraries

**PyDub** (https://github.com/jiaaro/pydub)
- Most popular Python library for audio manipulation (9.7k stars)
- Built-in silence detection: `detect_silence()` and `detect_nonsilent()`
- Parameters:
  - `min_silence_len`: Minimum length of silence (default 1000ms)
  - `silence_thresh`: Threshold in dBFS (default -16dB)
  - `seek_step`: Step size for detection (default 1ms)
- Returns list of silent/non-silent intervals in milliseconds
- Example usage:
```python
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

audio = AudioSegment.from_file("input.mp4")
nonsilent_ranges = detect_nonsilent(audio, min_silence_len=1000, silence_thresh=-40)
```

**Silero VAD** (https://pypi.org/project/silero-vad/)
- ML-based Voice Activity Detection (latest: v6.2.0, Nov 2025)
- Superior accuracy compared to threshold-based methods
- Real-time capable with low latency
- Uses ONNX Runtime for fast inference
- Better for speech detection vs general audio

**TEN VAD** (https://theten.ai/docs/ten_vad)
- Newest high-performance VAD (2025)
- Real-Time Factor: 0.015 on AMD Ryzen (exceptionally fast)
- Library Size: Only 306KB
- Superior precision vs WebRTC VAD and Silero VAD
- Frame-level speech activity detection

#### B. FFmpeg-Based Silence Detection

**silencedetect filter** (Industry standard)
- Built into FFmpeg, no additional dependencies
- Command pattern:
```bash
ffmpeg -i input.mp4 -af silencedetect=noise=-30dB:d=0.5 -f null -
```
- Parameters:
  - `noise`: Noise tolerance in dB (e.g., -30dB, -40dB)
  - `d`: Minimum silence duration in seconds (e.g., 0.5, 1.0)
- Output format (stderr):
```
[silencedetect @ 0x...] silence_start: 12.345
[silencedetect @ 0x...] silence_end: 15.678 | silence_duration: 3.333
```
- Parse output with regex to extract timestamps
- Used by: Auto-Editor, Unsilence, Jumpcutter, and many others

**Implementation Example** (from unsilence):
```python
command = [
    "ffmpeg", "-i", str(input_file), "-vn",
    "-af", f"silencedetect=noise={silence_level}dB:d={silence_time_threshold}",
    "-f", "null", "-"
]
# Parse stderr for silence_start/silence_end events
```

#### C. Threshold-Based vs ML-Based Approaches

**Threshold-Based (FFmpeg silencedetect, PyDub)**
- Pros:
  - Fast, lightweight, no training needed
  - Predictable behavior
  - Works for any audio (music, speech, ambient)
  - Easy to tune with dB threshold
- Cons:
  - Can miss speech in noisy environments
  - Sensitive to background noise
  - Requires manual threshold tuning
- Best for: Clean recordings, lectures, screencasts

**ML-Based (Silero VAD, TEN VAD)**
- Pros:
  - Better accuracy for speech detection
  - Robust to background noise
  - No threshold tuning needed
  - Distinguishes speech from non-speech sounds
- Cons:
  - Heavier (model loading, inference time)
  - Requires GPU for real-time on long videos
  - Focused on speech (not general audio)
- Best for: Noisy environments, podcasts, interviews

**Recommendation**: Start with FFmpeg silencedetect (simple, fast), upgrade to ML-based VAD if accuracy issues arise.

---

### 2. SUBTITLE-BASED VIDEO EDITING

#### A. Using SRT/VTT Files to Guide Editing

**SRT Parsing Libraries**
- `pysrt`: Dedicated SRT parser
- `srt`: Simple SRT library
- Manual parsing with regex (common in projects)

**Common Pattern** (from multiple repos):
```python
def parse_srt(srt_content):
    # Regex: \d\d:\d\d:\d\d,\d\d\d --> \d\d:\d\d:\d\d,\d\d\d
    blocks = re.split(r'\n\s*\n', srt_content)
    for block in blocks:
        # Extract: index, start_time, end_time, text
        yield (start_ms, end_ms, text)
```

**Use Cases**:
1. **Keep only subtitled segments**: Cut video to match subtitle timings
2. **Remove gaps between subtitles**: Speed up or cut inter-subtitle silence
3. **Filler word detection**: Parse subtitle text for "um", "uh", "like"
4. **Scene detection**: Use subtitle breaks as cut points

#### B. Filler Word Detection in Transcripts

**Common Filler Words** (English):
- Hesitations: "um", "uh", "er", "ah"
- Discourse markers: "like", "you know", "I mean", "basically"
- Repetitions: "so so", "and and"

**Detection Approach**:
```python
FILLER_WORDS = ['um', 'uh', 'like', 'you know', 'basically', 'actually']

def detect_fillers(subtitle_text, start_time, end_time):
    words = subtitle_text.lower().split()
    for word in words:
        if word in FILLER_WORDS:
            # Mark this subtitle segment for removal/speed-up
            yield (start_time, end_time, word)
```

**Advanced**: Use word-level timestamps (from Whisper JSON output) for precise filler removal

#### C. Automatic Cut Point Detection

**Strategies**:
1. **Silence + Subtitle Gaps**: Cut where both silence AND no subtitle
2. **Subtitle Boundaries**: Use subtitle start/end as natural cut points
3. **Sentence Boundaries**: Cut at periods, question marks (preserve context)
4. **Minimum Segment Length**: Avoid cuts shorter than X seconds (jarring)

**Example Logic**:
```python
def find_cut_points(silence_intervals, subtitle_intervals):
    cut_points = []
    for silence in silence_intervals:
        # Only cut if silence overlaps with subtitle gap
        if not overlaps_any_subtitle(silence, subtitle_intervals):
            if silence.duration > MIN_CUT_DURATION:
                cut_points.append(silence)
    return cut_points
```

---

### 3. INTEGRATION PATTERNS

#### A. Combining Silence Detection with Subtitle Analysis

**Workflow 1: Silence-First (Conservative)**
```
1. Detect silence with FFmpeg silencedetect
2. Load subtitles (SRT/VTT)
3. Filter silence intervals:
   - Keep silence if it overlaps with subtitle
   - Remove silence only in gaps between subtitles
4. Apply cuts/speed-ups
```
- Pros: Preserves all speech
- Cons: May keep unnecessary pauses within speech

**Workflow 2: Subtitle-First (Aggressive)**
```
1. Load subtitles
2. Identify gaps between subtitles (no text)
3. Detect silence only in those gaps
4. Cut/speed-up gaps
```
- Pros: Faster processing, cleaner cuts
- Cons: Relies on subtitle accuracy

**Workflow 3: Hybrid (Recommended)**
```
1. Detect silence with FFmpeg
2. Load subtitles
3. Classify silence:
   - Type A: Silence during subtitle (breathing, pauses) → Speed up 2-3x
   - Type B: Silence between subtitles → Speed up 6-8x or cut
   - Type C: Silence with filler words → Cut completely
4. Apply differential speed-ups
```
- Pros: Best quality, preserves context
- Cons: More complex logic

#### B. Common Workflows for Automated Video Editing

**Pattern 1: Extract → Analyze → Edit → Render**
```
1. Extract audio: ffmpeg -i video.mp4 audio.wav
2. Detect silence: silencedetect or PyDub
3. Generate cut list (JSON/intervals)
4. Apply cuts: ffmpeg filter_complex or re-encode
```

**Pattern 2: Single-Pass with FFmpeg**
```
1. Use FFmpeg filter_complex with silenceremove
2. Combine with subtitle filter for overlay
3. Render in one pass
```
- Faster but less flexible

**Pattern 3: Frame-Based (Jumpcutter approach)**
```
1. Extract all frames as images
2. Extract audio
3. Analyze audio per frame
4. Copy/skip frames based on analysis
5. Re-encode video from selected frames
```
- Most flexible but slowest

---

### 4. TOOLS THAT DO SIMILAR THINGS

#### A. Auto-Editor (https://github.com/WyattBlue/auto-editor)
- **Stars**: 3.9k | **Language**: Nim (was Python)
- **Key Features**:
  - Audio loudness detection (default: threshold=0.04, -19dB)
  - Motion detection for video
  - Export to Premiere, Resolve, Final Cut Pro
  - Margin control (padding before/after cuts)
  - Multiple edit methods: `--edit audio:threshold` or `--edit motion`
- **Architecture**:
  - Uses FFmpeg for media processing
  - Analyzes audio/video to generate timeline
  - Exports XML or renders directly
- **Strengths**: Most mature, feature-rich, active development
- **Permalink**: https://github.com/WyattBlue/auto-editor/blob/53e3f05687e6221e20c03a884f9148b91bbca593/README.md

#### B. Jumpcutter (https://github.com/carykh/jumpcutter)
- **Stars**: 3.1k | **Language**: Python
- **Key Features**:
  - Original viral tool (CaryKH's YouTube video)
  - Frame-by-frame analysis
  - Separate speeds for silent/sounded parts
  - Simple threshold-based detection
- **Architecture**:
  - Extract frames as JPEGs
  - Analyze audio per frame
  - Copy frames based on speed multiplier
  - Re-encode with time-stretched audio
- **Strengths**: Simple, educational, pioneered the concept
- **Weaknesses**: Slow (frame extraction), no longer maintained
- **Permalink**: https://github.com/carykh/jumpcutter/blob/master/jumpcutter.py

**Key Implementation** (lines 129-135):
```python
for i in range(audioFrameCount):
    start = int(i*samplesPerFrame)
    end = min(int((i+1)*samplesPerFrame), audioSampleCount)
    audiochunks = audioData[start:end]
    maxchunksVolume = float(getMaxVolume(audiochunks))/maxAudioVolume
    if maxchunksVolume >= SILENT_THRESHOLD:
        hasLoudAudio[i] = 1
```

#### C. Unsilence (https://github.com/lagmoellertim/unsilence)
- **Stars**: ~500 | **Language**: Python
- **Key Features**:
  - FFmpeg silencedetect wrapper
  - Speed up silent parts (default 6x)
  - Interval optimization (merge short segments)
  - CLI and library usage
- **Architecture**:
  - Parse FFmpeg silencedetect output
  - Build interval list (silent/audible)
  - Optimize intervals (merge, stretch)
  - Re-encode with speed filters
- **Strengths**: Clean API, well-documented, library-friendly
- **Permalink**: https://github.com/lagmoellertim/unsilence/blob/master/unsilence/lib/detect_silence/DetectSilence.py

**Key Implementation** (lines 30-38):
```python
command = [
    "ffmpeg", "-i", str(input_file), "-vn",
    "-af", f"silencedetect=noise={silence_level}dB:d={silence_time_threshold}",
    "-f", "null", "-"
]
# Parse: silence_start, silence_end from stderr
```

#### D. Commercial Tools (for reference)

**TimeBolt** (https://www.timebolt.io)
- Desktop app (Win/Mac)
- Auto remove silence, jump cuts
- Export to Premiere, Final Cut, DaVinci
- Pricing: ~$50-100

**Descript** (AI-powered)
- Transcript-based editing
- Remove filler words automatically
- Studio Sound (audio enhancement)
- Pricing: $12-24/month

**VEED.IO / Kapwing** (Web-based)
- AI jump cut tools
- Remove pauses and filler words
- Browser-based, no install
- Freemium pricing

---

### 5. RECOMMENDED ARCHITECTURE FOR THIS PROJECT

Based on research, here's the optimal approach:

#### Phase 1: Core Detection
```python
# 1. Silence Detection (FFmpeg-based)
def detect_silence_ffmpeg(video_path, noise_threshold=-30, min_duration=0.5):
    # Run: ffmpeg -i video -af silencedetect=noise=-30dB:d=0.5 -f null -
    # Parse stderr for silence_start/silence_end
    return [(start, end), ...]

# 2. Subtitle Parsing (if available)
def parse_subtitles(srt_path):
    # Parse SRT/VTT
    return [(start, end, text), ...]
```

#### Phase 2: Intelligent Merging
```python
def classify_intervals(silence_intervals, subtitle_intervals):
    """
    Classify silence into:
    - speech_pause: Silence during subtitle (keep or speed 2x)
    - inter_speech: Silence between subtitles (speed 6x or cut)
    - filler: Silence with filler words (cut)
    """
    pass
```

#### Phase 3: Video Editing
```python
def apply_edits(video_path, intervals, output_path):
    """
    Use FFmpeg filter_complex to:
    - Cut segments
    - Speed up segments
    - Concatenate result
    """
    pass
```

#### Key Design Decisions:
1. **Use FFmpeg silencedetect** (not PyDub) for speed
2. **Optional subtitle integration** (not required, but enhances quality)
3. **Differential speed-ups** (not just cut/keep)
4. **Export timeline** (JSON) for manual review/tweaking
5. **Support export to editors** (Premiere XML, DaVinci EDL)

---

### 6. USEFUL CODE PATTERNS

#### A. FFmpeg Silence Detection with Progress
```python
import subprocess, re

def detect_silence(video_path, noise_db=-30, min_duration=0.5):
    cmd = [
        'ffmpeg', '-i', video_path,
        '-af', f'silencedetect=noise={noise_db}dB:d={min_duration}',
        '-f', 'null', '-'
    ]
    
    process = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True)
    
    silence_intervals = []
    current_start = None
    
    for line in process.stderr:
        if 'silence_start' in line:
            match = re.search(r'silence_start: ([\d.]+)', line)
            if match:
                current_start = float(match.group(1))
        
        elif 'silence_end' in line:
            match = re.search(r'silence_end: ([\d.]+)', line)
            if match and current_start is not None:
                silence_intervals.append((current_start, float(match.group(1))))
                current_start = None
    
    return silence_intervals
```

#### B. SRT Parsing
```python
import re

def parse_srt(srt_path):
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split by double newline
    blocks = re.split(r'\n\s*\n', content.strip())
    
    subtitles = []
    for block in blocks:
        lines = block.split('\n')
        if len(lines) >= 3:
            # Line 0: index
            # Line 1: timestamp
            # Line 2+: text
            time_match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})', lines[1])
            if time_match:
                h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, time_match.groups())
                start = h1*3600 + m1*60 + s1 + ms1/1000
                end = h2*3600 + m2*60 + s2 + ms2/1000
                text = ' '.join(lines[2:])
                subtitles.append((start, end, text))
    
    return subtitles
```

#### C. Interval Merging
```python
def merge_close_intervals(intervals, max_gap=0.3):
    """Merge intervals that are closer than max_gap seconds"""
    if not intervals:
        return []
    
    merged = [intervals[0]]
    for current in intervals[1:]:
        last = merged[-1]
        if current[0] - last[1] <= max_gap:
            # Merge
            merged[-1] = (last[0], current[1])
        else:
            merged.append(current)
    
    return merged
```

---

### 7. PERFORMANCE CONSIDERATIONS

**FFmpeg silencedetect**: ~1-2x realtime (10min video = 5-10min processing)
**PyDub detect_silence**: ~0.5-1x realtime (slower, loads entire audio)
**Silero VAD**: ~5-10x realtime with GPU, ~1x with CPU
**Frame extraction (Jumpcutter)**: ~0.1x realtime (very slow)

**Recommendation**: Use FFmpeg silencedetect for initial implementation.

---

### 8. NEXT STEPS

1. Implement FFmpeg-based silence detection
2. Add SRT parsing (optional)
3. Build interval classification logic
4. Implement FFmpeg filter_complex for editing
5. Add export formats (JSON timeline, Premiere XML)
6. Consider ML-based VAD for v2.0

