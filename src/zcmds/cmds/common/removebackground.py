import argparse
import concurrent.futures
import os
import shutil
import subprocess
import sys
import threading
import time
import warnings
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Needed for some reason.
os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"

PORT = 5283

MODEL = "u2net"

"""
u2net: A pre-trained model for general use cases.
u2netp: A lightweight version of u2net model.
u2net_human_seg: A pre-trained model for human segmentation.
u2net_cloth_seg: A pre-trained model for Cloths Parsing from human portrait. Here clothes are parsed into 3 category: Upper body, Lower body and Full body.
silueta: Same as u2net but the size is reduced to 43Mb.
isnet-general-use: A new pre-trained model for general use cases.
isnet-anime: A high-accuracy segmentation for anime character.
sam (download encoder, download decoder, source): A pre-trained model for any use cases.
"""

MODELS = {
    "u2net": "A pre-trained model for general use cases.",
    "u2netp": "A lightweight version of u2net model.",
    "u2net_human_seg": "A pre-trained model for human segmentation.",
    "u2net_cloth_seg": "A pre-trained model for Cloths Parsing from human portrait. Here clothes are parsed into 3 category: Upper body, Lower body and Full body.",
    "silueta": "Same as u2net but the size is reduced to 43Mb.",
    "isnet-general-use": "A new pre-trained model for general use cases.",
    "isnet-anime": "A high-accuracy segmentation for anime character.",
    "sam": "A pre-trained model for any use cases.",
}

MODEL_CHOICES = list(MODELS.keys())


@dataclass
class RemoveBackgroundVideoResult:
    webm_path: Path
    mp4_path: Path


@dataclass
class VidInfo:
    width: int
    height: int
    fps: float


def install_rembg_if_missing() -> None:
    bin_path = os.path.expanduser("~/.local/bin")
    os.environ["PATH"] = os.environ["PATH"] + os.pathsep + bin_path
    if shutil.which("rembg") is not None:
        return
    print("Installing rembg...")
    _exec("pipx install rembg[cli,gpu]")
    assert shutil.which("rembg") is not None, "rembg not found after install"


def open_browser_with_delay(url: str, delay: float) -> None:
    def delayed_open():
        time.sleep(delay)
        webbrowser.open(url)

    threading.Thread(target=delayed_open).start()


def get_video_info(video_path: Path) -> VidInfo:
    # use static_ffmpeg to get the video dimensions using the ffprobe and the
    # json output feature
    assert shutil.which("vidinfo") is not None, "vidinfo not found"
    assert video_path.exists(), f"Video file not found: {video_path}"
    command = f'vidinfo "{video_path}"'
    stdout = subprocess.check_output(command, shell=True).decode("utf-8")
    lines = stdout.split("\n")
    height: Optional[int] = None
    width: Optional[int] = None
    fps: Optional[float] = None
    for line in lines:
        if "Height: " in line:
            height = int(line.split("Height: ")[1])
        if "Width: " in line:
            width = int(line.split("Width: ")[1])
        if "Framerate: " in line:
            fps_str = line.split("Framerate: ")[1]
            # split out the " fps" part
            fps = float(fps_str.split(" ")[0])
    assert height is not None, "Height not found in video info"
    assert width is not None, "Width not found in video info"
    assert fps is not None, "Framerate not found in video info"
    # return width, height, fps
    return VidInfo(width, height, fps)


def _exec(cmd: str) -> None:
    print(f"\n\nRunning:\n    {cmd}\n\n")
    rtn = os.system(cmd)
    if rtn != 0:
        raise OSError(f"Error running command: {cmd}, return code: {rtn}")


