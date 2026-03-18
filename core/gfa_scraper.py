"""
네이버 성과형 디스플레이 광고(GFA) Selenium 스크래퍼.
광고주센터 로그인 → 광고 계정 선택 → 성과형 DA 클릭 → GFA 대시보드 데이터 수집.
"""
import logging
import os
import re
import time
from datetime import date
from pathlib import Path

import pyperclip
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = str(Path(__file__).parent.parent / "downloads" / "gfa")


class GfaAdsScraper:
    """네이버 GFA 광고 보고서 스크래퍼.

    플로우:
      1. 네이버 광고주센터(searchad.naver.com) 로그인
      2. 광고 계정 목록에서 대상 계정의 [성과형 DA] 버튼 클릭
      3. GFA 광고센터로 이동
      4. 대시보드/보고서 데이터 스크래핑
    """

    AD_CENTER_URL = "https://searchad.naver.com"
    # searchad.naver.com이 ads.naver.com으로 리다이렉트될 수 있음
    AD_CENTER_DOMAINS = ["searchad.naver.com", "ads.naver.com"]
    NAVER_LOGIN_URL = "https://nid.naver.com/nidlogin.login"
    # 직접 로그인 URL (팝업 차단 우회)
    DIRECT_LOGIN_URL = "https://nid.naver.com/nidlogin.login?url=https%3A%2F%2Fads.naver.com%2F"
    # 광고관리시스템 (검색광고 관리 → 계정 목록 페이지)
    AD_MANAGE_URL = "https://manage.searchad.naver.com/customers"

    def __init__(self, naver_id: str, naver_password: str,
                 ad_account_id: str = "",
                 headless: bool = False, download_dir: str = None):
        self.naver_id = naver_id
        self.naver_password = naver_password
        self.ad_account_id = str(ad_account_id).strip()  # 광고주센터 계정 고유번호
        self.headless = headless
        self.download_dir = download_dir or DOWNLOAD_DIR
        self.driver = None

        os.makedirs(self.download_dir, exist_ok=True)
        os.makedirs(os.path.join(self.download_dir, "debug"), exist_ok=True)

    # ══════════════════════════════════════════════
    #  브라우저 관리
    # ══════════════════════════════════════════════

    def _create_driver(self) -> webdriver.Chrome:
        """Chrome 드라이버 생성 (봇 감지 최소화 설정)."""
        options = Options()

        if self.headless:
            options.add_argument("--headless=new")

        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        prefs = {
            "download.default_directory": self.download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        }
        options.add_experimental_option("prefs", prefs)

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )

        return driver

    def start(self) -> None:
        """브라우저 시작."""
        logger.info("GFA 스크래퍼: 브라우저 시작")
        self.driver = self._create_driver()

    def close(self) -> None:
        """브라우저 종료."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            logger.info("GFA 스크래퍼: 브라우저 종료")

    # ══════════════════════════════════════════════
    #  유틸리티
    # ══════════════════════════════════════════════

    def get_screenshot(self, name: str = "screenshot") -> str:
        """스크린샷 저장."""
        if not self.driver:
            return ""
        path = os.path.join(self.download_dir, "debug", f"{name}.png")
        try:
            self.driver.save_screenshot(path)
            logger.info(f"스크린샷 저장: {path}")
            return path
        except Exception as e:
            logger.warning(f"스크린샷 실패: {e}")
            return ""

    def _save_debug_html(self, name: str) -> None:
        """디버그용 HTML 소스 저장."""
        if not self.driver:
            return
        path = os.path.join(self.download_dir, "debug", f"{name}.html")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            logger.info(f"디버그 HTML 저장: {path}")
        except Exception as e:
            logger.warning(f"디버그 HTML 저장 실패: {e}")

    def _find_element_multi(self, selectors: list, timeout: int = 10):
        """여러 셀렉터를 순차 시도하여 요소 찾기."""
        for sel_type, sel_value in selectors:
            try:
                elem = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((sel_type, sel_value))
                )
                return elem
            except Exception:
                continue
        return None

    def _dismiss_popups(self) -> None:
        """팝업/모달 닫기."""
        try:
            close_selectors = [
                "button.close", "button[aria-label='Close']",
                "[class*='modal'] button[class*='close']",
                "[class*='popup'] button[class*='close']",
                "[class*='dialog'] button[class*='close']",
                "button[class*='dismiss']",
            ]
            for sel in close_selectors:
                try:
                    buttons = self.driver.find_elements(By.CSS_SELECTOR, sel)
                    for btn in buttons:
                        if btn.is_displayed():
                            btn.click()
                            time.sleep(0.5)
                except Exception:
                    pass

            try:
                checkboxes = self.driver.find_elements(
                    By.XPATH,
                    "//*[contains(text(), '보지 않') or contains(text(), '하루 안')]"
                )
                for cb in checkboxes:
                    if cb.is_displayed():
                        cb.click()
                        time.sleep(0.3)
            except Exception:
                pass

            try:
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                time.sleep(0.5)
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"팝업 닫기 실패 (무시): {e}")

    # ══════════════════════════════════════════════
    #  STEP 1: 네이버 광고주센터 로그인
    # ══════════════════════════════════════════════

    def _is_ad_center(self, url: str) -> bool:
        """URL이 광고주센터인지 확인 (searchad/ads 둘 다)."""
        return any(domain in url for domain in self.AD_CENTER_DOMAINS)

    def _is_logged_in(self) -> bool:
        """광고주센터에 로그인되어 있는지 확인."""
        try:
            page_source = self.driver.page_source
            # 로그인 버튼이 보이면 미로그인
            if 'data-nclick="gnb.login"' in page_source:
                return False
            # 계정 정보나 로그아웃 버튼이 있으면 로그인 상태
            if 'data-nclick="gnb.logout"' in page_source or "로그아웃" in page_source:
                return True
            # 계정 목록이 보이면 로그인 상태
            if "계정 목록" in page_source or "광고 계정" in page_source:
                return True
            return False
        except Exception:
            return False

    def login(self) -> bool:
        """네이버 광고주센터에 로그인."""
        if not self.driver:
            self.start()

        logger.info(f"광고주센터 로그인 시도: {self.naver_id}")

        try:
            # 1단계: 광고주센터 접속하여 상태 확인
            self.driver.get(self.AD_CENTER_URL)
            time.sleep(3)

            current_url = self.driver.current_url
            logger.info(f"초기 URL: {current_url}")
            self.get_screenshot("01_initial_page")

            # 이미 네이버 로그인 페이지로 리다이렉트됨
            if "nid.naver.com" in current_url or "naver.com/login" in current_url:
                logger.info("네이버 로그인 페이지로 리다이렉트됨")
                return self._do_naver_login()

            # 광고주센터 페이지에 있는 경우
            if self._is_ad_center(current_url):
                # 이미 로그인된 상태인지 확인
                if self._is_logged_in():
                    logger.info("이미 광고주센터에 로그인된 상태")
                    self._dismiss_popups()
                    return True

                # 미로그인 → 팝업 닫고 로그인 페이지로 직접 이동
                logger.info("광고주센터 미로그인 상태. 네이버 로그인 페이지로 직접 이동...")
                self._dismiss_popups()
                time.sleep(1)

            # 2단계: 네이버 로그인 페이지로 직접 이동 (팝업 문제 우회)
            logger.info(f"직접 로그인 URL: {self.DIRECT_LOGIN_URL}")
            self.driver.get(self.DIRECT_LOGIN_URL)
            time.sleep(3)

            current_url = self.driver.current_url
            logger.info(f"로그인 페이지 URL: {current_url}")

            if "nid.naver.com" in current_url:
                return self._do_naver_login()

            # 이미 로그인되어 광고주센터로 리다이렉트됨
            if self._is_ad_center(current_url):
                logger.info("이미 로그인됨, 광고주센터로 리다이렉트됨")
                self._dismiss_popups()
                return True

            logger.error(f"로그인 페이지를 찾을 수 없음: {current_url}")
            self.get_screenshot("login_failed")
            self._save_debug_html("login_failed")
            return False

        except Exception as e:
            logger.error(f"광고주센터 로그인 실패: {e}", exc_info=True)
            self.get_screenshot("login_error")
            return False

    def _clipboard_paste(self, element, text: str) -> None:
        """클립보드를 이용한 텍스트 입력 (네이버 봇 감지 우회).

        네이버는 JavaScript element.value 설정과 일반 send_keys를 감지하므로
        pyperclip → Ctrl+V 방식으로 입력해야 합니다.
        """
        element.click()
        time.sleep(0.3)

        # 기존 값 전체 선택 후 삭제
        actions = ActionChains(self.driver)
        actions.key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
        time.sleep(0.1)
        actions.send_keys(Keys.DELETE).perform()
        time.sleep(0.2)

        # 클립보드에 복사 후 붙여넣기
        pyperclip.copy(text)
        time.sleep(0.1)
        actions = ActionChains(self.driver)
        actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
        time.sleep(0.5)

    def _do_naver_login(self) -> bool:
        """네이버 ID 로그인 수행 (클립보드 붙여넣기 방식)."""
        try:
            self.get_screenshot("02_naver_login_page")
            self._save_debug_html("02_naver_login_page")

            # ID 입력 필드 찾기
            id_field = self._find_element_multi([
                (By.ID, "id"),
                (By.NAME, "id"),
                (By.CSS_SELECTOR, "input#id"),
                (By.CSS_SELECTOR, "input[name='id']"),
            ], timeout=10)
            if not id_field:
                logger.error("아이디 입력 필드를 찾을 수 없음")
                self._save_debug_html("no_id_field")
                return False

            # 비밀번호 입력 필드 찾기
            pw_field = self._find_element_multi([
                (By.ID, "pw"),
                (By.NAME, "pw"),
                (By.CSS_SELECTOR, "input#pw"),
                (By.CSS_SELECTOR, "input[type='password']"),
            ], timeout=10)
            if not pw_field:
                logger.error("비밀번호 입력 필드를 찾을 수 없음")
                self._save_debug_html("no_pw_field")
                return False

            # 클립보드 붙여넣기로 아이디 입력
            logger.info("아이디 입력 (클립보드 붙여넣기)")
            self._clipboard_paste(id_field, self.naver_id)
            time.sleep(0.5)

            # 클립보드 붙여넣기로 비밀번호 입력
            logger.info("비밀번호 입력 (클립보드 붙여넣기)")
            self._clipboard_paste(pw_field, self.naver_password)
            time.sleep(0.5)

            self.get_screenshot("03_credentials_entered")

            # 로그인 버튼 클릭
            login_btn = self._find_element_multi([
                (By.ID, "log.login"),
                (By.CSS_SELECTOR, "button.btn_login"),
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[contains(@class, 'btn_login')]"),
            ], timeout=5)

            if login_btn:
                login_btn.click()
                logger.info("로그인 버튼 클릭")
            else:
                pw_field.send_keys(Keys.RETURN)
                logger.info("Enter 키로 로그인 시도")

            time.sleep(5)
            self.get_screenshot("04_after_login")

            current_url = self.driver.current_url
            logger.info(f"로그인 후 URL: {current_url}")

            # 캡차/2차인증/기기등록 체크
            if "nid.naver.com" in current_url:
                page_source = self.driver.page_source

                if "캡차" in page_source or "captcha" in page_source.lower():
                    logger.error("캡차 인증이 필요합니다. headless=False로 다시 시도하세요.")
                    self._save_debug_html("captcha_required")
                    self.get_screenshot("captcha_required")
                    return False

                # ── 2단계 인증 감지 ──
                if "2단계 인증" in page_source or "인증 알림" in page_source or "OTP" in page_source:
                    logger.warning("[2FA] 2단계 인증 필요! 핸드폰에서 인증을 승인해주세요...")
                    self.get_screenshot("2step_auth_required")

                    # "이 브라우저는 2단계 인증 없이 로그인" 체크박스 클릭 (다음 로그인부터 2FA 스킵)
                    try:
                        skip_2fa_selectors = [
                            "//input[@type='checkbox' and ancestor::*[contains(text(), '2단계')]]",
                            "//label[contains(text(), '2단계')]",
                            "//span[contains(text(), '2단계')]/preceding-sibling::input",
                            "//*[contains(text(), '2단계 인증') and contains(text(), '없이')]/preceding-sibling::*",
                            "//input[@type='checkbox']",
                        ]
                        for sel in skip_2fa_selectors:
                            try:
                                cb = self.driver.find_element(By.XPATH, sel)
                                if cb.is_displayed() and not cb.is_selected():
                                    cb.click()
                                    logger.info("'2단계 인증 없이 로그인' 체크박스 클릭 완료")
                                    time.sleep(0.5)
                                    break
                            except Exception:
                                continue
                    except Exception as e:
                        logger.debug(f"2FA 스킵 체크박스 클릭 실패 (무시): {e}")

                    # 최대 120초 대기 (5초 간격으로 확인)
                    for wait_count in range(24):
                        time.sleep(5)
                        current_url = self.driver.current_url
                        logger.info(f"2단계 인증 대기 중... ({(wait_count + 1) * 5}초) URL: {current_url}")

                        # nid.naver.com을 벗어나면 인증 성공
                        if "nid.naver.com" not in current_url:
                            logger.info("2단계 인증 승인 완료!")
                            self.get_screenshot("2step_auth_passed")
                            break
                    else:
                        logger.error("2단계 인증 시간 초과 (120초). 핸드폰에서 인증을 승인하지 않았습니다.")
                        self.get_screenshot("2step_auth_timeout")
                        self._save_debug_html("2step_auth_timeout")
                        return False

                    current_url = self.driver.current_url
                    logger.info(f"2단계 인증 후 URL: {current_url}")

                elif "새로운 기기" in page_source or "기기 등록" in page_source:
                    logger.warning("새 기기 인증이 필요할 수 있습니다")
                    self._save_debug_html("new_device_auth")
                    self.get_screenshot("new_device_auth")
                    # 기기 등록도 대기
                    for wait_count in range(12):
                        time.sleep(5)
                        current_url = self.driver.current_url
                        if "nid.naver.com" not in current_url:
                            break
                    current_url = self.driver.current_url
                else:
                    # 기타 nid 페이지 - 추가 대기
                    time.sleep(5)
                    current_url = self.driver.current_url
                    logger.info(f"추가 대기 후 URL: {current_url}")

            # 광고주센터로 이동 확인 (searchad.naver.com 또는 ads.naver.com)
            if self._is_ad_center(current_url):
                self._dismiss_popups()
                time.sleep(1)
                if self._is_logged_in():
                    logger.info("광고주센터 로그인 성공!")
                    self.get_screenshot("05_ad_center")
                    return True
                else:
                    logger.warning("광고주센터에 도달했지만 로그인 상태가 아닙니다")

            # naver.com 메인이나 다른 네이버 페이지에 있는 경우
            if "naver.com" in current_url and "nid.naver.com" not in current_url:
                logger.info("네이버 로그인 성공, 광고주센터로 직접 이동...")
                self.driver.get(self.AD_CENTER_URL)
                time.sleep(5)
                self._dismiss_popups()
                time.sleep(1)
                current_url = self.driver.current_url

                if self._is_ad_center(current_url) and self._is_logged_in():
                    logger.info("광고주센터 로그인 성공! (직접 이동)")
                    self.get_screenshot("05_ad_center")
                    return True

            # 최종 시도: 광고주센터로 직접 이동
            logger.info("광고주센터로 최종 이동 시도...")
            self.driver.get(self.AD_CENTER_URL)
            time.sleep(5)
            self._dismiss_popups()
            time.sleep(1)

            if self._is_ad_center(self.driver.current_url) and self._is_logged_in():
                logger.info("광고주센터 로그인 성공! (최종 직접 이동)")
                self.get_screenshot("05_ad_center")
                return True

            # 최종 상태 확인
            self.get_screenshot("login_final_fail")
            self._save_debug_html("login_final_fail")

            # 로그인 실패 원인 분석
            if "nid.naver.com" in self.driver.current_url:
                page_source = self.driver.page_source
                if "2단계" in page_source or "인증" in page_source:
                    logger.error("로그인 실패: 2단계 인증이 승인되지 않았습니다")
                else:
                    logger.error("로그인 실패: 네이버 로그인 페이지에 머물러 있습니다")
            else:
                logger.error(f"로그인 실패: 광고주센터에서 로그인 상태가 아닙니다. URL = {self.driver.current_url}")

            return False

        except Exception as e:
            logger.error(f"네이버 로그인 실패: {e}", exc_info=True)
            self.get_screenshot("naver_login_error")
            return False

    # ══════════════════════════════════════════════
    #  STEP 2: 광고 계정 선택 → 성과형 DA 클릭
    # ══════════════════════════════════════════════

    def navigate_to_gfa(self) -> bool:
        """GFA 대시보드로 직접 이동.

        광고주센터 HTML 분석 결과, 성과형 DA 버튼의 링크는:
          https://gfa.naver.com/adAccount/accounts/{ad_account_id}
        이 URL로 직접 이동하면 계정 목록 페이지네이션을 순회할 필요 없음.
        """
        logger.info(f"GFA 대시보드 직접 이동: 계정 고유번호 '{self.ad_account_id}'")

        try:
            # 방법 1: GFA 직접 URL로 이동 (가장 빠르고 안정적)
            gfa_direct_url = f"https://gfa.naver.com/adAccount/accounts/{self.ad_account_id}"
            logger.info(f"GFA 직접 URL: {gfa_direct_url}")
            self.driver.get(gfa_direct_url)
            time.sleep(5)

            self._dismiss_popups()
            time.sleep(2)

            current_url = self.driver.current_url
            logger.info(f"GFA 이동 후 URL: {current_url}")
            self.get_screenshot("07_gfa_page")
            self._save_debug_html("gfa_page")

            # GFA 페이지 확인
            if "gfa.naver.com" in current_url:
                logger.info("GFA 대시보드 이동 성공!")
                return True

            # GFA로 리다이렉트 안 된 경우 → 로그인이 안 되어 있을 수 있음
            # 네이버 로그인 페이지로 리다이렉트된 경우
            if "nid.naver.com" in current_url:
                logger.warning("GFA 접근 시 로그인 페이지로 리다이렉트됨. 이미 로그인 세션이 유지되어야 하는데...")
                self.get_screenshot("gfa_login_redirect")
                return False

            # 방법 2: 계정 목록에서 '성과형 DA' 버튼 직접 클릭 (폴백)
            logger.info("GFA 직접 이동 실패, 계정 목록에서 버튼 찾기 시도...")
            return self._find_gfa_in_account_list()

        except Exception as e:
            logger.error(f"GFA 이동 실패: {e}", exc_info=True)
            self.get_screenshot("navigate_gfa_error")
            return False

    def _find_gfa_in_account_list(self) -> bool:
        """계정 목록에서 해당 계정의 GFA 링크를 찾아 클릭 (폴백).

        계정 목록 구조 (Ant Design Table):
          - 각 행: data-row-key="{account_id}"
          - GFA 링크: <a href="https://gfa.naver.com/adAccount/accounts/{id}" data-nclick="account.gfa">
          - 페이지네이션: ant-pagination (ant-pagination-next, ant-pagination-item-N)
        """
        try:
            self.driver.get("https://ads.naver.com")
            time.sleep(3)
            self._dismiss_popups()
            time.sleep(2)

            self.get_screenshot("06_account_list")
            self._save_debug_html("account_list")

            max_pages = 10
            for page_num in range(max_pages):
                logger.info(f"계정 목록 페이지 {page_num + 1} 검색 중...")

                # 방법 A: data-row-key로 정확한 행 찾기
                try:
                    row = self.driver.find_element(
                        By.CSS_SELECTOR,
                        f"tr[data-row-key='{self.ad_account_id}']"
                    )
                    logger.info(f"계정 행 발견 (data-row-key): {row.text[:80]}")

                    # GFA 링크 클릭
                    gfa_link = row.find_element(
                        By.CSS_SELECTOR,
                        "a[data-nclick='account.gfa']"
                    )
                    if gfa_link:
                        gfa_url = gfa_link.get_attribute("href")
                        logger.info(f"GFA 링크 발견: {gfa_url}")
                        self.driver.get(gfa_url)
                        time.sleep(5)
                        self._dismiss_popups()
                        if "gfa.naver.com" in self.driver.current_url:
                            logger.info("GFA 대시보드 이동 성공! (계정 목록 경유)")
                            self.get_screenshot("07_gfa_page")
                            return True
                except Exception:
                    pass

                # 방법 B: 텍스트로 찾기
                try:
                    target = f"({self.ad_account_id})"
                    rows = self.driver.find_elements(By.CSS_SELECTOR, "tr.ant-table-row")
                    for r in rows:
                        if target in r.text:
                            gfa_btn = r.find_element(
                                By.XPATH,
                                ".//a[contains(@href, 'gfa.naver.com')] | "
                                ".//a[contains(text(), '성과형')]"
                            )
                            if gfa_btn:
                                gfa_url = gfa_btn.get_attribute("href")
                                logger.info(f"GFA 버튼 발견 (텍스트 검색): {gfa_url}")
                                self.driver.get(gfa_url)
                                time.sleep(5)
                                self._dismiss_popups()
                                if "gfa.naver.com" in self.driver.current_url:
                                    logger.info("GFA 대시보드 이동 성공!")
                                    self.get_screenshot("07_gfa_page")
                                    return True
                except Exception:
                    pass

                # 다음 페이지로 이동 (Ant Design pagination)
                if not self._go_to_next_page():
                    logger.info("마지막 페이지 도달")
                    break

            logger.error(f"계정 '{self.ad_account_id}'를 계정 목록에서 찾지 못함")
            self.get_screenshot("account_not_found")
            self._save_debug_html("account_not_found")
            return False

        except Exception as e:
            logger.error(f"계정 목록 검색 실패: {e}", exc_info=True)
            return False

    def _go_to_next_page(self) -> bool:
        """Ant Design 페이지네이션에서 다음 페이지로 이동."""
        try:
            # Ant Design: ant-pagination-next 클릭
            next_btn = self.driver.find_elements(
                By.CSS_SELECTOR,
                "li.ant-pagination-next:not(.ant-pagination-disabled) button"
            )
            if next_btn and next_btn[0].is_enabled():
                next_btn[0].click()
                time.sleep(2)
                logger.info("다음 페이지로 이동 (ant-pagination-next)")
                return True

            # 현재 활성 페이지 + 1 클릭
            active_items = self.driver.find_elements(
                By.CSS_SELECTOR,
                "li.ant-pagination-item-active"
            )
            if active_items:
                active_num = active_items[0].get_attribute("title")
                try:
                    next_num = int(active_num) + 1
                    next_item = self.driver.find_element(
                        By.CSS_SELECTOR,
                        f"li.ant-pagination-item-{next_num}"
                    )
                    next_item.click()
                    time.sleep(2)
                    logger.info(f"페이지 {next_num}으로 이동")
                    return True
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"다음 페이지 이동 실패: {e}")

        return False

    # ══════════════════════════════════════════════
    #  STEP 3: GFA 대시보드 데이터 수집
    # ══════════════════════════════════════════════

    def download_dashboard_data(self, date_from: date, date_to: date) -> dict:
        """대시보드 데이터 수집 (광고주센터 → GFA 이동 후)."""
        if not self.driver:
            logger.error("브라우저가 시작되지 않음")
            return None

        # 먼저 GFA 광고센터로 이동
        if not self.navigate_to_gfa():
            logger.error("GFA 광고센터로 이동 실패")
            return None

        logger.info(f"GFA 데이터 수집: {date_from} ~ {date_to}")

        # 방법 1: 현재 페이지(GFA 대시보드) DOM 스크래핑
        self._actual_date_range = None
        try:
            result = self._scrape_gfa_dashboard(date_from, date_to)
            if result and result.get("dom_data"):
                logger.info("GFA 대시보드 스크래핑 성공")
                # 실제 조회 기간 반영
                if self._actual_date_range:
                    result["actual_date_range"] = self._actual_date_range
                return result
        except Exception as e:
            logger.warning(f"대시보드 스크래핑 실패: {e}")

        # 방법 2: 내부 API 캡처
        try:
            result = self._capture_internal_api(date_from, date_to)
            if result and result.get("api_data"):
                logger.info("내부 API 캡처 성공")
                return result
        except Exception as e:
            logger.warning(f"내부 API 캡처 실패: {e}")

        # 방법 3: 캠페인 메뉴 이동 후 스크래핑
        try:
            result = self._scrape_campaign_page(date_from, date_to)
            if result and result.get("dom_data"):
                logger.info("캠페인 페이지 스크래핑 성공")
                return result
        except Exception as e:
            logger.warning(f"캠페인 페이지 스크래핑 실패: {e}")

        logger.error("모든 데이터 수집 방법 실패")
        self.get_screenshot("data_collection_failed")
        self._save_debug_html("data_collection_failed")
        return None

    def _scrape_gfa_dashboard(self, date_from: date, date_to: date) -> dict:
        """GFA 대시보드에서 데이터 수집.

        1단계: API 인터셉터 설치 → 페이지 리프레시 → 내부 API 캡처 (ROAS/전환매출 포함)
        2단계: DOM 테이블 스크래핑 (API 실패 시 폴백)
        """
        time.sleep(3)

        # ── 실제 조회 기간 감지 (날짜 변경 전!) ──
        try:
            actual_url = self.driver.current_url
            date_match = re.search(r'dateRange=(\d{4}-\d{2}-\d{2})(?:[,%]|%2C)(\d{4}-\d{2}-\d{2})', actual_url)
            if date_match:
                self._actual_date_range = (date_match.group(1), date_match.group(2))
                logger.info(f"GFA 기본 조회 기간: {self._actual_date_range[0]} ~ {self._actual_date_range[1]}")
        except Exception:
            pass

        self.get_screenshot("08_gfa_dashboard")
        self._save_debug_html("gfa_dashboard")

        # ※ 날짜를 변경하지 않고 GFA 기본 조회 기간(최근 7일 등) 데이터를 그대로 사용
        # 날짜는 URL에서 감지된 실제 기간이 리포트에 표시됨

        # 테이블 가로 스크롤 → 숨겨진 컬럼 로딩
        try:
            self.driver.execute_script("""
                const tb = document.querySelector('.ant-table-body');
                if (tb) { tb.scrollLeft = tb.scrollWidth; }
            """)
            time.sleep(1)
            self.driver.execute_script("""
                const tb = document.querySelector('.ant-table-body');
                if (tb) { tb.scrollLeft = 0; }
            """)
            time.sleep(1)
        except Exception:
            pass

        # JavaScript로 Ant Design 테이블에서 데이터 직접 추출
        extract_script = """
        const result = {headers: [], campaigns: []};

        // 1. 헤더 추출 (filter_alt 아이콘 텍스트 제거)
        const thElements = document.querySelectorAll('th.ant-table-cell');
        thElements.forEach(th => {
            let text = '';
            const spans = th.querySelectorAll('span');
            for (const span of spans) {
                const t = span.textContent.trim();
                if (t && t !== 'filter_alt' && !t.includes('arrow')) {
                    text = t;
                    break;
                }
            }
            if (!text) {
                text = th.textContent.replace('filter_alt', '').trim();
            }
            result.headers.push(text);
        });

        // 2. 데이터 행 추출
        const rows = document.querySelectorAll('tr.ant-table-row');
        rows.forEach(row => {
            const cells = row.querySelectorAll('td.ant-table-cell');
            const rowData = [];
            cells.forEach(td => {
                let text = td.textContent.trim();
                text = text.replace(/\\n/g, ' ').replace(/\\s+/g, ' ').trim();
                rowData.push(text);
            });
            if (rowData.length > 0) {
                result.campaigns.push(rowData);
            }
        });

        return result;
        """

        try:
            table_data = self.driver.execute_script(extract_script)
            if table_data:
                headers = table_data.get("headers", [])
                campaigns = table_data.get("campaigns", [])
                logger.info(f"GFA 테이블 추출: 헤더 {len(headers)}개, 캠페인 {len(campaigns)}개")
                logger.info(f"  헤더: {headers}")
                for i, row in enumerate(campaigns):
                    logger.info(f"  캠페인[{i}]: {row[:8]}...")

                if campaigns:
                    # GFA 전용 파싱으로 clean 데이터 생성
                    parsed = self._parse_gfa_table(headers, campaigns)

                    # 대시보드 상단 영역에서 추가 KPI(전환매출 등) 추출 시도
                    try:
                        extra_kpi = self.driver.execute_script("""
                            const result = {};
                            // 대시보드 상단 카드/그래프에서 값 추출
                            const allText = document.body.innerText || '';
                            // 전환매출 패턴
                            const patterns = [
                                /(?:전환매출|구매전환매출|전환\\s*매출액?)\\s*[:\\s]*[₩￦]?\\s*([0-9,]+)/,
                                /(?:총\\s*전환\\s*매출|conv.*?revenue)\\s*[:\\s]*[₩￦]?\\s*([0-9,]+)/i,
                                /ROAS\\s*[:\\s]*([0-9,.]+)\\s*%?/,
                            ];
                            for (const pat of patterns) {
                                const m = allText.match(pat);
                                if (m) {
                                    const key = pat.source.includes('ROAS') ? 'roas' : 'conv_revenue';
                                    result[key] = m[1].replace(/,/g, '');
                                }
                            }
                            return result;
                        """)
                        if extra_kpi:
                            logger.info(f"추가 KPI 추출: {extra_kpi}")
                            if "conv_revenue" in extra_kpi:
                                parsed["kpi"]["conv_revenue"] = extra_kpi["conv_revenue"]
                            if "roas" in extra_kpi:
                                parsed["kpi"]["roas"] = extra_kpi["roas"]
                    except Exception as e:
                        logger.debug(f"추가 KPI 추출 실패: {e}")

                    return {"dom_data": parsed}
        except Exception as e:
            logger.warning(f"JavaScript 테이블 추출 실패: {e}")

        # 폴백: 기존 방식
        kpi_data = self._extract_kpi_data()
        table_data = self._extract_table_data()

        if kpi_data or table_data.get("campaigns"):
            return {
                "dom_data": {
                    "kpi": kpi_data,
                    "campaigns": table_data.get("campaigns", []),
                    "headers": table_data.get("headers", []),
                }
            }
        return None

    def _parse_gfa_table(self, headers: list, campaigns: list) -> dict:
        """GFA Ant Design 테이블 데이터를 깨끗한 형식으로 변환.

        GFA 셀 값 예시:
          - "₩ 315,152" → 315152 (비용)
          - "76,494" → 76494 (노출)
          - "86 전환" → 86 (결과/전환)
          - "₩ 3,665 전환당" → 3665 (결과당 비용)
          - "0.82%" → 0.82 (CTR)
        """
        # 헤더 → 인덱스 매핑 (GFA 전용)
        col_idx = {}
        for i, h in enumerate(headers):
            h_clean = h.strip()
            if "캠페인 이름" in h_clean or "캠페인이름" in h_clean:
                col_idx["name"] = i
            elif h_clean == "상태":
                col_idx["status"] = i
            elif "캠페인 목적" in h_clean:
                col_idx["objective"] = i
            elif "캠페인 예산" in h_clean:
                col_idx["budget"] = i
            elif h_clean == "결과" or h_clean == "결과":
                col_idx["result"] = i
            elif "결과당" in h_clean:
                col_idx["cost_per_result"] = i
            elif "총비용" in h_clean or "비용" == h_clean:
                col_idx["cost"] = i
            elif h_clean == "노출" or h_clean == "노출수":
                col_idx["impressions"] = i
            elif h_clean == "CPM":
                col_idx["cpm"] = i
            elif h_clean == "클릭" or h_clean == "클릭수":
                col_idx["clicks"] = i
            elif h_clean == "CPC":
                col_idx["cpc"] = i
            elif h_clean == "CTR" or h_clean == "클릭률":
                col_idx["ctr"] = i
            elif "ROAS" in h_clean or "roas" in h_clean:
                col_idx["roas"] = i
            elif "전환매출" in h_clean or "전환 매출" in h_clean or "구매" in h_clean:
                col_idx["conv_revenue"] = i
            elif "총 전환" in h_clean:
                col_idx["total_conversions"] = i

        logger.info(f"GFA 컬럼 매핑: {col_idx}")

        # 표준 헤더 이름으로 변환
        std_headers = ["캠페인 이름", "총비용", "노출", "클릭", "전환", "CTR", "CPC", "CPM"]

        parsed_campaigns = []
        for row in campaigns:
            if len(row) < 3:
                continue

            # 캠페인 이름 추출 (숫자 ID 제거)
            name_raw = row[col_idx.get("name", 2)] if col_idx.get("name", 2) < len(row) else ""
            name = re.sub(r'\s*\d{5,}$', '', name_raw).strip()
            if not name:
                continue

            def clean_val(idx_key, default_idx=None):
                """셀 값에서 숫자만 추출."""
                idx = col_idx.get(idx_key, default_idx)
                if idx is None or idx >= len(row):
                    return "0"
                val = row[idx]
                val = val.replace("₩", "").replace("￦", "")
                val = re.sub(r'[가-힣]+.*$', '', val)
                val = val.replace(",", "").strip()
                val = val.replace("%", "").strip()
                return val if val else "0"

            cost = clean_val("cost", 8)
            impressions = clean_val("impressions", 9)
            clicks = clean_val("clicks", 11)
            cpc = clean_val("cpc", 12)
            ctr = clean_val("ctr", 13)
            cpm = clean_val("cpm", 10)

            # 결과(전환) 추출 - "86 전환" → "86"
            result_raw = row[col_idx.get("result", 6)] if col_idx.get("result", 6) < len(row) else "0"
            conversions = re.sub(r'[^\d]', '', result_raw.split()[0] if result_raw.split() else "0")

            # 결과당 비용 추출 - "₩ 3,665 전환당" → "3665"
            cost_per_result = clean_val("cost_per_result", 7)

            # 상태/목적/예산 추출
            status = row[col_idx.get("status", 3)] if col_idx.get("status", 3) < len(row) else ""
            objective = row[col_idx.get("objective", 4)] if col_idx.get("objective", 4) < len(row) else ""
            budget_raw = row[col_idx.get("budget", 5)] if col_idx.get("budget", 5) < len(row) else ""

            # 예산 파싱 - "₩ 50,000 예산 소진율 32%"
            budget_val = "0"
            budget_usage = ""
            if budget_raw:
                budget_clean = budget_raw.replace("₩", "").replace("￦", "").strip()
                budget_num_match = re.match(r'[\s]*([\d,]+)', budget_clean)
                if budget_num_match:
                    budget_val = budget_num_match.group(1).replace(",", "")
                usage_match = re.search(r'(\d+)%', budget_raw)
                if usage_match:
                    budget_usage = usage_match.group(1) + "%"

            parsed_row = [name, cost, impressions, clicks, conversions, ctr, cpc, cpm]
            parsed_campaigns.append(parsed_row)

            # 확장 데이터를 별도 저장 (parse_gfa_dom_data에서 활용)
            if not hasattr(self, '_campaign_extra'):
                self._campaign_extra = []
            self._campaign_extra.append({
                "name": name,
                "status": status,
                "objective": objective,
                "budget": budget_val,
                "budget_usage": budget_usage,
                "cost_per_result": cost_per_result,
            })

            logger.info(
                f"  파싱 결과: {name} | 상태:{status} 목적:{objective} "
                f"예산:{budget_val}({budget_usage}) 비용:{cost} 노출:{impressions} "
                f"클릭:{clicks} 전환:{conversions} CTR:{ctr}%"
            )

        return {
            "kpi": {},
            "headers": std_headers,
            "campaigns": parsed_campaigns,
            "extra": getattr(self, '_campaign_extra', []),
        }

    def _capture_gfa_api_on_date_change(self, date_from: date, date_to: date) -> list:
        """API 인터셉터를 설치하고 날짜를 변경하여 GFA 내부 API 응답 캡처.

        GFA 내부 API는 테이블에 표시되지 않는 전환매출, ROAS 등 전체 지표를 포함.
        """
        try:
            # 1. fetch/XHR 인터셉터 설치
            self.driver.execute_script("""
                window.__gfa_api = [];
                const origFetch = window.fetch;
                window.fetch = function(...args) {
                    const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
                    return origFetch.apply(this, args).then(async resp => {
                        try {
                            if (url.includes('/api/') || url.includes('/campaign') ||
                                url.includes('/stat') || url.includes('/report') ||
                                url.includes('/dashboard') || url.includes('/summary') ||
                                url.includes('/performance') || url.includes('/adAccount')) {
                                const clone = resp.clone();
                                const data = await clone.json();
                                window.__gfa_api.push({url: url, data: data, status: resp.status});
                            }
                        } catch(e) {}
                        return resp;
                    });
                };
                const origXHR = XMLHttpRequest.prototype.open;
                XMLHttpRequest.prototype.open = function(method, url, ...rest) {
                    this._gfa_url = url;
                    return origXHR.call(this, method, url, ...rest);
                };
                const origSend = XMLHttpRequest.prototype.send;
                XMLHttpRequest.prototype.send = function(...args) {
                    this.addEventListener('load', function() {
                        const url = this._gfa_url || '';
                        if (url.includes('/api/') || url.includes('/campaign') ||
                            url.includes('/stat') || url.includes('/report') ||
                            url.includes('/dashboard') || url.includes('/summary') ||
                            url.includes('/performance') || url.includes('/adAccount')) {
                            try {
                                const data = JSON.parse(this.responseText);
                                window.__gfa_api.push({url: url, data: data, status: this.status});
                            } catch(e) {}
                        }
                    });
                    return origSend.apply(this, args);
                };
            """)
            logger.info("GFA API 인터셉터 설치 완료")

            # 2. 페이지 새로고침 (API 호출 트리거)
            self.driver.refresh()
            time.sleep(8)

            # 3. 캡처된 API 데이터 확인
            api_data = self.driver.execute_script("return window.__gfa_api || [];")
            if api_data:
                logger.info(f"GFA API 캡처 성공: {len(api_data)}개 응답")
                for i, item in enumerate(api_data):
                    url = item.get("url", "")
                    data = item.get("data")
                    data_preview = str(data)[:200] if data else "empty"
                    logger.info(f"  API[{i}]: {url[:100]} → {data_preview}")

                # 실제 조회 기간 다시 감지
                try:
                    actual_url = self.driver.current_url
                    dm = re.search(r'dateRange=(\d{4}-\d{2}-\d{2})(?:[,%]|%2C)(\d{4}-\d{2}-\d{2})', actual_url)
                    if dm:
                        self._actual_date_range = (dm.group(1), dm.group(2))
                except Exception:
                    pass

                return api_data
            else:
                logger.warning("GFA API 캡처 결과 없음")

        except Exception as e:
            logger.warning(f"GFA API 캡처 실패: {e}")

        return None

    def _try_set_gfa_date(self, date_from: date, date_to: date) -> bool:
        """GFA 대시보드 날짜 설정 (URL 파라미터 방식)."""
        try:
            current_url = self.driver.current_url
            # URL에 dateRange 파라미터 추가/변경
            date_str = f"{date_from.strftime('%Y-%m-%d')},{date_to.strftime('%Y-%m-%d')}"
            if "dateRange=" in current_url:
                new_url = re.sub(r'dateRange=[^&]*', f'dateRange={date_str}', current_url)
            else:
                separator = "&" if "?" in current_url else "?"
                new_url = f"{current_url}{separator}dateRange={date_str}&period=custom"

            if new_url != current_url:
                logger.info(f"GFA 날짜 설정: {date_from} ~ {date_to}")
                self.driver.get(new_url)
                time.sleep(5)
                return True
        except Exception as e:
            logger.warning(f"GFA 날짜 설정 실패: {e}")
        return False

    def _scrape_campaign_page(self, date_from: date, date_to: date) -> dict:
        """캠페인 메뉴로 이동 후 스크래핑."""
        try:
            menu_items = self.driver.find_elements(
                By.XPATH,
                "//*[contains(text(), '캠페인') and (self::a or self::button or self::span or self::li)]"
            )
            for item in menu_items[:3]:
                try:
                    if item.is_displayed():
                        item.click()
                        time.sleep(3)
                        break
                except Exception:
                    continue

            self.get_screenshot("09_campaign_page")
            self._save_debug_html("campaign_page")

            # GFA 전용 스크래핑 재시도
            return self._scrape_gfa_dashboard(date_from, date_to)

        except Exception as e:
            logger.warning(f"캠페인 페이지 이동 실패: {e}")

        return None

    def _capture_internal_api(self, date_from: date, date_to: date) -> dict:
        """내부 API 응답 캡처 (fetch 인터셉트)."""
        intercept_script = """
        window.__gfa_api = [];
        const origFetch = window.fetch;
        window.fetch = function(...args) {
            const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
            const keywords = ['/api/', '/report', '/stat', '/campaign', '/dashboard',
                              '/performance', '/adSet', '/creative', '/summary'];
            const shouldCapture = keywords.some(k => url.toLowerCase().includes(k.toLowerCase()));
            return origFetch.apply(this, args).then(async resp => {
                if (shouldCapture) {
                    try {
                        const clone = resp.clone();
                        const data = await clone.json();
                        window.__gfa_api.push({url: url, data: data, status: resp.status});
                    } catch(e) {}
                }
                return resp;
            });
        };

        const origXHR = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url, ...rest) {
            this._gfa_url = url;
            return origXHR.call(this, method, url, ...rest);
        };
        const origSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.send = function(...args) {
            this.addEventListener('load', function() {
                const url = this._gfa_url || '';
                const keywords = ['/api/', '/report', '/stat', '/campaign', '/dashboard',
                                  '/performance', '/adSet', '/creative', '/summary'];
                const shouldCapture = keywords.some(k => url.toLowerCase().includes(k.toLowerCase()));
                if (shouldCapture) {
                    try {
                        const data = JSON.parse(this.responseText);
                        window.__gfa_api.push({url: url, data: data, status: this.status});
                    } catch(e) {}
                }
            });
            return origSend.apply(this, args);
        };
        """
        self.driver.execute_script(intercept_script)

        # 페이지 새로고침으로 API 호출 트리거
        self.driver.refresh()
        time.sleep(8)

        # 캠페인/보고서 메뉴 클릭으로 추가 API 호출 트리거
        try:
            menu_items = self.driver.find_elements(
                By.XPATH,
                "//*[contains(text(), '캠페인') or contains(text(), '보고서') or contains(text(), '리포트')]"
            )
            for item in menu_items[:2]:
                try:
                    if item.is_displayed():
                        item.click()
                        time.sleep(3)
                except Exception:
                    pass
        except Exception:
            pass

        api_data = self.driver.execute_script("return window.__gfa_api || [];")

        if api_data:
            logger.info(f"내부 API 캡처: {len(api_data)}개 응답")
            for i, item in enumerate(api_data):
                logger.info(f"  API [{i}]: {item.get('url', 'unknown')}")
            return {"api_data": api_data}

        return None

    # ══════════════════════════════════════════════
    #  날짜 / KPI / 테이블 추출
    # ══════════════════════════════════════════════

    def _try_set_date_range(self, date_from: date, date_to: date) -> bool:
        """날짜 범위 설정 시도."""
        try:
            date_selectors = [
                "input[type='date']",
                "input[class*='date']",
                "[class*='datepicker'] input",
                "[class*='date-range'] input",
                "[class*='DatePicker'] input",
            ]
            for sel in date_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, sel)
                    if len(elements) >= 2:
                        elements[0].clear()
                        elements[0].send_keys(date_from.strftime("%Y-%m-%d"))
                        elements[1].clear()
                        elements[1].send_keys(date_to.strftime("%Y-%m-%d"))
                        time.sleep(1)
                        apply_btn = self._find_element_multi([
                            (By.XPATH, "//button[contains(text(), '조회')]"),
                            (By.XPATH, "//button[contains(text(), '적용')]"),
                            (By.XPATH, "//button[contains(text(), '확인')]"),
                        ], timeout=3)
                        if apply_btn:
                            apply_btn.click()
                            time.sleep(3)
                        logger.info(f"날짜 범위 설정: {date_from} ~ {date_to}")
                        return True
                except Exception:
                    continue
            logger.warning("날짜 피커를 찾을 수 없음")
            return False
        except Exception as e:
            logger.warning(f"날짜 설정 실패: {e}")
            return False

    def _extract_kpi_data(self) -> dict:
        """페이지에서 KPI 요약 데이터 추출."""
        try:
            page_text = self.driver.execute_script("return document.body.innerText")
            return self._parse_kpi_from_text(page_text)
        except Exception as e:
            logger.warning(f"KPI 추출 실패: {e}")
            return {}

    def _parse_kpi_from_text(self, text: str) -> dict:
        """텍스트에서 KPI 패턴 매칭."""
        kpi = {}
        patterns = {
            "impressions": [r"노출(?:수)?\s*[:\s]*([0-9,]+)", r"(?:광고\s*)?노출\s*([0-9,]+)"],
            "clicks": [r"클릭(?:수)?\s*[:\s]*([0-9,]+)", r"(?:광고\s*)?클릭\s*([0-9,]+)"],
            "cost": [r"(?:광고비|비용|소진액|집행)\s*[:\s]*([0-9,]+)\s*원?"],
            "conversions": [r"전환(?:수)?\s*[:\s]*([0-9,]+)"],
            "conv_revenue": [r"전환\s*(?:매출|수익)\s*[:\s]*([0-9,]+)"],
            "ctr": [r"CTR\s*[:\s]*([0-9.]+)\s*%?", r"클릭률\s*[:\s]*([0-9.]+)"],
            "roas": [r"ROAS\s*[:\s]*([0-9,.]+)\s*%?", r"광고\s*수익률\s*[:\s]*([0-9,.]+)"],
        }
        for key, pats in patterns.items():
            for pat in pats:
                m = re.search(pat, text)
                if m:
                    val_str = m.group(1).replace(",", "")
                    try:
                        kpi[key] = float(val_str) if "." in val_str else int(val_str)
                    except ValueError:
                        pass
                    break
        logger.info(f"KPI 추출 결과: {kpi}")
        return kpi

    def _extract_table_data(self) -> dict:
        """페이지의 테이블에서 캠페인 데이터 추출."""
        result = {"headers": [], "campaigns": []}
        try:
            # HTML 테이블
            tables = self.driver.find_elements(By.CSS_SELECTOR, "table")
            for table in tables:
                data = self._parse_html_table(table)
                if data and data.get("campaigns"):
                    return data

            # AG-Grid
            ag_data = self._parse_ag_grid()
            if ag_data and ag_data.get("campaigns"):
                return ag_data

            # Ant Design 테이블
            ant_data = self._parse_ant_table()
            if ant_data and ant_data.get("campaigns"):
                return ant_data

            # div 기반 테이블
            div_data = self._parse_div_table()
            if div_data and div_data.get("campaigns"):
                return div_data
        except Exception as e:
            logger.warning(f"테이블 추출 실패: {e}")
        return result

    def _parse_html_table(self, table) -> dict:
        """일반 HTML <table> 파싱."""
        try:
            th_elements = table.find_elements(By.CSS_SELECTOR, "thead th")
            if not th_elements:
                th_elements = table.find_elements(By.CSS_SELECTOR, "tr:first-child th")
            headers = [th.text.strip() for th in th_elements if th.text.strip()]

            tr_elements = table.find_elements(By.CSS_SELECTOR, "tbody tr")
            if not tr_elements:
                tr_elements = table.find_elements(By.CSS_SELECTOR, "tr")[1:]
            rows = []
            for tr in tr_elements:
                cells = tr.find_elements(By.CSS_SELECTOR, "td")
                row = [cell.text.strip() for cell in cells]
                if any(row):
                    rows.append(row)

            if headers and rows:
                return {"headers": headers, "campaigns": rows}
        except Exception as e:
            logger.debug(f"HTML 테이블 파싱 실패: {e}")
        return None

    def _parse_ag_grid(self) -> dict:
        """AG-Grid 테이블 파싱."""
        try:
            ag_root = self.driver.find_elements(By.CSS_SELECTOR, ".ag-root-wrapper, [class*='ag-theme']")
            if not ag_root:
                return None
            headers = self.driver.execute_script("""
                const cells = document.querySelectorAll('.ag-header-cell-text');
                return Array.from(cells).map(el => el.textContent.trim()).filter(t => t);
            """)
            rows = self.driver.execute_script("""
                const result = [];
                document.querySelectorAll('.ag-row').forEach(row => {
                    const cells = row.querySelectorAll('.ag-cell');
                    const data = Array.from(cells).map(c => c.textContent.trim());
                    if (data.some(d => d)) result.push(data);
                });
                return result;
            """)
            if headers and rows:
                return {"headers": headers, "campaigns": rows}
        except Exception as e:
            logger.debug(f"AG-Grid 파싱 실패: {e}")
        return None

    def _parse_ant_table(self) -> dict:
        """Ant Design 테이블 파싱."""
        try:
            tables = self.driver.find_elements(By.CSS_SELECTOR, ".ant-table-content table")
            if tables:
                return self._parse_html_table(tables[0])
        except Exception as e:
            logger.debug(f"Ant 테이블 파싱 실패: {e}")
        return None

    def _parse_div_table(self) -> dict:
        """div 기반 테이블 파싱."""
        try:
            data = self.driver.execute_script("""
                const result = {headers: [], campaigns: []};
                const headerRow = document.querySelector(
                    '[class*="header-row"], [class*="table-header"], [class*="thead"]'
                );
                if (headerRow) {
                    const cells = headerRow.querySelectorAll('[class*="cell"], [class*="col"], div > span');
                    result.headers = Array.from(cells).map(c => c.textContent.trim()).filter(t => t);
                }
                const dataRows = document.querySelectorAll(
                    '[class*="body-row"], [class*="table-row"], [class*="tbody"] > div'
                );
                dataRows.forEach(row => {
                    const cells = row.querySelectorAll('[class*="cell"], [class*="col"], div > span');
                    const rowData = Array.from(cells).map(c => c.textContent.trim());
                    if (rowData.some(d => d)) result.campaigns.push(rowData);
                });
                return result;
            """)
            if data and (data.get("headers") or data.get("campaigns")):
                return data
        except Exception as e:
            logger.debug(f"div 테이블 파싱 실패: {e}")
        return None
