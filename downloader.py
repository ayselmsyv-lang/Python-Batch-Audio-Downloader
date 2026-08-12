from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import questionary
import yt_dlp
from questionary import Choice
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from yt_dlp.utils import DownloadError


console = Console()

PROMPT_STYLE = questionary.Style(
    [
        ("qmark", "fg:#38bdf8 bold"),
        ("question", "bold"),
        ("answer", "fg:#22c55e bold"),
        ("pointer", "fg:#38bdf8 bold"),
        ("highlighted", "fg:#38bdf8 bold"),
        ("selected", "fg:#22c55e"),
        ("instruction", "fg:#64748b"),
    ]
)


YOUTUBE_URL_PATTERN = re.compile(
    r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)/[^\s<>'\"]+",
    re.IGNORECASE,
)


def video_id_from_url(url: str) -> str | None:
    """Return a YouTube video ID for common URL formats."""
    cleaned = url.rstrip(".,;:!?)]}")
    parsed = urlparse(cleaned)
    host = (parsed.hostname or "").lower()

    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
        return candidate if len(candidate) == 11 else None

    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [None])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
            parts = parsed.path.strip("/").split("/")
            candidate = parts[1] if len(parts) > 1 else None
        else:
            candidate = None
        return candidate if candidate and len(candidate) == 11 else None

    return None


def load_unique_links(input_file: Path) -> list[str]:
    """Extract YouTube links and deduplicate them by video ID."""
    text = input_file.read_text(encoding="utf-8")
    video_ids: dict[str, None] = {}

    for match in YOUTUBE_URL_PATTERN.findall(text):
        video_id = video_id_from_url(match)
        if video_id:
            video_ids.setdefault(video_id, None)

    return [f"https://www.youtube.com/watch?v={video_id}" for video_id in video_ids]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download audio from a text file containing YouTube links.",
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=Path("links.txt"),
        help="Text file containing YouTube URLs (default: links.txt)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("songs"),
        help="Output directory (default: songs)",
    )
    parser.add_argument(
        "--browser",
        choices=("brave", "chrome", "edge", "firefox"),
        help="Read authentication cookies from this browser",
    )
    parser.add_argument(
        "--browser-profile",
        help="Optional browser profile name, for example 'Profile 1'",
    )
    parser.add_argument(
        "--cookies",
        type=Path,
        help="Netscape-format cookies.txt file",
    )
    parser.add_argument(
        "--audio-format",
        choices=("original", "mp3", "m4a"),
        default="original",
        help="Output format; mp3/m4a conversion requires FFmpeg (default: original)",
    )
    parser.add_argument(
        "--quality",
        default="192",
        help="FFmpeg audio quality for converted files (default: 192)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=5,
        help="Minimum seconds between downloads (default: 5)",
    )
    parser.add_argument(
        "--max-sleep",
        type=float,
        default=10,
        help="Maximum randomized delay between downloads (default: 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print normalized links without downloading",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Open the interactive setup wizard",
    )
    return parser


def ask(prompt):
    """Run a questionary prompt and treat Ctrl+C as a clean cancellation."""
    answer = prompt.ask()
    if answer is None:
        raise KeyboardInterrupt
    return answer


def existing_file(value: str) -> bool | str:
    return True if Path(value).is_file() else "File not found. Check the path."


def non_negative_number(value: str) -> bool | str:
    try:
        return True if float(value) >= 0 else "Enter a number greater than or equal to 0."
    except ValueError:
        return "Enter a valid number."


