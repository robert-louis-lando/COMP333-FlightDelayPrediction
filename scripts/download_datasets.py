"""Download only the BTS airport reference and all 12 monthly 2024 flight ZIPs."""

from __future__ import annotations

import argparse
import http.cookiejar
import html
import os
from pathlib import Path
import re
import shutil
import urllib.parse
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
AIRPORT_FORM = (
    "https://www.transtats.bts.gov/DL_SelectFields.aspx?"
    "QO_fu146_anzr=N8vn6v10+f722146+gnoyr5&gnoyr_VQ=FLL"
)
FLIGHT_URL = "https://www.transtats.bts.gov/PREZIP/"
FLIGHT_FILE = "On_Time_Marketing_Carrier_On_Time_Performance_Beginning_January_2018_2024_{}.zip"


def make_client() -> urllib.request.OpenerDirector:
    """Keep cookies between the BTS airport form request and its download."""
    client = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    client.addheaders = [("User-Agent", "COMP333 dataset downloader")]
    return client


def download_zip(
    client: urllib.request.OpenerDirector,
    source: str | urllib.request.Request,
    path: Path,
    force: bool,
) -> None:
    """Download one ZIP safely and keep an existing complete file by default."""
    if path.is_file() and not force:
        print(f"Already downloaded: {path.relative_to(ROOT)}")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    try:
        print(f"Downloading: {path.name}")
        with client.open(source, timeout=120) as response, partial.open("wb") as output:
            if "text/html" in response.headers.get("Content-Type", ""):
                raise ValueError("BTS returned a web page instead of a ZIP")
            shutil.copyfileobj(response, output)

        with zipfile.ZipFile(partial) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"ZIP integrity check failed: {path.name}")
        os.replace(partial, path)
        print(f"Saved: {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")
    finally:
        if partial.exists():
            partial.unlink()


def airport_download_request(client: urllib.request.OpenerDirector) -> urllib.request.Request:
    """Select all fields on the BTS Master Coordinate download form."""
    with client.open(AIRPORT_FORM, timeout=120) as response:
        page = response.read().decode("utf-8")

    hidden = {
        name: html.unescape(value)
        for name, value in re.findall(
            r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page
        )
    }
    field_names = re.findall(r'<label for="([^"]+)">[^<]+</label>', page)
    if "__VIEWSTATE" not in hidden or not field_names:
        raise RuntimeError("Could not read the expected BTS airport download form")

    hidden.update({name: "on" for name in field_names})
    hidden.update(cboGeography="All", cboYear="All", cboPeriod="All", btnDownload="Download")
    request = urllib.request.Request(
        AIRPORT_FORM,
        data=urllib.parse.urlencode(hidden).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    # The form response contains the ZIP bytes, so save it directly to the final path.
    return request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="download again over existing ZIP files")
    args = parser.parse_args()
    client = make_client()

    print("Step 1/2: download the 12 monthly flight ZIPs (Jan-Dec 2024).")
    flights_dir = ROOT / "data/raw/bts/flights"
    for month in range(1, 13):
        filename = FLIGHT_FILE.format(month)
        download_zip(client, FLIGHT_URL + filename, flights_dir / filename, args.force)

    print("Step 2/2: download the complete BTS Master Coordinate airport ZIP.")
    airport_path = ROOT / "data/raw/bts/airports/T_MASTER_CORD.zip"
    if airport_path.is_file() and not args.force:
        print(f"Already downloaded: {airport_path.relative_to(ROOT)}")
    else:
        download_zip(client, airport_download_request(client), airport_path, args.force)

    print("Done. ZIP files are saved under data/raw/bts/.")


if __name__ == "__main__":
    main()
