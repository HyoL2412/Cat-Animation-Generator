"""
Flask server to generate a cute kitten video from a user supplied image and
message.  Users can POST an image and a text string to the `/export_video`
endpoint and receive back a short MP4 file with their picture as the
background, the message overlaid and small hearts falling from the top of
the frame.  The video is assembled frame‑by‑frame using Pillow and
converted to an MP4 via ffmpeg.  See README or deployment instructions
for information on installing ffmpeg in your environment.
"""

import os
import tempfile
import subprocess
import random
from flask import Flask, request, send_file, jsonify
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    """Try to load a sensible font for drawing text.  Falls back to
    Pillow's default font if none of the common system fonts can be
    located.  When deploying to a Linux server the DejaVu Sans fonts
    are usually available under `/usr/share/fonts/truetype/dejavu/`.

    Args:
        size: Point size for the font.

    Returns:
        A PIL ImageFont instance at the requested size.
    """
    # Common font paths to try.  Add more paths if necessary.
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for path in font_paths:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    # Fall back to PIL's default bitmap font if no TTF font found.
    return ImageFont.load_default()


def create_heart(size: int, color=(255, 105, 180, 200)) -> Image.Image:
    """Generate a simple heart shape as a PIL RGBA image.

    The heart is constructed from two circles and a triangle.  The
    resulting image has transparent background and can be composited
    directly onto another image via `Image.alpha_composite`.

    Args:
        size: Width and height of the heart in pixels.
        color: RGBA tuple defining the heart's fill colour.

    Returns:
        A new Image object containing the heart.
    """
    heart = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(heart)
    # The heart shape consists of two circles and a downward triangle.
    radius = size // 2
    circle_radius = radius * 0.65  # adjust to get a pleasing shape
    circle_offset = radius * 0.35
    # Draw left circle
    draw.ellipse(
        (
            radius - 2 * circle_radius + circle_offset,
            radius - 2 * circle_radius,
            radius + circle_offset,
            radius,
        ),
        fill=color,
    )
    # Draw right circle
    draw.ellipse(
        (
            radius - circle_offset,
            radius - 2 * circle_radius,
            radius + 2 * circle_radius - circle_offset,
            radius,
        ),
        fill=color,
    )
    # Draw bottom triangle
    draw.polygon(
        [
            (radius - 2 * circle_radius + circle_offset, radius - circle_radius),
            (radius + 2 * circle_radius - circle_offset, radius - circle_radius),
            (radius, size),
        ],
        fill=color,
    )
    return heart