def run_interactive_wizard() -> argparse.Namespace:
    """Collect CLI options through a guided terminal wizard."""
    console.print(
        Panel.fit(
            "[bold cyan]Python Batch Audio Downloader[/bold cyan]\n"
            "Configure a safe, resumable audio download batch.",
            border_style="cyan",
        )
    )

    input_path = Path(
        ask(
            questionary.text(
                "Where is your link file?",
                default="links.txt",
                validate=existing_file,
                style=PROMPT_STYLE,
            )
        )
    )
    output_path = Path(
        ask(
            questionary.text(
                "Where should downloaded files be saved?",
                default="songs",
                style=PROMPT_STYLE,
            )
        )
    )

    auth_method = ask(
        questionary.select(
            "How should YouTube authentication be handled?",
            choices=[
                Choice("Guest session — no cookies", value="guest"),
                Choice("Brave browser session", value="brave"),
                Choice("Chrome browser session", value="chrome"),
                Choice("Edge browser session", value="edge"),
                Choice("Firefox browser session", value="firefox"),
                Choice("Netscape cookies.txt file", value="cookiefile"),
            ],
            style=PROMPT_STYLE,
        )
    )

    browser = auth_method if auth_method in {"brave", "chrome", "edge", "firefox"} else None
    browser_profile = None
    cookie_path = None

    if browser:
        browser_profile = ask(
            questionary.text(
                "Browser profile name (leave empty for Default):",
                default="",
                style=PROMPT_STYLE,
            )
        ).strip() or None
        browser_closed = ask(
            questionary.confirm(
                f"Is {browser.title()} fully closed?",
                default=False,
                style=PROMPT_STYLE,
            )
        )
        if not browser_closed:
            console.print("[yellow]Close the browser and run the wizard again.[/yellow]")
            raise KeyboardInterrupt
    elif auth_method == "cookiefile":
        cookie_path = Path(
            ask(
                questionary.text(
                    "Path to the Netscape cookie file:",
                    default="cookies.txt",
                    validate=existing_file,
                    style=PROMPT_STYLE,
                )
            )
        )

    audio_format = ask(
        questionary.select(
            "Which audio format should be produced?",
            choices=[
                Choice("Original — best source audio, no conversion", value="original"),
                Choice("MP3 — requires FFmpeg", value="mp3"),
                Choice("M4A — requires FFmpeg", value="m4a"),
            ],
            style=PROMPT_STYLE,
        )
    )
    quality = "192"
    if audio_format != "original":
        quality = ask(
            questionary.select(
                "Select conversion quality:",
                choices=["128", "192", "256", "320"],
                default="192",
                style=PROMPT_STYLE,
            )
        )

    advanced = ask(
        questionary.confirm(
            "Configure advanced request delays?",
            default=False,
            style=PROMPT_STYLE,
        )
    )
    sleep = 5.0
    max_sleep = 10.0
    if advanced:
        sleep = float(
            ask(
                questionary.text(
                    "Minimum delay between downloads (seconds):",
                    default="5",
                    validate=non_negative_number,
                    style=PROMPT_STYLE,
                )
            )
        )
        max_sleep = float(
            ask(
                questionary.text(
                    "Maximum randomized delay (seconds):",
                    default="10",
                    validate=non_negative_number,
                    style=PROMPT_STYLE,
                )
            )
        )

    dry_run = ask(
        questionary.confirm(
            "Preview normalized links without downloading?",
            default=False,
            style=PROMPT_STYLE,
        )
    )

    unique_count = len(load_unique_links(input_path))
    summary = Table(title="Batch configuration", border_style="cyan", show_header=False)
    summary.add_column("Setting", style="bold")
    summary.add_column("Value", style="green")
    summary.add_row("Input", str(input_path))
    summary.add_row("Unique videos", str(unique_count))
    summary.add_row("Output", str(output_path))
    summary.add_row("Authentication", auth_method)
    summary.add_row("Browser profile", browser_profile or "Default / not applicable")
    summary.add_row("Audio format", audio_format.upper())
    summary.add_row("Request delay", f"{sleep:g}–{max_sleep:g} seconds")
    summary.add_row("Mode", "Preview only" if dry_run else "Download")
    console.print(summary)

    confirmed = ask(
        questionary.confirm(
            "Start with this configuration?",
            default=True,
            style=PROMPT_STYLE,
        )
    )
    if not confirmed:
        raise KeyboardInterrupt

    return argparse.Namespace(
        input=input_path,
        output=output_path,
        browser=browser,
        browser_profile=browser_profile,
        cookies=cookie_path,
        audio_format=audio_format,
        quality=quality,
        sleep=sleep,
        max_sleep=max_sleep,
        dry_run=dry_run,
        interactive=True,
    )


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.browser and args.cookies:
        parser.error("Use either --browser or --cookies, not both.")
    if args.browser_profile and not args.browser:
        parser.error("--browser-profile requires --browser.")
    if args.max_sleep < args.sleep:
        parser.error("--max-sleep cannot be smaller than --sleep.")
    if not args.input.is_file():
        parser.error(f"Input file not found: {args.input}")
    if args.cookies and not args.cookies.is_file():
        parser.error(f"Cookie file not found: {args.cookies}")


