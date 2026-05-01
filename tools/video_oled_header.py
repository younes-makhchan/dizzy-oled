from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image


# ============================================================
# CONFIG
# ============================================================

OLED_W = 128
OLED_H = 64
BYTES_PER_FRAME = OLED_W * OLED_H // 8

# Your videos
VIDEOS = [
    {
        "name": "blink",
        "file": "blink.mp4",
    },
    {
        "name": "dizzy",
        "file": "dizzy.mp4",
    },
]

OUTPUT_HEADER = "face_frames.h"

# If video has too many frames, you can skip frames:
# 1 = use every frame
# 2 = use every second frame
# 3 = use every third frame
FRAME_SKIP = 1

# Optional limit.
# None = use all frames.
# Example: 18 = only export first 18 frames.
MAX_FRAMES_PER_VIDEO = None

# Threshold:
# pixel > THRESHOLD becomes white
# pixel <= THRESHOLD becomes black
THRESHOLD = 127

# Set True only if your output is inverted on OLED
INVERT = False

# Debug frames help you inspect what will go to OLED
SAVE_DEBUG_PNGS = True
DEBUG_DIR = Path("debug_exported_frames")


# ============================================================
# BITMAP CONVERSION
# ============================================================

def frame_to_128x64_gray(frame_array):
    """
    Convert one video frame to 128x64 grayscale PIL image.
    Assumes video is already 128x64, but resizes if needed.
    """
    img = Image.fromarray(frame_array)

    # Convert video frame to grayscale
    img = img.convert("L")

    if img.size != (OLED_W, OLED_H):
        print(f"Warning: resizing frame from {img.size} to {(OLED_W, OLED_H)}")
        img = img.resize((OLED_W, OLED_H), Image.Resampling.LANCZOS)

    return img


def gray_to_bool_pixels(img):
    """
    Convert grayscale PIL image to boolean white/black pixel array.
    Shape: 64x128
    True = white pixel
    False = black pixel
    """
    arr = np.array(img, dtype=np.uint8)

    white = arr > THRESHOLD

    if INVERT:
        white = ~white

    return white


def pack_bitmap_msb_first(white_pixels):
    """
    Convert 128x64 bool image to Adafruit_GFX bitmap format.

    Adafruit_GFX drawBitmap expects:
    - row-major
    - 8 horizontal pixels per byte
    - MSB first

    128x64 = 1024 bytes
    """
    data = []

    for y in range(OLED_H):
        for byte_x in range(OLED_W // 8):
            value = 0

            for bit in range(8):
                x = byte_x * 8 + bit

                if white_pixels[y, x]:
                    value |= (0x80 >> bit)

            data.append(value)

    if len(data) != BYTES_PER_FRAME:
        raise RuntimeError(f"Bad frame size: got {len(data)} bytes")

    return data


def format_byte_array(data, indent="    "):
    """
    Format one 1024-byte frame as C++ hex values.
    """
    lines = []

    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        line = indent + ", ".join(f"0x{b:02X}" for b in chunk)
        lines.append(line)

    return ",\n".join(lines)


def export_video(video_name, video_file):
    """
    Read video and return list of bitmap frames.
    """
    video_file = Path(video_file)

    if not video_file.exists():
        raise FileNotFoundError(f"Missing video file: {video_file}")

    print(f"Reading {video_file}...")

    reader = imageio.get_reader(str(video_file))

    frames = []

    debug_video_dir = DEBUG_DIR / video_name

    if SAVE_DEBUG_PNGS:
        debug_video_dir.mkdir(parents=True, exist_ok=True)

    for source_index, frame_array in enumerate(reader):
        if source_index % FRAME_SKIP != 0:
            continue

        if MAX_FRAMES_PER_VIDEO is not None:
            if len(frames) >= MAX_FRAMES_PER_VIDEO:
                break

        img_gray = frame_to_128x64_gray(frame_array)
        white_pixels = gray_to_bool_pixels(img_gray)

        bitmap_data = pack_bitmap_msb_first(white_pixels)
        frames.append(bitmap_data)

        if SAVE_DEBUG_PNGS:
            debug_img = Image.fromarray(
                np.where(white_pixels, 255, 0).astype(np.uint8),
                mode="L",
            )
            debug_img.save(debug_video_dir / f"{video_name}_{len(frames) - 1:03d}.png")

    reader.close()

    print(f"Exported {len(frames)} frames for '{video_name}'")

    if len(frames) == 0:
        raise RuntimeError(f"No frames exported from {video_file}")

    return frames


def write_header(all_animations):
    """
    Generate face_frames.h
    """
    with open(OUTPUT_HEADER, "w", encoding="utf-8") as f:
        f.write("#pragma once\n\n")
        f.write("#include <Arduino.h>\n\n")
        f.write("#define FACE_WIDTH 128\n")
        f.write("#define FACE_HEIGHT 64\n")
        f.write("#define FACE_FRAME_BYTES 1024\n\n")

        for anim_name, frames in all_animations.items():
            upper = anim_name.upper()

            f.write(f"const uint16_t {upper}_FRAME_COUNT = {len(frames)};\n\n")

            f.write(
                f"const uint8_t {anim_name}Frames"
                f"[{len(frames)}][FACE_FRAME_BYTES] PROGMEM = {{\n"
            )

            for index, frame_data in enumerate(frames):
                f.write(f"  // {anim_name} frame {index}\n")
                f.write("  {\n")
                f.write(format_byte_array(frame_data))
                f.write("\n  }")

                if index != len(frames) - 1:
                    f.write(",")

                f.write("\n")

            f.write("};\n\n")

    print(f"Generated {OUTPUT_HEADER}")


def main():
    all_animations = {}

    if SAVE_DEBUG_PNGS:
        DEBUG_DIR.mkdir(exist_ok=True)

    for video in VIDEOS:
        frames = export_video(video["name"], video["file"])
        all_animations[video["name"]] = frames

    write_header(all_animations)

    print("")
    print("Done.")
    print(f"Header file: {OUTPUT_HEADER}")
    print("Copy this file into your Arduino/PlatformIO src folder.")
    print("")
    print("Important:")
    print("Each 128x64 frame uses 1024 bytes of flash.")
    print("Example: 30 frames = about 30 KB.")


if __name__ == "__main__":
    main()