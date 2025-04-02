import contextlib
import subprocess
import sys
import re
from pathlib import Path
from collections.abc import Iterator

import undetected_chromedriver as uc  # type: ignore

CHROMEDRIVER_PATH = (
    Path.home()
    / ".local"
    / "share"
    / "undetected_chromedriver"
    / "undetected_chromedriver"
)


class ChromeDriverDoesNotExist(Exception):
    pass

class ChromeDoesNotExist(Exception):
    pass

@contextlib.contextmanager
def chrome_driver(headless: bool = True) -> Iterator[uc.Chrome]:
    options = uc.ChromeOptions()
    options.headless = headless
    for option in [
        "--incognito",
        "--no-sandbox",
        "--disable-extensions",
        "--disable-application-cache",
        "--disable-gpu",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
    ]:
        options.add_argument(option)
    if headless:
        options.add_argument("--headless=new")
    version_main = re.findall('(\\d+)\\.', chrome_version())
    if len(version_main) > 0:
        version_main = version_main[0]
    driver = uc.Chrome(options=options, version_main=int(version_main))
    yield driver
    driver.quit()

def chrome_version() -> str:
    chrome_path = Path('/usr/bin/google-chrome')
    if not chrome_path.is_file():
        raise ChromeDoesNotExist(
            f"Error: {chrome_path} does not exist"
        )
    cmd = [str(chrome_path), "--version"]
    result = subprocess.run(cmd, capture_output=True)
    return result.stdout.decode()

def chrome_driver_version() -> str:
    if not CHROMEDRIVER_PATH.is_file():
        raise ChromeDriverDoesNotExist(
            f"Error: {CHROMEDRIVER_PATH} does not exist"
        )
    cmd = [str(CHROMEDRIVER_PATH), "--version"]
    print(f"+ {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True)
    return result.stdout.decode()

def init() -> None:
#    with contextlib.suppress(ChromeDriverDoesNotExist):
#        print(chrome_driver_version())
#        return
    print("Initializing Chrome Driver")
    with chrome_driver() as driver:
        print("Connect to example.com")
        driver.get("https://example.com")
    print(chrome_driver_version())
