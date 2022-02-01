import os
import sys
from pathlib import Path

def main():
    if len(sys.argv != 2):
        print(f'Expected two args, but got {len(sys.argv)} instead.')
        sys.exit(1)
    filename = sys.argv[1:2][0]
    if not os.path.exists(filename):
        print(f'{filename} does not exist')
        sys.exit(1)
    out_path = Path('web_' + filename).with_suffix('.mp4')
    cmd = f'ffmpeg -i "{filename}" -vf scale=640:-1 -c:v libx264 -crf 19 "{out_path}"'
    os.system(cmd)

if __name__ == "__main__":
    main()