def generate_frames(base_image: Image.Image, message: str, width: int = 720,
                    height: int = 720, fps: int = 15, duration: int = 5) -> list:
    """Produce a list of PIL Images representing frames of the animation.

    The animation overlays the user supplied message near the top of the
    frame and renders a number of heart shapes that fall from random
    positions above the canvas.  Hearts begin falling at staggered
    times to produce a continuous rain effect.  The returned list
    contains one image per frame.

    Args:
        base_image: A PIL Image used as the background.  This image is
            resized to `width`×`height` before drawing.
        message: A unicode string containing the user supplied message.
        width: Desired width of the output frames.
        height: Desired height of the output frames.
        fps: Frames per second of the output video.
        duration: Length of the animation in seconds.

    Returns:
        A list of PIL Image objects, length equal to fps×duration.
    """
    # Prepare background
    bg = base_image.convert("RGBA").resize((width, height), Image.LANCZOS)
    total_frames = fps * duration
    # Preselect hearts with random start frames, x positions and sizes
    heart_count = 15
    hearts = []
    for _ in range(heart_count):
        start_frame = random.randint(0, total_frames // 2)
        x_pos = random.randint(0, width)
        size = random.randint(int(width * 0.03), int(width * 0.08))  # hearts scale with frame
        hearts.append({"start": start_frame, "x": x_pos, "size": size})
    # Cache heart images by size to avoid recomputation
    heart_cache = {}
    # Load a font once.  Size chosen relative to image dimensions.
    font_size = int(height * 0.06)
    font = load_font(font_size)
    # Precompute message width/height
    dummy_img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    d_draw = ImageDraw.Draw(dummy_img)
    text_w, text_h = d_draw.textsize(message, font=font)
    # Y coordinate for message: 10% down the frame height
    msg_y = int(height * 0.05)
    frames = []
    for frame_idx in range(total_frames):
        frame = bg.copy()
        frame_draw = ImageDraw.Draw(frame)
        # Draw message centered at the top
        msg_x = int((width - text_w) / 2)
        # Add a subtle shadow behind the text for better readability
        shadow_offset = 2
        frame_draw.text((msg_x + shadow_offset, msg_y + shadow_offset), message, font=font,
                         fill=(0, 0, 0, 160))
        frame_draw.text((msg_x, msg_y), message, font=font, fill=(255, 255, 255, 255))
        # Draw hearts
        for h in hearts:
            rel = frame_idx - h["start"]
            if rel < 0:
                continue
            # Compute progress of this heart falling from -heart.size to height
            t = rel / (total_frames - h["start"])
            y = -h["size"] + t * (height + h["size"] * 2)
            if y > height:
                continue
            size = h["size"]
            # Retrieve or create heart image
            if size not in heart_cache:
                heart_cache[size] = create_heart(size)
            heart_img = heart_cache[size]
            # Random subtle horizontal drift per heart
            drift = int((random.random() - 0.5) * size * 0.2)
            dest_x = int(h["x"] - size / 2 + drift)
            dest_y = int(y)
            # Composite heart onto frame
            frame.alpha_composite(heart_img, dest=(dest_x, dest_y))
        frames.append(frame.convert("RGB"))  # convert to RGB for ffmpeg
    return frames


@app.route("/export_video", methods=["POST"])
def export_video() -> object:
    """Handle video export requests.

    Expects multipart/form-data with keys:

    - `image`: the uploaded kitten photograph (required)
    - `message`: a unicode string to overlay on the video (required)

    Optionally, a query parameter `effect` can be provided, however
    at present only the heart rain effect is implemented.  The
    response is a binary MP4 stream.

    Returns:
        Flask Response object streaming the generated MP4 file.
    """
    # Validate incoming data
    if 'image' not in request.files:
        return jsonify({"error": "Missing image file"}), 400
    file = request.files['image']
    if file.filename == '':
        return jsonify({"error": "Empty filename"}), 400
    message = request.form.get('message', '')
    # Limit message length to prevent abuse
    if len(message) > 200:
        message = message[:200]
    try:
        base_image = Image.open(file.stream).convert("RGBA")
    except Exception:
        return jsonify({"error": "Invalid image file"}), 400
    # Create temporary directory to store frames and output video
    with tempfile.TemporaryDirectory() as tmpdir:
        # Generate frames
        frames = generate_frames(base_image, message)
        frame_pattern = os.path.join(tmpdir, "frame_%04d.png")
        # Save frames to disk for ffmpeg
        for idx, frame in enumerate(frames):
            frame_path = os.path.join(tmpdir, f"frame_{idx:04d}.png")
            frame.save(frame_path)
        # Prepare output path
        output_path = os.path.join(tmpdir, 'output.mp4')
        # Build ffmpeg command.  We expect ffmpeg to be installed on the server.
        # -y: overwrite output file
        # -framerate: input frame rate
        # -i: input pattern
        # -c:v libx264: encode video using H.264
        # -pix_fmt yuv420p: ensure compatibility with most players
        cmd = [
            'ffmpeg',
            '-y',
            '-framerate', str(15),
            '-i', os.path.join(tmpdir, 'frame_%04d.png'),
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            output_path
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            # ffmpeg not available: return error
            return jsonify({"error": "ffmpeg is not installed on the server"}), 500
        except subprocess.CalledProcessError:
            return jsonify({"error": "Failed to encode video"}), 500
        # Send the video back to the client
        return send_file(
            output_path,
            mimetype='video/mp4',
            as_attachment=True,
            download_name='kitten_video.mp4'
        )


@app.after_request
def add_cors_headers(response):
    """Add CORS headers to every response to allow cross‑origin requests.

    Since the front end may be served from a different domain during
    development, we add a permissive CORS header.  In production you
    should restrict this to the domain hosting your front‑end.
    """
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


if __name__ == '__main__':
    # When running locally `python app.py` will start the development server.
    # In production, you should use a WSGI server like Gunicorn.
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))