def build_options(args: argparse.Namespace) -> dict:
    args.output.mkdir(parents=True, exist_ok=True)

    options: dict = {
        "format": "bestaudio/best",
        "outtmpl": str(args.output / "%(title).180B [%(id)s].%(ext)s"),
        "download_archive": str(args.output / "download-archive.txt"),
        "noplaylist": True,
        "windowsfilenames": True,
        "retries": 5,
        "fragment_retries": 5,
        "sleep_interval": args.sleep,
        "max_sleep_interval": args.max_sleep,
        "concurrent_fragment_downloads": 1,
        "quiet": False,
    }

    if args.browser:
        options["cookiesfrombrowser"] = (
            (args.browser, args.browser_profile)
            if args.browser_profile
            else (args.browser,)
        )
    elif args.cookies:
        options["cookiefile"] = str(args.cookies)

    if args.audio_format != "original":
        options["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": args.audio_format,
                "preferredquality": args.quality,
            }
        ]

    return options


def main() -> int:
    parser = build_parser()
    try:
        if len(sys.argv) == 1:
            args = run_interactive_wizard()
        else:
            args = parser.parse_args()
            if args.interactive:
                if len(sys.argv) > 2:
                    parser.error("--interactive cannot be combined with other options.")
                args = run_interactive_wizard()
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled. No download was started.[/yellow]")
        return 130

    validate_args(args, parser)

    links = load_unique_links(args.input)
    if not links:
        console.print(f"[red]No valid YouTube links found in {args.input}.[/red]")
        return 1

    console.print(f"[bold green]Found {len(links)} unique YouTube videos.[/bold green]")

    if args.dry_run:
        console.print(*links, sep="\n")
        return 0

    failed: list[str] = []
    options = build_options(args)

    with yt_dlp.YoutubeDL(options) as ydl:
        for index, url in enumerate(links, start=1):
            console.rule(f"[cyan]{index}/{len(links)}[/cyan] {url}")
            try:
                ydl.download([url])
            except DownloadError as error:
                console.print(f"[red]Failed:[/red] {error}")
                failed.append(url)
            except KeyboardInterrupt:
                console.print("\n[yellow]Download interrupted by user.[/yellow]")
                failed.extend(links[index - 1 :])
                break

    failed_file = args.output / "failed-links.txt"
    if failed:
        failed_file.write_text("\n".join(failed) + "\n", encoding="utf-8")
        console.print(
            Panel.fit(
                f"Completed with [red]{len(failed)} failure(s)[/red].\n"
                f"Review: [bold]{failed_file}[/bold]",
                title="Batch completed",
                border_style="yellow",
            )
        )
        return 2

    failed_file.unlink(missing_ok=True)
    console.print(
        Panel.fit(
            f"[bold green]All downloads completed successfully.[/bold green]\n"
            f"Output: [bold]{args.output}[/bold]",
            title="Batch completed",
            border_style="green",
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
