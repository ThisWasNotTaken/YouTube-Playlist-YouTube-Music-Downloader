import sys
import subprocess
import importlib.util

def check_and_install_packages(packages):
    missing = [pkg for pkg in packages if importlib.util.find_spec(pkg) is None]

    if not missing:
        return

    print(f"Missing packages: {', '.join(missing)}")
    answer = input("Do you want to install missing packages now? (y/n): ").strip().lower()
    if answer == 'y':
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
        print("All missing packages installed. Please restart the script.")
        sys.exit(0)
    else:
        print("Cannot continue without required packages. Exiting.")
        sys.exit(1)

# List of required packages
required_packages = ["rich", "yt_dlp"]
check_and_install_packages(required_packages)

# Now safe to import required packages
from yt_dlp import YoutubeDL
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn

import os
import re
import time
import shutil
import webbrowser
from pathlib import Path
import concurrent.futures
from threading import Lock

console = Console()
console_lock = Lock()

def sanitize_folder_name(name):
    return re.sub(r'[\\/:"*?<>|]+', '_', name)

def check_tool(tool_name, install_url=None):
    found = shutil.which(tool_name) is not None
    return found, install_url

def show_startup_checklist():
    tools = {
        "ffmpeg": "https://ffmpeg.org/download.html",
        "yt-dlp": "https://github.com/yt-dlp/yt-dlp/releases",
    }

    tool_table = Table(title="🛠️  Startup Dependency Checklist", box=None, show_edge=False, pad_edge=False)
    tool_table.add_column("Tool", style="bold")
    tool_table.add_column("Status", justify="center")
    tool_table.add_column("Action", justify="left")

    missing_tools = []

    for tool, url in tools.items():
        found, install_url = check_tool(tool, url)
        if found:
            status = "[green]✅ Found[/green]"
            action = "-"
        else:
            status = "[red]❌ Missing[/red]"
            action = f"[cyan]Visit:[/] {install_url}"
            missing_tools.append((tool, install_url))
        tool_table.add_row(tool, status, action)

    console.print(Panel(tool_table, style="magenta"))

    for tool, url in missing_tools:
        answer = Prompt.ask(f"Do you want to open the download page for '{tool}' now? (y/n)", choices=["y", "n"], default="y")
        if answer == "y":
            webbrowser.open(url)

    if missing_tools:
        console.print("[red]Please install the missing tools and restart the script.[/red]")
        sys.exit(1)

def get_playlist_info(url):
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'skip_download': True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info

def download_video(entry, playlist_folder, existing_files):
    video_title = entry.get('title', 'unknown_title')
    safe_title = sanitize_folder_name(video_title)
    filename = f"{safe_title}.mp3"

    if filename in existing_files:
        with console_lock:
            console.print(f":arrow_forward: [yellow]Skipping already downloaded:[/] [bold]{video_title}[/]")
        return True

    output_path = playlist_folder / filename

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(output_path),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
        'ignoreerrors': True,
        'noplaylist': True,
    }

    with console_lock:
        console.print(f":arrow_down_small: [cyan]Downloading:[/] [bold]{video_title}[/]")

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([entry['url']])
        with console_lock:
            console.print(f":white_check_mark: [green]Finished:[/] [bold]{video_title}[/]")
        existing_files.add(filename)
        return True
    except Exception as e:
        err = str(e).lower()
        with console_lock:
            if "content isn't available" in err or "try again later" in err:
                console.print(f":warning: [red]Content not available, waiting 10 seconds before continuing...[/]")
            else:
                console.print(f":cross_mark: [red]Error downloading '{video_title}': {e}[/]")
        if "content isn't available" in err or "try again later" in err:
            time.sleep(10)
            with console_lock:
                console.print(":fast_forward: [yellow]Skipping this video.[/]")
            return False
        return False

def download_video_threadsafe(entry, playlist_folder, existing_files):
    return download_video(entry, playlist_folder, existing_files)

def main():
    console.clear()
    show_startup_checklist()

    console.print(Panel.fit("[bold magenta]🎵 YouTube Music Playlist Downloader[/bold magenta]", subtitle="Modern & Concurrent Terminal UI", padding=(1,2)))

    playlist_urls = []
    while True:
        url = Prompt.ask("Enter YouTube playlist URL (leave empty to finish)", default="")
        if not url.strip():
            break
        playlist_urls.append(url.strip())

    if not playlist_urls:
        console.print("[red]No URLs entered. Exiting.[/]")
        return

    output_folder = Prompt.ask("Enter output folder", default="downloads")
    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[bold green]Starting downloads...[/bold green]\n")

    max_workers = 4

    for idx, url in enumerate(playlist_urls, 1):
        console.rule(f"[bold blue]Playlist {idx}/{len(playlist_urls)}[/bold blue]")
        console.print(f"[bold]URL:[/] {url}")

        try:
            info = get_playlist_info(url)
            playlist_title = info.get('title', 'UnknownPlaylist')
            safe_title = sanitize_folder_name(playlist_title)
            playlist_folder = output_path / safe_title
            playlist_folder.mkdir(parents=True, exist_ok=True)
            entries = info.get('entries', [])

            if not entries:
                console.print(f":warning: [yellow]No videos found in playlist: {playlist_title}[/]\n")
                continue

            console.print(f"[bold green]Playlist:[/] {playlist_title} ([cyan]{len(entries)} videos[/cyan])\n")

            existing_files = {f.name for f in playlist_folder.glob("*.mp3")}

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=console,
                transient=True,
            ) as progress:

                task = progress.add_task("Downloading videos...", total=len(entries))

                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = []
                    for entry in entries:
                        safe_title = sanitize_folder_name(entry.get('title', 'unknown_title'))
                        filename = f"{safe_title}.mp3"
                        if filename in existing_files:
                            with console_lock:
                                console.print(f":arrow_forward: [yellow]Skipping already downloaded:[/] [bold]{entry.get('title', 'unknown')}[/]")
                            progress.advance(task)
                            continue
                        futures.append(executor.submit(download_video_threadsafe, entry, playlist_folder, existing_files))

                    for future in concurrent.futures.as_completed(futures):
                        progress.advance(task)

            console.print(f"\n:white_check_mark: [bold green]Completed playlist:[/] {playlist_title}\n")

        except Exception as e:
            console.print(f":cross_mark: [red]Failed to process playlist:[/] {e}")
            console.print(":fast_forward: [yellow]Skipping to next playlist...[/]\n")

    console.print(Panel.fit(f":tada: [bold magenta]All downloads finished![/bold magenta]\nFiles saved to: [bold]{output_path}[/bold]", padding=(1,2)))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n:stop_button: [red]Download interrupted by user. Exiting...[/]")
        sys.exit(0)