def video_remove_background(
    video_path: Path,
    output_dir: Path,
    bitrate_megs: float,
    output_height: Optional[int] = None,
    fps_override: Optional[float] = None,
    model: str = MODEL,
    keep_files: bool = False,
    exposed_gpus: Optional[list[int]] = None,
    num_jobs: Optional[int] = None,
) -> RemoveBackgroundVideoResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    vidinfo: VidInfo = get_video_info(video_path)
    print(f"Video dimensions: {vidinfo.width}x{vidinfo.height}")
    cmd = f"static_ffmpeg -hide_banner -y -i {video_path} {output_dir}/%07d.png"
    _exec(cmd)
    print(f"Images saved to {output_dir}")

    if num_jobs is None:
        if exposed_gpus is None:
            num_jobs = 1
        else:
            num_jobs = len(exposed_gpus)

    if exposed_gpus is None or len(exposed_gpus) == 1:
        final_output_dir = output_dir / "video"
        final_output_dir.mkdir(parents=True, exist_ok=True)
        cmd = f'rembg p -a -ae 15 --post-process-mask -m {model} "{output_dir}" "{final_output_dir}"'
        _exec(cmd)
        print(f"Images with background removed saved to {final_output_dir}")
    else:
        # Split the images into subfolders for parallel processing
        img_files = list(output_dir.glob("*.png"))
        img_files.sort()
        chunk_size = (len(img_files) + num_jobs - 1) // num_jobs
        img_chunks = [
            img_files[i : i + chunk_size] for i in range(0, len(img_files), chunk_size)
        ]

        def process_chunk(chunk, gpu_id, job_id):
            chunk_dir = output_dir / str(job_id)
            chunk_dir.mkdir(parents=True, exist_ok=True)
            for img in chunk:
                shutil.move(str(img), str(chunk_dir / img.name))

            final_output_dir = chunk_dir / "video"
            final_output_dir.mkdir(parents=True, exist_ok=True)
            env = {}
            env["NVIDIA_VISIBLE_DEVICES"] = str(gpu_id)
            env["CUDA_VISIBLE_DEVICES"] = "0"
            new_env = env.copy()
            env.update(os.environ)
            cmd = f'rembg p -a -ae 15 --post-process-mask -m {model} "{chunk_dir}" "{final_output_dir}"'
            print(f"Running: {cmd}, with updated environment: {new_env}")
            subprocess.run(cmd, shell=True, env=env, check=True)
            print(f"Images with background removed saved to {final_output_dir}")
            print()

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_jobs) as executor:
            futures = [
                executor.submit(
                    process_chunk,
                    chunk,
                    exposed_gpus[job_id % len(exposed_gpus)],
                    job_id,
                )
                for job_id, chunk in enumerate(img_chunks)
            ]
            concurrent.futures.wait(futures)

        # Merge the processed images back into the main video directory
        final_output_dir = output_dir / "video"
        final_output_dir.mkdir(parents=True, exist_ok=True)
        for gpu_id in range(num_jobs):
            chunk_output_dir = output_dir / str(gpu_id) / "video"
            for img in chunk_output_dir.glob("*.png"):
                shutil.move(str(img), str(final_output_dir / img.name))

    fps: float = fps_override if fps_override else vidinfo.fps
    out_vid_path = Path(str(video_path.with_suffix("")) + "-nobackground.webm")
    filter_stmt = ""
    if output_height is not None:
        filter_stmt = f'-vf "scale=trunc(oh*a/2)*2:{output_height}"'

    # Generate webm format for Chrome/Firefox
    cmd = (
        f"static_ffmpeg -hide_banner -y -framerate {vidinfo.fps}"
        f' -i "{final_output_dir}/%07d.png" {filter_stmt} -c:v libvpx-vp9 -b:v {bitrate_megs}M'
        f' -auto-alt-ref 0 -pix_fmt yuva420p -an -r {fps} "{out_vid_path}"'
    )
    _exec(cmd)

    # Command to merge the audio from the original video with the new video
    final_output_path = Path(str(video_path.with_suffix("")) + f"-nobg-{model}.webm")
    print(f"Mixing audio from {video_path} into {final_output_path}")
    cmd = (
        f'static_ffmpeg -hide_banner -y -i "{out_vid_path}" -i "{video_path}"'
        f' -c:v copy -c:a libvorbis -map 0:v:0 -map 1:a:0 "{final_output_path}"'
    )
    _exec(cmd)

    # Generate HEVC mp4 format for Safari
    tmp_mp4 = Path(str(video_path.with_suffix("")) + "-nobackground.mp4")
    cmd = (
        f"static_ffmpeg -hide_banner -y -framerate {vidinfo.fps}"
        f' -i "{final_output_dir}/%07d.png" {filter_stmt} -c:v libx265 -crf 28'
        f' -an -r {fps} "{tmp_mp4}"'
    )

    _exec(cmd)

    # now mix in the audio
    out_mp4 = Path(str(video_path.with_suffix("")) + f"-nobg-{model}.mp4")
    cmd = (
        f'static_ffmpeg -hide_banner -y -i "{tmp_mp4}" -i "{video_path}"'
        f' -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 "{out_mp4}"'
    )
    _exec(cmd)

    # Delete intermediate files if --keep-files is not set
    if not keep_files:
        items_to_delete: list[Path] = [output_dir, out_vid_path, tmp_mp4]
        for item in items_to_delete:
            if item.exists():
                try:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        os.remove(item)
                except Exception as e:
                    warnings.warn(f"Failed to delete {item}: {e}")

    print(
        f"Generated transparent supporting webm (vp9 with yuva420p) for Chrome/Firefox: {final_output_path}"
    )
    print(
        f"Generated transparent supporting mp4 (HEVC with yuva420p) for Safari: {out_mp4}"
    )
    return RemoveBackgroundVideoResult(final_output_path, out_mp4)


