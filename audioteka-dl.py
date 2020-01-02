#!/usr/bin/env python3

import argparse
import getpass
import sys
import re
from typing import List
from urllib.parse import urlparse, parse_qsl
from collections import namedtuple
from pathlib import Path

import requests
import tqdm
from termcolor import colored
from bs4 import BeautifulSoup


try:
    assert sys.version_info.major == 3
    assert sys.version_info.minor > 6
except AssertionError:
    raise RuntimeError("This script requires Python 3.7+!")


Audiobook = namedtuple("Audiobook", ["id", "title"])


class AudiotekaClient:

    BASE_DOMAIN = "audioteka.com"

    def __init__(self):
        self.session = requests.Session()
        self.is_authenticated = False

    def login(self, username: str, password: str):
        resp = self.session.get(f"https://{self.BASE_DOMAIN}/pl/signin/login")
        html = BeautifulSoup(resp.content, "html.parser")
        form = html.find("form", {"action": "/pl/user/login_check"})
        payload = {
            "_username": username,
            "_password": password,
            "_remember_me": 1,
            "_failure_path": "login",
            "_token": form.find("input", {"id": "_token"}).get("value"),
            "login": "",
        }

        resp = self.session.post(
            f"https://{self.BASE_DOMAIN}/pl/user/login_check",
            data=payload,
            headers={"Referer": f"https://{self.BASE_DOMAIN}/pl/signin/login"},
        )

        if b"shelf-item" in resp.content:
            self.is_authenticated = True

    @property
    def shelf(self) -> List[Audiobook]:
        resp = self.session.get(f"https://{self.BASE_DOMAIN}/pl/my-shelf")
        html = BeautifulSoup(resp.content, "html.parser")
        audiobooks = []

        for item in html.find_all("div", {"class": "shelf-item"}):
            a = item.find("a", {"class": "js-item-trunk8"})
            *_, item_id = a.get("href").split("/")
            item_title = a.get("title")
            audiobooks.append(Audiobook(item_id, item_title))

        return audiobooks

    def _download_asset(self, url: str, dest_file: Path):

        if dest_file.exists():
            print(colored(f"File {dest_file} already exists! Skipping!", "yellow"))
            return

        resp = self.session.get(url, stream=True)
        resp.raise_for_status()

        content_length = int(resp.headers.get("Content-Length", -1))
        with open(dest_file, "wb") as f:
            for chunk in tqdm.tqdm(
                resp.iter_content(chunk_size=1024),
                total=content_length / 1024,
                unit="KB",
                desc=str(dest_file),
                leave=True,
            ):
                f.write(chunk)

    def download_audiobook(self, audiobook: Audiobook, dest_dir: Path):
        resp = self.session.get(
            f"https://{self.BASE_DOMAIN}/pl/my-shelf/audiobook/{audiobook.id}"
        )
        html = BeautifulSoup(resp.content, "html.parser")

        download_link = urlparse(html.find("a", text=re.compile("Pobierz")).get("href"))

        if download_link.path.endswith("/download-sample"):
            print(
                colored(
                    f"Audiobook {audiobook.title} is a sample - skipping...", "cyan"
                )
            )
            return

        [(_, token)] = parse_qsl(download_link.query)

        dest_dir = dest_dir / audiobook.id
        dest_dir.mkdir(exist_ok=True)

        self._download_asset(
            f"https://tools.{self.BASE_DOMAIN}/pl/cover/{audiobook.id}.jpg?token={token}",
            dest_dir / f"{audiobook.id}.jpg",
        )
        self._download_asset(
            f"https://fn.{self.BASE_DOMAIN}/pl/app/info/audiobook/{audiobook.id}/cue?token={token}",
            dest_dir / f"{audiobook.id}.cue",
        )
        self._download_asset(
            f"https://{self.BASE_DOMAIN}/pl/audiobook/{audiobook.id}/download",
            dest_dir / f"{audiobook.id}.mp3",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Audioteka library backup script")
    parser.add_argument("-u", "--username", type=str, help="Audioteka username")
    parser.add_argument("-p", "--password", type=str, help="Audioteka password")
    parser.add_argument(
        "-d",
        "--dest_dir",
        type=str,
        help="Directory where audiobooks will be downloaded",
        required=True,
    )

    args = parser.parse_args()

    if not args.username:
        args.username = input("Username: ")

    if not args.password:
        args.password = getpass.getpass()

    dest_dir = Path(args.dest_dir)
    dest_dir.mkdir(exist_ok=True)

    audioteka = AudiotekaClient()
    audioteka.login(args.username, args.password)

    if not audioteka.is_authenticated:
        print(colored("Provided credentials are not valid :( Could not log in.", "red"))
        return 1

    for audiobook in audioteka.shelf:
        print(colored(f"-> Downloading '{audiobook.title}'", "green"))
        audioteka.download_audiobook(audiobook, dest_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
