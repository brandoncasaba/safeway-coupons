import contextlib
import json
import select
import sys
import time
import urllib
import requests
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Optional

import requests
import selenium.webdriver.support.expected_conditions as ec
import undetected_chromedriver as uc  # type: ignore
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.remote.webdriver import By
from selenium.webdriver.support.wait import WebDriverWait

from .accounts import Account
from .chrome_driver import chrome_driver
from .errors import AuthenticationFailure


class ExceptionWithAttachments(Exception):
    def __init__(
        self,
        *args: Any,
        attachments: Optional[list[Path]] = None,
        **kwargs: Any,
    ):
        self.attachments = attachments


class BaseSession:
    USER_AGENT = ( "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36" )

    @property
    def requests(self) -> requests.Session:
        if not hasattr(self, "_requests"):
            session = requests.Session()
            session.mount(
                "https://", requests.adapters.HTTPAdapter(pool_maxsize=1)
            )
            session.headers.update({"DNT": "1", "User-Agent": self.USER_AGENT})
            self._requests = session
        return self._requests


class LoginSession(BaseSession):
    def __init__(self, account: Account, interactive_sign_in: bool, debug_dir: Optional[Path]) -> None:
        self.access_token: Optional[str] = None
        self.store_id: Optional[str] = None
        self.interactive_sign_in = interactive_sign_in
        self.debug_dir: Optional[Path] = debug_dir
        try:
            self._login(account)
        except ExceptionWithAttachments as e:
            raise AuthenticationFailure(
                e, account, attachments=e.attachments
            ) from e
        except Exception as e:
            raise AuthenticationFailure(e, account) from e

    @contextlib.contextmanager
    def _chrome_driver(self, headless: bool = True) -> Iterator[uc.Chrome]:
        try:
            with chrome_driver(headless=headless) as driver:
                yield driver
        except WebDriverException as e:
            attachments: list[Path] = []
            if self.debug_dir:
                path = self.debug_dir / "screenshot.png"
                with contextlib.suppress(WebDriverException):
                    driver.save_screenshot(path)
                    attachments.append(path)
            raise ExceptionWithAttachments(
                f"[{type(e).__name__}] {e}", attachments=attachments
            ) from e
        finally:
            driver.quit()

    @staticmethod
    def _sign_in_success(driver: uc.Chrome) -> bool:
        try:
            element = driver.find_element(
                By.XPATH, '//span [contains(@class, "user-greeting")]'
            )
            if not (element and element.text):
                return False
            return not element.text.lower().startswith("sign in")
        except (StaleElementReferenceException, NoSuchElementException):
            return False

    @staticmethod
    def _element_exists(driver: uc.Chrome, id: str) -> bool:
        try:
            driver.find_element("id", id)
        except NoSuchElementException:
            return False
        return True
    
    @staticmethod
    def _get_code_from_human(timeout=290, interval=10) -> str:
        print("Wait for the SMS OTP code and enter it in the terminal (5 minute max): ", end="", flush=True)
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if ready:
            return sys.stdin.readline().strip()
        else:
            raise Exception("Timeout waiting for OTP")

    def _login(self, account: Account) -> None:
        with self._chrome_driver() as driver:
            driver.implicitly_wait(10)
            wait = WebDriverWait(driver, 10)
            # Navigate to the website URL
            url = "https://www.safeway.com/account/sign-in.html"
            print("Connect to safeway.com/account/sign-in.html")
            driver.get(url)
            #driver.delete_all_cookies() # uncomment to clear cookies
            #driver.get(url)
            try:
                button = driver.find_element(
                    By.XPATH,
                    "//button [contains(text(), 'Necessary Only')]",
                )
                if button:
                    print("Decline cookie prompt")
                    button.click()
                    print(
                        "Return to safeway.com after declining cookie prompt"
                    )
                    driver.get(url)
            except NoSuchElementException:
                print("Skipping cookie prompt which is not present")
            time.sleep(2)

            # Check if already signed in
            if not self._sign_in_success(driver):
                time.sleep(2)
                print("Populate Sign In form")

                # Support new and old sign in flows
                if self._element_exists(driver, "label-email"):
                    driver.find_element(By.ID, "label-email").send_keys(
                        account.username
                    )
                    driver.find_element(By.ID, "label-password").send_keys(
                        account.password
                    )
                    time.sleep(0.5)
                    print("Click Sign In button")
                    driver.find_element("id", "btnSignIn").click()
                else:
                    driver.find_element(By.ID, "enterUsername").send_keys(
                        account.username
                    )
                    time.sleep(0.5)
                    print("Click Sign in with password button")
                    driver.find_element(By.XPATH, '//button[contains(text(), "Sign in with password")]').click()
                    time.sleep(2)
                    print("Populate password")
                    driver.find_element(By.ID, "password").send_keys(
                        account.password
                    )
                    time.sleep(0.5)
                    print("Click Sign In button")
                    driver.find_element(By.XPATH, '//button[contains(text(), "Sign In")]').click()
                time.sleep(2)

                # Check for verify device
                print("Check for verify device required")
                if self._element_exists(driver, "verifyOptionForm"):
                    if not self.interactive_sign_in:
                        raise Exception(
                            "Interactive sign-in required, but not enabled. Run with --interactive-sign-in"
                        )
                    print("Click Text code")
                    driver.find_element(By.XPATH, '//span[contains(text(), "Text code to")]').click()
                    time.sleep(0.5)
                    print("Click Continue button")
                    driver.find_element(By.XPATH, '//button[contains(text(), "Continue")]').click()

                    code = self._get_code_from_human()
                    print("Typing code " + code + " in to field")
                    driver.find_element(By.XPATH, '//input[@formcontrolname="otpCode"]').send_keys(code)
                    time.sleep(0.5)
                    driver.find_element(By.XPATH, '//button[contains(text(), "Sign In")]').click()
                    time.sleep(2)
                    if self._element_exists(driver, "verifyOptionForm"):
                        raise Exception("Code not accepted")

                # Check for sign in success
                print("Wait for signed in landing page to load")
                element = driver.find_element(
                    By.XPATH, '//span [contains(@class, "user-greeting")]'
                )
                if not self._sign_in_success(driver):
                    raise Exception("Sign in failure, unable to verify user is signed in")
                               
            print("Retrieve session information")
            session_cookie = self._parse_cookie_value(
                driver.get_cookie("SWY_SHARED_SESSION")["value"]
            )
            session_info_cookie = self._parse_cookie_value(
                driver.get_cookie("SWY_SHARED_SESSION_INFO")["value"]
            )
            self.access_token = session_cookie["accessToken"]
            try:
                self.store_id = session_info_cookie["info"]["J4U"]["storeId"]
            except Exception as e:
                raise Exception("Unable to retrieve store ID") from e

    def _parse_cookie_value(self, value: str) -> Any:
        return json.loads(urllib.parse.unquote(value))