def is_video_file(file_path: Path) -> bool:
    return file_path.suffix in {".mp4", ".avi", ".mov", ".mkv", ".flv", ".webm", ".wmv"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remove background from images")
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=PORT,
        help=f"Port to run the server on (default: {PORT})",
    )

    parser.add_argument(
        "file",
        type=Path,
        nargs="?",
    )

    parser.add_argument(
        "-b",
        "--bitrate",
        type=float,
        default=10.0,
        help="Bitrate for the output video (default: 10.0)",
    )
    parser.add_argument(
        "--height",
        type=int,
        help="Height of the output video (default: None)",
    )
    parser.add_argument(
        "--fps",
        type=float,
        help="Frames per second for the output video (default: None)",
    )
    parser.add_argument(
        "--keep-files",
        action="store_true",
        help="Keep intermediate files (default: False)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=MODEL,
        choices=MODEL_CHOICES,
        help=f"Model to use (default: {MODEL}, choices: {MODEL_CHOICES})",
    )
    parser.add_argument(
        "--gpu-count",
        type=int,
        default=1,
        help="Number of GPUs to use for parallel processing (default: 1)",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        help="Number of parallel jobs to run (default: same as --gpu-count)",
    )
    return parser.parse_args()


def cli() -> int:
    install_rembg_if_missing()
    args = parse_args()

    if args.file is None:
        open_browser_with_delay(f"http://localhost:{PORT}", 4)
        _exec(f"rembg s --port {PORT}")
        return 0

    if is_video_file(args.file):
        import time

        start = time.time()
        video_remove_background(
            video_path=args.file,
            output_dir=args.file.with_suffix(""),
            bitrate_megs=args.bitrate,
            output_height=args.height,
            fps_override=args.fps,
            keep_files=args.keep_files,
            model=args.model,
            exposed_gpus=[int(i) for i in range(args.gpu_count)],
            num_jobs=args.jobs or args.gpu_count,
        )
        diff = time.time() - start
        print(f"Time taken: {diff:.2f} seconds")
        return 0
    cmd = f'rembg -a -ae 15 --post-process-mask -m {args.model} i "{args.file}"'
    _exec(cmd)
    return 0


def main() -> int:
    try:
        return cli()
    except KeyboardInterrupt:
        return 1


def _project_root() -> Path:
    here = Path(__file__).parent
    return here.parent.parent.parent.parent


def _cd_to_project_root() -> None:
    project_root = _project_root()
    os.chdir(project_root)


def test_data() -> str:
    return str(_project_root() / "tests" / "test_data" / "rembg.mp4")


def unit_test() -> None:
    _cd_to_project_root()
    test_mp4 = test_data()
    sys.argv.append(test_mp4)
    sys.argv.append("--gpu-count")
    sys.argv.append("2")
    sys.argv.append("--jobs")
    sys.argv.append("4")
    # sys.argv.append("--keep-files")
    # u2net_human_seg
    # sys.argv.append("--model")
    # sys.argv.append("isnet-general-use")
    sys.exit(main())


if __name__ == "__main__":
    unit_test()
    # main()
