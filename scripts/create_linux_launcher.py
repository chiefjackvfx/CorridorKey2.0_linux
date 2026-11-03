#!/usr/bin/env python3
"""Create a relocatable-on-regeneration desktop shortcut in the project folder."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    # Desktop Entry Exec quoting is distinct from shell quoting.
    executable = str(ROOT / '2-start.sh')
    for character in ('\\', '"', '`', '$'):
        executable = executable.replace(character, '\\' + character)
    executable = executable.replace('\\', '\\\\')
    launcher = ROOT / 'CorridorKey2-Linux.desktop'
    launcher.write_text(
        '[Desktop Entry]\nType=Application\nName=CorridorKey 2.0 Linux\n'
        'Comment=GPU video and image-sequence keying\n'
        f'Exec="{executable}" %F\n'
        'Icon=video-x-generic\nTerminal=false\nCategories=AudioVideo;Video;\n'
    )
    launcher.chmod(0o755)
    print(f'Created {launcher}')


if __name__ == '__main__':
    main()
