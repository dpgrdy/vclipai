"""Music overlay with audio ducking."""

import logging

from moviepy import VideoClip, AudioFileClip, CompositeAudioClip

log = logging.getLogger(__name__)


def overlay_music(
    clip: VideoClip,
    music_path: str,
    music_volume: float = 0.7,
    game_duck_db: float = -12,
) -> VideoClip:
    """Overlay music track on video with game audio ducking.

    Args:
        clip: Video clip with game audio
        music_path: Path to music file
        music_volume: Music volume multiplier (0-1)
        game_duck_db: How much to duck game audio in dB (negative)
    """
    try:
        music = AudioFileClip(music_path)
    except Exception as e:
        log.error("Failed to load music: %s", e)
        return clip

    # Trim or loop music to match video duration
    if music.duration > clip.duration:
        music = music.subclipped(0, clip.duration)
    elif music.duration < clip.duration:
        # Loop music
        loops_needed = int(clip.duration / music.duration) + 1
        from moviepy import concatenate_audioclips
        music = concatenate_audioclips([music] * loops_needed)
        music = music.subclipped(0, clip.duration)

    # Apply volume
    music = music.with_volume_scaled(music_volume)

    # Duck game audio
    duck_factor = 10 ** (game_duck_db / 20)  # dB to linear
    original_audio = clip.audio
    if original_audio:
        ducked_audio = original_audio.with_volume_scaled(duck_factor)
        combined = CompositeAudioClip([ducked_audio, music])
    else:
        combined = music

    return clip.with_audio(combined)
