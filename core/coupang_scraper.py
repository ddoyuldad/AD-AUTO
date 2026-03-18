"""
쿠팡 광고센터 Selenium 스크래퍼.
advertising.coupang.com에 로그인하여 광고 보고서를 엑셀로 다운로드.
"""
import glob
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)

# 다운로드 폴더 (프로젝트 내부)
DOWNLOAD_DIR = str(Path(__file__).parent.parent / "downloads" / "coupang")


class CoupangAdsScraper:
    """쿠팡 광고센터 보고서 다운로드 스크래퍼."""

    # 쿠팡 광고센터 URL
    ADS_LOGIN_URL = "https://advertising.coupang.com/user/login"
    ADS_DASHBOARD_URL = "https://advertising.coupang.com"
    ADS_DASHBOARD_SALES = "https://advertising.coupang.com/marketing/dashboard/sales"
    ADS_REPORT_URL = "https://advertising.coupang.com/marketing-reporting/billboard"
    ADS_CAMPAIGN_URL = "https://advertising.coupang.com/marketing/campaign/type"

    def __init__(self, wing_id: str, wing_password: str,
                 headless: bool = True, download_dir: str = None):
        self.wing_id = wing_id
        self.wing_password = wing_password
        self.headless = headless
        self.download_dir = download_dir or DOWNLOAD_DIR
        self.driver = None

        # 다운로드 폴더 생성
        os.makedirs(self.download_dir, exist_ok=True)

    def _create_driver(self) -> webdriver.Chrome:
        """Chrome 드라이버 생성 (봇 감지 최소화 설정)."""
        options = Options()

        if self.headless:
            options.add_argument("--headless=new")

        # 봇 감지 최소화
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

        # 다운로드 경로 설정
        prefs = {
            "download.default_directory": self.download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        }
        options.add_experimental_option("prefs", prefs)

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        # navigator.webdriver 숨기기
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )

        return driver

    def start(self) -> None:
        """브라우저 시작."""
        logger.info("쿠팡 스크래퍼: 브라우저 시작")
        self.driver = self._create_driver()

    def close(self) -> None:
        """브라우저 종료."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            logger.info("쿠팡 스크래퍼: 브라우저 종료")

    # ══════════════════════════════════════════════
    #  캠페인 목록 조회 / ON·OFF 토글
    # ══════════════════════════════════════════════

    ADS_CAMPAIGN_LIST_URL = "https://advertising.coupang.com/marketing/campaign"

    def get_campaign_list(self) -> list:
        """캠페인 목록 조회 (이름, ON/OFF 상태).

        광고관리 페이지 → 캠페인 React Table에서 추출.
        Returns: [{"name": str, "status": "ON"|"OFF", "index": int}, ...]
        """
        if not self.driver:
            self.start()

        try:
            # 광고관리 페이지로 이동
            self.driver.get(self.ADS_DASHBOARD_SALES)
            time.sleep(5)
            self._dismiss_popups()
            time.sleep(2)

            # 캠페인 목록 추출 (React Table)
            campaigns = self.driver.execute_script("""
                const result = [];
                // React Table 행 (rt-tr-group)
                const groups = document.querySelectorAll('.rt-tr-group');
                groups.forEach((group, idx) => {
                    const cells = group.querySelectorAll('[role="gridcell"]');
                    if (cells.length >= 3) {
                        const name = cells[0] ? cells[0].innerText.trim() : '';
                        const onoff = cells[1] ? cells[1].innerText.trim() : '';
                        const status = cells[2] ? cells[2].innerText.trim() : '';
                        if (name && name.length > 1) {
                            result.push({name: name, status: onoff || status, index: idx});
                        }
                    }
                });

                // React Table이 없으면 AG-Grid 시도
                if (result.length === 0) {
                    const pinnedRows = document.querySelectorAll(
                        '.ag-pinned-left-cols-container .ag-row'
                    );
                    pinnedRows.forEach((row, idx) => {
                        const cell = row.querySelector('[role="gridcell"]');
                        if (cell) {
                            const name = cell.innerText.trim();
                            if (name && name.length > 1) {
                                result.push({name: name, status: 'ON', index: idx});
                            }
                        }
                    });
                }
                return result;
            """)

            if campaigns:
                logger.info(f"쿠팡 캠페인 목록: {len(campaigns)}개")
                for c in campaigns:
                    logger.info(f"  - {c.get('name', '')} [{c.get('status', '')}]")
            else:
                logger.warning("캠페인 목록을 찾을 수 없음")

            return campaigns or []

        except Exception as e:
            logger.error(f"캠페인 목록 조회 실패: {e}", exc_info=True)
            return []

    def toggle_campaign(self, campaign_name: str, action: str = "pause") -> dict:
        """캠페인 ON/OFF 토글 (Selenium으로 광고관리 페이지에서 직접 클릭).

        Args:
            campaign_name: 토글할 캠페인 이름
            action: "pause" (OFF) 또는 "resume" (ON)
        Returns:
            {"success": bool, "message": str}
        """
        if not self.driver:
            return {"success": False, "message": "브라우저가 시작되지 않았습니다"}

        try:
            current_url = self.driver.current_url
            if "advertising.coupang.com" not in current_url:
                return {"success": False, "message": "쿠팡 광고센터에 로그인되지 않았습니다"}

            # 광고관리 페이지로 이동
            self.driver.get(self.ADS_DASHBOARD_SALES)
            time.sleep(5)
            self._dismiss_popups()
            time.sleep(2)

            # 캠페인 찾기 + 토글 클릭
            result = self.driver.execute_script("""
                const targetName = arguments[0];
                const action = arguments[1];  // "pause" or "resume"

                // React Table에서 캠페인 찾기
                const groups = document.querySelectorAll('.rt-tr-group');
                for (const group of groups) {
                    const cells = group.querySelectorAll('[role="gridcell"]');
                    if (cells.length < 2) continue;

                    const nameCell = cells[0];
                    const name = nameCell ? nameCell.innerText.trim() : '';

                    if (name.includes(targetName) || targetName.includes(name)) {
                        // ON/OFF 스위치/버튼 찾기
                        const switchEl = group.querySelector(
                            'button[class*="switch"], ' +
                            '[class*="Switch"], ' +
                            'input[type="checkbox"], ' +
                            '[role="switch"]'
                        );
                        if (switchEl) {
                            const currentState = switchEl.getAttribute('aria-checked') ||
                                                 switchEl.classList.contains('ant-switch-checked') ||
                                                 cells[1]?.innerText.trim();
                            const isOn = currentState === 'true' || currentState === 'ON';

                            if ((action === 'pause' && isOn) || (action === 'resume' && !isOn)) {
                                switchEl.click();
                                return {found: true, clicked: true, name: name, prevState: isOn ? 'ON' : 'OFF'};
                            } else {
                                return {found: true, clicked: false, name: name,
                                        message: '이미 ' + (isOn ? 'ON' : 'OFF') + ' 상태입니다'};
                            }
                        }

                        // 스위치가 없으면 ON/OFF 텍스트 셀 클릭 시도
                        const statusCell = cells[1];
                        if (statusCell) {
                            const btn = statusCell.querySelector('button, a, span[class*="click"]');
                            if (btn) {
                                btn.click();
                                return {found: true, clicked: true, name: name, prevState: statusCell.innerText.trim()};
                            }
                        }

                        return {found: true, clicked: false, name: name,
                                message: '토글 버튼을 찾을 수 없습니다'};
                    }
                }
                return {found: false, clicked: false, message: '캠페인을 찾을 수 없습니다: ' + targetName};
            """, campaign_name, action)

            if result and result.get("clicked"):
                time.sleep(3)
                # 확인 모달이 뜨면 확인 클릭
                try:
                    confirm_btn = self._find_element_multi([
                        (By.XPATH, "//button[contains(text(), '확인')]"),
                        (By.XPATH, "//button[contains(text(), '네')]"),
                        (By.XPATH, "//button[contains(text(), 'OK')]"),
                        (By.CSS_SELECTOR, ".ant-modal-confirm-btns .ant-btn-primary"),
                    ], timeout=3)
                    if confirm_btn:
                        confirm_btn.click()
                        time.sleep(2)
                        logger.info(f"토글 확인 모달 클릭")
                except Exception:
                    pass

                new_action = "OFF" if action == "pause" else "ON"
                logger.info(f"쿠팡 캠페인 '{campaign_name}' → {new_action}")
                self.get_dashboard_screenshot("campaign_toggled")
                return {"success": True, "message": f"캠페인 '{campaign_name}' → {new_action} 완료"}

            msg = result.get("message", "토글 실패") if result else "토글 실패"
            logger.warning(f"쿠팡 캠페인 토글 실패: {msg}")
            return {"success": False, "message": msg}

        except Exception as e:
            logger.error(f"캠페인 토글 오류: {e}", exc_info=True)
            return {"success": False, "message": str(e)}

    def login(self) -> bool:
        """쿠팡 광고센터 로그인."""
        if not self.driver:
            self.start()

        logger.info(f"쿠팡 광고센터 로그인 시도: {self.wing_id}")

        try:
            self.driver.get(self.ADS_LOGIN_URL)
            time.sleep(3)

            current_url = self.driver.current_url
            logger.info(f"로그인 페이지 URL: {current_url}")
            page_title = self.driver.title
            logger.info(f"페이지 타이틀: {page_title}")

            # ── Step 1: 로그인 유형 선택 페이지 처리 ──
            # 쿠팡 광고센터는 Wing / Supplier Hub / Ads 3가지 로그인 유형을 먼저 보여줌
            if not self._handle_login_type_selection():
                logger.warning("로그인 유형 선택 실패, 직접 ID/PW 입력 시도...")

            time.sleep(2)
            self.get_dashboard_screenshot("after_type_select")
            current_url = self.driver.current_url
            logger.info(f"유형 선택 후 URL: {current_url}")

            # ── Step 2: ID/PW 입력 ──
            id_selectors = [
                (By.ID, "username"),
                (By.ID, "email"),
                (By.ID, "loginId"),
                (By.NAME, "username"),
                (By.NAME, "email"),
                (By.NAME, "loginId"),
                (By.CSS_SELECTOR, "input[type='email']"),
                (By.CSS_SELECTOR, "input[type='text'][name]"),
                (By.CSS_SELECTOR, "input[type='text']"),
                (By.CSS_SELECTOR, "input[placeholder*='아이디']"),
                (By.CSS_SELECTOR, "input[placeholder*='이메일']"),
                (By.CSS_SELECTOR, "input[placeholder*='ID']"),
                (By.CSS_SELECTOR, "input[placeholder*='id']"),
            ]

            pw_selectors = [
                (By.ID, "password"),
                (By.NAME, "password"),
                (By.CSS_SELECTOR, "input[type='password']"),
            ]

            id_input = self._find_element_multi(id_selectors, timeout=10)
            if not id_input:
                self._save_debug_html("login_page_no_id")
                logger.error("ID 입력 필드를 찾을 수 없습니다")
                return False

            id_input.clear()
            id_input.send_keys(self.wing_id)
            logger.info("ID 입력 완료")
            time.sleep(0.5)

            pw_input = self._find_element_multi(pw_selectors, timeout=5)
            if not pw_input:
                self._save_debug_html("login_page_no_pw")
                logger.error("비밀번호 입력 필드를 찾을 수 없습니다")
                return False

            pw_input.clear()
            pw_input.send_keys(self.wing_password)
            logger.info("PW 입력 완료")
            time.sleep(0.5)

            # ── Step 3: 로그인 버튼 클릭 ──
            login_btn_selectors = [
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[contains(text(), '로그인')]"),
                (By.XPATH, "//button[contains(text(), 'Login')]"),
                (By.XPATH, "//button[contains(text(), 'Sign')]"),
                (By.XPATH, "//input[@type='submit']"),
                (By.CSS_SELECTOR, ".login-btn"),
                (By.CSS_SELECTOR, "#loginButton"),
            ]

            login_btn = self._find_element_multi(login_btn_selectors, timeout=5)
            if login_btn:
                login_btn.click()
                logger.info("로그인 버튼 클릭")
            else:
                from selenium.webdriver.common.keys import Keys
                pw_input.send_keys(Keys.RETURN)
                logger.info("Enter 키로 로그인 시도")

            time.sleep(5)
            self.get_dashboard_screenshot("after_login_click")

            # ── Step 4: 로그인 결과 확인 ──
            current_url = self.driver.current_url
            logger.info(f"로그인 후 URL: {current_url}")

            # wing.coupang.com 로그인 후 advertising.coupang.com으로 리다이렉트
            if "login" in current_url.lower() and "advertising" in current_url.lower():
                self._save_debug_html("login_failed")
                logger.error("로그인 실패: 여전히 로그인 페이지에 있습니다")
                return False

            logger.info("쿠팡 광고센터 로그인 성공!")

            # 광고주 선택 페이지 처리 (여러 광고주가 있을 수 있음)
            if "select-advertiser" in current_url or "select" in current_url.lower():
                logger.info("광고주 선택 페이지 감지, 첫 번째 광고주 선택 시도...")
                self._select_first_advertiser()

            return True

        except Exception as e:
            logger.error(f"로그인 중 오류: {e}", exc_info=True)
            self._save_debug_html("login_error")
            self.get_dashboard_screenshot("login_error")
            return False

    def _handle_login_type_selection(self) -> bool:
        """
        로그인 유형 선택 페이지 처리.
        '쿠팡 마켓플레이스 & 로켓그로스 판매자' (Wing) 로그인 선택.
        """
        try:
            # 방법 1: "쿠팡 마켓플레이스" 텍스트가 있는 카드의 "로그인하기" 버튼 클릭
            # 페이지 구조: 카드 3개, 각각 "로그인하기" 버튼 포함
            cards = self.driver.find_elements(
                By.CSS_SELECTOR, "a[href], button, div[role='button']"
            )

            # 첫 번째 "로그인하기" 버튼 찾기 (Wing 카드)
            login_buttons = self.driver.find_elements(
                By.XPATH, "//button[contains(text(), '로그인하기')] | //a[contains(text(), '로그인하기')]"
            )

            if login_buttons:
                # 첫 번째 버튼 = Wing 로그인
                logger.info(f"로그인 유형 버튼 {len(login_buttons)}개 발견, Wing(첫 번째) 선택")
                login_buttons[0].click()
                time.sleep(2)
                return True

            # 방법 2: 카드 영역 클릭 (링크로 감싸져 있을 수 있음)
            wing_selectors = [
                (By.XPATH, "//a[contains(@href, 'wing')]"),
                (By.XPATH, "//*[contains(text(), '마켓플레이스')]//ancestor::a"),
                (By.XPATH, "//*[contains(text(), '마켓플레이스')]//ancestor::div[contains(@class, 'card')]//a"),
                (By.XPATH, "//*[contains(text(), '마켓플레이스')]//ancestor::div[contains(@class, 'card')]//button"),
                (By.CSS_SELECTOR, ".login-type-card:first-child a"),
                (By.CSS_SELECTOR, ".login-type-card:first-child button"),
            ]

            elem = self._find_element_multi(wing_selectors, timeout=5)
            if elem:
                logger.info("Wing 로그인 링크/카드 클릭")
                elem.click()
                time.sleep(2)
                return True

            # 방법 3: 이미 ID/PW 입력 폼이 보이면 유형 선택 불필요
            pw_fields = self.driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
            if pw_fields:
                logger.info("로그인 유형 선택 페이지가 아닌 것 같음 (PW 필드 발견)")
                return True

            self._save_debug_html("login_type_page")
            logger.warning("로그인 유형 선택 버튼을 찾지 못했습니다")
            return False

        except Exception as e:
            logger.warning(f"로그인 유형 선택 중 오류: {e}")
            return False

    def _select_first_advertiser(self) -> None:
        """광고주 선택 페이지에서 첫 번째 광고주 선택."""
        try:
            time.sleep(2)
            # 광고주 선택 링크/버튼 클릭
            selectors = [
                (By.CSS_SELECTOR, ".advertiser-item"),
                (By.CSS_SELECTOR, ".advertiser-list a"),
                (By.CSS_SELECTOR, "a[href*='advertiser']"),
                (By.CSS_SELECTOR, "tr td a"),
                (By.CSS_SELECTOR, ".list-item"),
            ]
            item = self._find_element_multi(selectors, timeout=5)
            if item:
                item.click()
                time.sleep(3)
                logger.info("첫 번째 광고주 선택 완료")
            else:
                self._save_debug_html("advertiser_select")
                logger.warning("광고주 선택 항목을 찾지 못했습니다")
        except Exception as e:
            logger.warning(f"광고주 선택 중 오류: {e}")

    def _dismiss_popups(self) -> None:
        """로그인 후 나타나는 팝업 닫기."""
        try:
            time.sleep(1)
            # "닫기" / "X" 버튼 시도
            close_selectors = [
                (By.XPATH, "//button[contains(text(), '닫기')]"),
                (By.XPATH, "//button[contains(text(), '확인')]"),
                (By.CSS_SELECTOR, ".modal-close"),
                (By.CSS_SELECTOR, "[aria-label='Close']"),
                (By.CSS_SELECTOR, "[aria-label='close']"),
                (By.CSS_SELECTOR, "button.close"),
                (By.CSS_SELECTOR, ".popup-close"),
                (By.XPATH, "//div[contains(@class,'modal')]//button[contains(text(),'X') or contains(text(),'\u00d7')]"),
            ]
            # 빠르게 순회 (timeout 짧게)
            for by, value in close_selectors:
                try:
                    btns = self.driver.find_elements(by, value)
                    for btn in btns:
                        if btn.is_displayed():
                            btn.click()
                            logger.info(f"팝업 닫기: {value}")
                            time.sleep(0.5)
                except Exception:
                    continue

            # "한 달간 보지 않기" 체크 + 닫기
            try:
                checkbox = self.driver.find_element(
                    By.XPATH, "//*[contains(text(), '보지 않기')]//preceding-sibling::input | //*[contains(text(), '보지 않기')]//ancestor::label//input"
                )
                if checkbox and not checkbox.is_selected():
                    checkbox.click()
                    time.sleep(0.3)
            except Exception:
                pass

            # ESC 키로 모달 닫기
            from selenium.webdriver.common.keys import Keys
            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            time.sleep(0.5)

        except Exception as e:
            logger.debug(f"팝업 닫기 시도 중 무시: {e}")

    def download_dashboard_data(self, date_from: date = None,
                                 date_to: date = None) -> dict:
        """
        쿠팡 광고 데이터를 수집.
        1순위: 광고보고서 페이지에서 엑셀 다운로드
        2순위: 대시보드 API 인터셉트
        3순위: 대시보드 DOM에서 직접 스크래핑
        """
        if not date_from:
            date_from = date.today() - timedelta(days=1)
        if not date_to:
            date_to = date_from

        # 팝업 닫기
        self._dismiss_popups()
        time.sleep(1)

        result = {}

        # 방법 1 (추천): 광고보고서 페이지에서 직접 스크래핑
        try:
            logger.info(f"[방법1] 광고보고서 페이지 스크래핑: {date_from} ~ {date_to}")
            result = self._scrape_report_page(date_from, date_to)
            if result and result.get("dom_data"):
                # KPI 값이 실제로 추출되었는지 확인 (값이 합리적인지)
                dom = result["dom_data"]
                has_kpi = any(
                    int(dom.get(k, "0") or "0") > 100
                    for k in ("ad_cost", "impressions", "clicks")
                )
                has_table = bool(dom.get("_tables"))
                if has_kpi or has_table:
                    return result
                logger.warning("보고서 페이지 스크래핑 성공했으나 KPI 데이터 없음")
        except Exception as e:
            logger.warning(f"보고서 페이지 스크래핑 실패: {e}")

        # 방법 2: 대시보드 DOM에서 직접 스크래핑
        try:
            logger.info("[방법2] 대시보드 DOM 스크래핑 시도...")
            result = self._scrape_dashboard_dom(date_from, date_to)
            if result:
                return result
        except Exception as e:
            logger.warning(f"DOM 스크래핑 실패: {e}")

        # 방법 3: 내부 API 캡처 (시간이 오래 걸림)
        try:
            logger.info("[방법3] 대시보드 내부 API 캡처 시도...")
            result = self._capture_dashboard_api(date_from, date_to)
            if result and result.get("api_data"):
                return result
        except Exception as e:
            logger.warning(f"API 캡처 실패: {e}")

        return result

    def _scrape_report_page(self, date_from: date, date_to: date) -> dict:
        """
        광고보고서 페이지(/marketing-reporting/billboard)에서 KPI 직접 스크래핑.
        이 페이지는 노출수, 클릭수, 전환, ROAS, 매출 등을 차트와 함께 표시.
        """
        import json as json_module

        self.driver.get(self.ADS_REPORT_URL)
        time.sleep(8)

        current = self.driver.current_url
        logger.info(f"광고보고서 페이지 URL: {current}")

        if "login" in current.lower():
            logger.warning("세션 만료됨")
            return {}

        # 데이터 로딩 대기 (차트+테이블 렌더링)
        time.sleep(8)
        self._dismiss_popups()
        time.sleep(2)

        self.get_dashboard_screenshot("report_page")
        self._save_debug_html("report_page")

        # 캠페인별 성과 탭 클릭 (가능하면)
        try:
            campaign_tab = self._find_element_multi([
                (By.XPATH, "//div[contains(text(), '캠페인별 성과')]"),
                (By.XPATH, "//span[contains(text(), '캠페인별 성과')]"),
                (By.XPATH, "//button[contains(text(), '캠페인별')]"),
            ], timeout=3)
            if campaign_tab:
                campaign_tab.click()
                logger.info("'캠페인별 성과' 탭 클릭")
                time.sleep(3)

                # AG-Grid 데이터 행이 렌더링될 때까지 대기 (최대 15초)
                for wait_i in range(15):
                    row_count = self.driver.execute_script("""
                        return document.querySelectorAll(
                            '.ag-center-cols-container .ag-row, '
                          + '[role="row"][row-index], '
                          + '.ag-cell, '
                          + '.rt-tr-group, '
                          + '[role="gridcell"]'
                        ).length;
                    """)
                    if row_count and row_count > 0:
                        logger.info(f"테이블 데이터 행 감지: {row_count}개 (대기 {wait_i}초)")
                        break
                    time.sleep(1)
                else:
                    logger.warning("AG-Grid 데이터 행 대기 타임아웃 (15초)")

                self.get_dashboard_screenshot("report_campaign_tab")
                self._save_debug_html("report_campaign_tab")
        except Exception:
            pass

        # JavaScript로 페이지 전체 데이터 추출
        data = self.driver.execute_script("""
            const result = {};
            const body = document.body.innerText;

            // KPI 패턴 매칭 (정확한 패턴 우선)
            const patterns = [
                {key: 'impressions', patterns: [
                    /광고\\s*노출수[\\s\\n]*([\\d,]{4,})회/,
                    /광고\\s*노출수[\\s\\n]*([\\d,]{4,})/,
                    /노출수[\\s\\n]*([\\d,]{4,})회/,
                ]},
                {key: 'clicks', patterns: [
                    /광고\\s*클릭수[\\s\\n]*([\\d,]{3,})회/,
                    /광고\\s*클릭수[\\s\\n]*([\\d,]{3,})/,
                    /클릭수[\\s\\n]*([\\d,]{3,})회/,
                ]},
                {key: 'conversions', patterns: [
                    /광고\\s*전환\\s*판매수[\\s\\n]*([\\d,]+)회/,
                    /광고\\s*전환\\s*판매수[\\s\\n]*([\\d,]+)/,
                    /전환\\s*판매수[\\s\\n]*([\\d,]+)/,
                ]},
                {key: 'roas', patterns: [
                    /광고\\s*수익률[\\s\\n]*([\\d,]+\\.?\\d*)\\s*%/,
                    /ROAS[\\s\\n]*([\\d,]+\\.?\\d*)\\s*%/,
                ]},
                {key: 'total_revenue', patterns: [
                    /전체\\s*매출[\\s\\n]*([\\d,]{4,})원/,
                    /전체\\s*매출[\\s\\n]*([\\d,]{4,})/,
                ]},
                {key: 'conv_revenue', patterns: [
                    /광고\\s*전환\\s*매출[\\s\\n]*([\\d,]{4,})원/,
                    /광고\\s*전환\\s*매출[\\s\\n]*([\\d,]{4,})/,
                ]},
                {key: 'ad_cost', patterns: [
                    /집행\\s*광고비[\\s\\n]*([\\d,]{4,})원/,
                    /집행\\s*광고비[\\s\\n]*([\\d,]{4,})/,
                ]},
            ];

            for (const {key, patterns: pats} of patterns) {
                for (const p of pats) {
                    const m = body.match(p);
                    if (m) {
                        result[key] = m[1].replace(/,/g, '');
                        break;
                    }
                }
            }

            // 테이블 데이터 (캠페인별 성과)
            const tables = [];

            // 1) Ant Design Table (가장 가능성 높음)
            const antTable = document.querySelector('.ant-table-content table, .ant-table table');
            if (antTable) {
                const rows = [];
                antTable.querySelectorAll('thead tr').forEach(tr => {
                    const cells = [];
                    tr.querySelectorAll('th').forEach(th => cells.push(th.innerText.trim()));
                    if (cells.length > 2) rows.push(cells);
                });
                antTable.querySelectorAll('tbody tr').forEach(tr => {
                    const cells = [];
                    tr.querySelectorAll('td').forEach(td => cells.push(td.innerText.trim()));
                    if (cells.length > 2) rows.push(cells);
                });
                if (rows.length > 1) tables.push(rows);
            }

            // 2) 일반 HTML table (Ant Design이 아닌 경우)
            if (tables.length === 0) {
                document.querySelectorAll('table').forEach(table => {
                    const rows = [];
                    table.querySelectorAll('tr').forEach(tr => {
                        const cells = [];
                        tr.querySelectorAll('td, th').forEach(td => cells.push(td.innerText.trim()));
                        if (cells.length > 2) rows.push(cells);
                    });
                    if (rows.length > 1) tables.push(rows);
                });
            }

            // 3) AG-Grid (pinned left + center 행을 row-index 또는 ag-row로 합침)
            if (tables.length === 0) {
                // 헤더 먼저 수집
                const headers = [];
                document.querySelectorAll('[role="columnheader"], .customHeaderLabel').forEach(h => {
                    const txt = h.innerText.trim().split('\\n')[0];
                    if (txt) headers.push(txt);
                });

                // row-index 속성이 있는 행 시도
                let gridRows = document.querySelectorAll('[role="row"][row-index]');
                let useRowIndex = true;

                // 없으면 ag-row 클래스로 폴백
                if (gridRows.length === 0) {
                    gridRows = document.querySelectorAll('.ag-row[row-id]');
                    useRowIndex = false;
                }
                // 그래도 없으면 ag-row 클래스만으로
                if (gridRows.length === 0) {
                    gridRows = document.querySelectorAll('.ag-row');
                    useRowIndex = false;
                }

                if (gridRows.length > 0) {
                    const rowMap = {};
                    gridRows.forEach(row => {
                        // row-index, row-id, 또는 aria-rowindex로 행 식별
                        let idx = row.getAttribute('row-index')
                               || row.getAttribute('row-id')
                               || row.getAttribute('aria-rowindex')
                               || row.getAttribute('comp-id');
                        if (!idx) return;
                        if (!rowMap[idx]) rowMap[idx] = [];
                        // gridcell 또는 ag-cell 선택
                        const cells = row.querySelectorAll('[role="gridcell"], .ag-cell');
                        cells.forEach(c => {
                            rowMap[idx].push(c.innerText.trim());
                        });
                    });

                    const gridData = headers.length > 0 ? [headers] : [];
                    const sortedIdxs = Object.keys(rowMap).sort((a,b) => {
                        const na = parseInt(a), nb = parseInt(b);
                        if (!isNaN(na) && !isNaN(nb)) return na - nb;
                        return a.localeCompare(b);
                    });
                    sortedIdxs.forEach(idx => {
                        const cells = rowMap[idx];
                        if (cells.length > 0) gridData.push(cells);
                    });
                    if (gridData.length > 1) tables.push(gridData);
                }
            }

            // 4) React Table (rt-td, rt-tr, role="gridcell")
            if (tables.length === 0) {
                const rtHeaders = [];
                document.querySelectorAll('.rt-resizable-header-content').forEach(h => {
                    const txt = h.innerText.trim();
                    if (txt) rtHeaders.push(txt);
                });

                if (rtHeaders.length > 3) {
                    const rtData = [rtHeaders];
                    const rtGroups = document.querySelectorAll('.rt-tr-group');
                    rtGroups.forEach(group => {
                        const cells = [];
                        group.querySelectorAll('[role="gridcell"]').forEach(td => {
                            let text = td.innerText.trim().replace(/\\n/g, ' ');
                            cells.push(text);
                        });
                        if (cells.length > 3) rtData.push(cells);
                    });
                    if (rtData.length > 1) tables.push(rtData);
                }
            }

            result['_tables'] = tables;
            result['_cards'] = [];

            // 캠페인명 추출: AG-Grid pinned left의 gridcell에서
            const campNames = [];
            try {
                // AG-Grid pinned left 컨테이너에서 캠페인명 추출
                const pinnedLeft = document.querySelector('.ag-pinned-left-cols-container');
                if (pinnedLeft) {
                    // row-index 우선, 없으면 ag-row 폴백
                    let nameRows = pinnedLeft.querySelectorAll('[role="row"][row-index]');
                    if (nameRows.length === 0) {
                        nameRows = pinnedLeft.querySelectorAll('.ag-row[row-id]');
                    }
                    if (nameRows.length === 0) {
                        nameRows = pinnedLeft.querySelectorAll('.ag-row');
                    }
                    const sorted = Array.from(nameRows).sort((a,b) => {
                        const ai = parseInt(a.getAttribute('row-index') || a.getAttribute('row-id') || a.getAttribute('aria-rowindex') || '0');
                        const bi = parseInt(b.getAttribute('row-index') || b.getAttribute('row-id') || b.getAttribute('aria-rowindex') || '0');
                        return ai - bi;
                    });
                    sorted.forEach(row => {
                        const cell = row.querySelector('[role="gridcell"], .ag-cell');
                        if (cell) {
                            const t = cell.innerText.trim();
                            if (t && t.length > 1) campNames.push(t);
                        }
                    });
                }

                // 대안: .campaign-name 클래스
                if (campNames.length === 0) {
                    document.querySelectorAll('.campaign-name').forEach(el => {
                        let t = el.innerText.split('\\n')[0].trim();
                        if (t && t.length > 1) campNames.push(t);
                    });
                }
            } catch(e) {}

            result['_campaign_names'] = campNames;

            return result;
        """)

        if data:
            logger.info(f"보고서 페이지 KPI: {dict((k,v) for k,v in data.items() if not k.startswith('_'))}")
            if data.get("_tables"):
                for i, t in enumerate(data["_tables"]):
                    logger.info(f"  테이블[{i}]: {len(t)}행")

            # 페이지네이션: 다음 페이지가 있으면 추가 캠페인 수집
            try:
                next_btn = self._find_element_multi([
                    (By.CSS_SELECTOR, ".pagination-control.right:not(.disabled)"),
                    (By.CSS_SELECTOR, ".ag-paging-button[ref='btNext']:not([disabled])"),
                    (By.XPATH, "//div[contains(@class,'pagination-control') and contains(@class,'right') and not(contains(@class,'disabled'))]"),
                ], timeout=2)
                if next_btn:
                    next_btn.click()
                    logger.info("페이지 2로 이동")
                    time.sleep(3)

                    page2 = self.driver.execute_script("""
                        const names = [];
                        const rows = [];
                        const pinnedLeft = document.querySelector('.ag-pinned-left-cols-container');
                        if (pinnedLeft) {
                            let pRows = pinnedLeft.querySelectorAll('[role="row"][row-index]');
                            if (pRows.length === 0) pRows = pinnedLeft.querySelectorAll('.ag-row[row-id]');
                            if (pRows.length === 0) pRows = pinnedLeft.querySelectorAll('.ag-row');
                            Array.from(pRows).sort((a,b) => {
                                const ai = parseInt(a.getAttribute('row-index') || a.getAttribute('row-id') || '0');
                                const bi = parseInt(b.getAttribute('row-index') || b.getAttribute('row-id') || '0');
                                return ai - bi;
                            }).forEach(row => {
                                const cell = row.querySelector('[role="gridcell"], .ag-cell');
                                if (cell) names.push(cell.innerText.trim());
                            });
                        }
                        // 행 데이터 수집 (row-index 우선, ag-row 폴백)
                        let gridRows = document.querySelectorAll('[role="row"][row-index]');
                        if (gridRows.length === 0) gridRows = document.querySelectorAll('.ag-row[row-id]');
                        if (gridRows.length === 0) gridRows = document.querySelectorAll('.ag-row');
                        const rowMap = {};
                        gridRows.forEach(row => {
                            const idx = row.getAttribute('row-index')
                                     || row.getAttribute('row-id')
                                     || row.getAttribute('aria-rowindex')
                                     || row.getAttribute('comp-id');
                            if (!idx) return;
                            if (!rowMap[idx]) rowMap[idx] = [];
                            row.querySelectorAll('[role="gridcell"], .ag-cell').forEach(c => {
                                rowMap[idx].push(c.innerText.trim());
                            });
                        });
                        Object.keys(rowMap).sort((a,b) => {
                            const na = parseInt(a), nb = parseInt(b);
                            if (!isNaN(na) && !isNaN(nb)) return na - nb;
                            return a.localeCompare(b);
                        }).forEach(idx => {
                            if (rowMap[idx].length > 0) rows.push(rowMap[idx]);
                        });
                        return {names, rows};
                    """)

                    if page2 and page2.get("rows"):
                        # 기존 테이블의 마지막 행("전체") 보존
                        existing_table = data.get("_tables", [[]])[0]
                        # "전체" 총계행 찾아서 임시 보관 후 제거
                        total_row_backup = None
                        if existing_table and str(existing_table[-1][0] if existing_table[-1] else "") == "전체":
                            total_row_backup = existing_table.pop()

                        # 페이지 2 행 추가 (전체/합계 행 제외, 개별 캠페인만)
                        added = 0
                        for row in page2["rows"]:
                            first_val = str(row[0]).strip() if row else ""
                            if first_val and first_val != "전체" and "평균" not in first_val:
                                existing_table.append(row)
                                added += 1

                        # "전체" 총계행 다시 맨 뒤에 추가
                        if total_row_backup:
                            existing_table.append(total_row_backup)

                        # 캠페인명 추가
                        p2_names = page2.get("names", [])
                        data["_campaign_names"].extend(
                            n for n in p2_names if n and n != "전체"
                        )
                        logger.info(f"페이지 2: 캠페인 {added}행, 이름 {len(p2_names)}개 추가")
            except Exception as e:
                logger.debug(f"페이지네이션 처리: {e}")

            # JSON 파일로 저장
            debug_dir = Path(self.download_dir) / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            dom_file = str(debug_dir / "dom_scraped.json")
            with open(dom_file, "w", encoding="utf-8") as f:
                json_module.dump(data, f, ensure_ascii=False, indent=2, default=str)

            return {"dom_data": data}

        return {}

    def _capture_dashboard_api(self, date_from: date, date_to: date) -> dict:
        """
        Performance Log를 이용해 대시보드 내부 API 호출을 캡처.
        페이지 로드 시 쿠팡 프론트엔드가 호출하는 API 응답을 수집.
        """
        import json as json_module
        result = {}

        # fetch/XHR 인터셉터 설치
        self.driver.execute_script("""
            window.__coupang_api = [];
            const _fetch = window.fetch;
            window.fetch = function(...args) {
                return _fetch.apply(this, args).then(resp => {
                    const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
                    if (url.includes('/api/') || url.includes('/report') ||
                        url.includes('/stat') || url.includes('/campaign') ||
                        url.includes('/dashboard') || url.includes('/performance') ||
                        url.includes('/keyword') || url.includes('/product')) {
                        resp.clone().text().then(txt => {
                            try { window.__coupang_api.push({url, data: JSON.parse(txt)}); }
                            catch(e) { window.__coupang_api.push({url, raw: txt.substring(0, 2000)}); }
                        }).catch(() => {});
                    }
                    return resp;
                });
            };
        """)

        # 대시보드 새로고침 (API 호출 트리거)
        date_from_str = date_from.strftime("%Y%m%d")
        date_to_str = date_to.strftime("%Y%m%d")
        dashboard_url = (
            f"{self.ADS_DASHBOARD_URL}/marketing/dashboard/sales"
            f"?startDate={date_from_str}&endDate={date_to_str}"
        )
        self.driver.get(dashboard_url)
        time.sleep(6)
        self._dismiss_popups()
        time.sleep(2)

        # 캡처된 API 응답 수집
        captured = self.driver.execute_script("return window.__coupang_api || [];")
        if captured:
            logger.info(f"캡처된 API 응답 {len(captured)}개:")
            for item in captured:
                url = item.get("url", "unknown")
                logger.info(f"  - {url}")
            result["api_data"] = captured

            # API 데이터를 JSON 파일로 저장
            debug_dir = Path(self.download_dir) / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            api_file = str(debug_dir / "api_captured.json")
            with open(api_file, "w", encoding="utf-8") as f:
                json_module.dump(captured, f, ensure_ascii=False, indent=2, default=str)
            logger.info(f"API 데이터 저장: {api_file}")

        self.get_dashboard_screenshot("dashboard_api_capture")
        return result

    def _scrape_dashboard_dom(self, date_from: date, date_to: date) -> dict:
        """
        대시보드 DOM에서 KPI 데이터를 스크래핑.
        1. 대시보드 로드 → "광고 성과 자세히 보기" 클릭하여 KPI 펼치기
        2. KPI 숫자 추출
        3. 캠페인 관리 페이지에서 캠페인 테이블 수집
        """
        import json as json_module

        # ── Step 1: 대시보드 기본 화면 (날짜 파라미터 없이) ──
        self.driver.get(self.ADS_DASHBOARD_SALES)
        time.sleep(5)
        self._dismiss_popups()
        time.sleep(2)

        # 대시보드 데이터 로딩 대기
        time.sleep(3)

        self.get_dashboard_screenshot("dashboard_scrape")
        self._save_debug_html("dashboard_scrape")

        # ── Step 2: 대시보드 전체 텍스트에서 KPI 추출 ──
        data = self.driver.execute_script("""
            const result = {};
            const body = document.body.innerText;

            // 다양한 패턴으로 KPI 값 추출
            const patterns = [
                {key: 'ad_cost', patterns: [
                    /집행\\s*광고비[\\s\\n]*([\\d,]+)/,
                    /광고비[\\s\\n]*([\\d,]+)\\s*원/,
                ]},
                {key: 'conv_revenue', patterns: [
                    /광고\\s*전환\\s*매출[\\s\\n]*([\\d,]+)/,
                    /전환매출[\\s\\n]*([\\d,]+)/,
                    /광고\\s*전환\\s*판매수[\\s\\S]{0,50}?([\\d,]+)원/,
                ]},
                {key: 'total_revenue', patterns: [
                    /전체\\s*매출[\\s\\n]*([\\d,]+)/,
                    /판매매출[\\s\\n]*([\\d,]+)/,
                ]},
                {key: 'conversions', patterns: [
                    /광고\\s*전환\\s*판매수[\\s\\n]*([\\d,]+)/,
                    /전환수[\\s\\n]*([\\d,]+)/,
                    /전환건수[\\s\\n]*([\\d,]+)/,
                ]},
                {key: 'orders', patterns: [
                    /광고\\s*전환\\s*주문수[\\s\\n]*([\\d,]+)/,
                ]},
                {key: 'impressions', patterns: [
                    /노출수[\\s\\n]*([\\d,]+)/,
                    /노출[\\s\\n]*([\\d,]+)\\s*회/,
                ]},
                {key: 'clicks', patterns: [
                    /클릭수[\\s\\n]*([\\d,]+)/,
                    /클릭[\\s\\n]*([\\d,]+)\\s*회/,
                ]},
                {key: 'ctr', patterns: [
                    /클릭률[\\s\\n]*([\\d.]+)/,
                    /CTR[\\s\\n]*([\\d.]+)/,
                ]},
                {key: 'conv_rate', patterns: [
                    /전환율[\\s\\n]*([\\d.]+)/,
                ]},
                {key: 'roas', patterns: [
                    /광고\\s*수익률[\\s\\n]*([\\d,]+\\.?\\d*)\\s*%/,
                    /ROAS[\\s\\n]*([\\d,]+\\.?\\d*)\\s*%/,
                ]},
                {key: 'cpc', patterns: [
                    /CPC[\\s\\n]*([\\d,]+)/,
                    /평균\\s*CPC[\\s\\n]*([\\d,]+)/,
                ]},
            ];

            for (const {key, patterns: pats} of patterns) {
                for (const p of pats) {
                    const m = body.match(p);
                    if (m) {
                        result[key] = m[1].replace(/,/g, '');
                        break;
                    }
                }
            }

            // 숫자가 표시되는 모든 카드/지표 영역 텍스트 수집
            const metricElements = document.querySelectorAll(
                '[class*="card"], [class*="kpi"], [class*="metric"], ' +
                '[class*="stat"], [class*="summary"], [class*="total"], ' +
                '[class*="value"], [class*="number"]'
            );
            const cardData = [];
            metricElements.forEach(el => {
                const text = el.innerText.trim();
                if (text && text.length < 500) cardData.push(text);
            });
            result['_cards'] = cardData;

            // AG-Grid / Ant Design 테이블 데이터 수집
            const tables = document.querySelectorAll('table');
            const tableData = [];
            tables.forEach(table => {
                const rows = [];
                table.querySelectorAll('tr').forEach(tr => {
                    const cells = [];
                    tr.querySelectorAll('td, th').forEach(td => cells.push(td.innerText.trim()));
                    if (cells.length > 0) rows.push(cells);
                });
                if (rows.length > 0) tableData.push(rows);
            });

            // ag-grid 행이 있으면 그것도 수집
            const agRows = document.querySelectorAll('.ag-row, [role="row"]');
            if (agRows.length > 2) {
                const agData = [];
                agRows.forEach(row => {
                    const cells = [];
                    row.querySelectorAll('.ag-cell, [role="gridcell"], td').forEach(cell => {
                        cells.push(cell.innerText.trim());
                    });
                    if (cells.length > 2) agData.push(cells);
                });
                if (agData.length > 0) tableData.push(agData);
            }

            // Ant Design table body rows
            const antRows = document.querySelectorAll('.ant-table-tbody tr, .ant-table-row');
            if (antRows.length > 0) {
                const antHeaders = [];
                document.querySelectorAll('.ant-table-thead th, .customHeaderLabel').forEach(th => {
                    antHeaders.push(th.innerText.trim());
                });
                const antData = [antHeaders];
                antRows.forEach(row => {
                    const cells = [];
                    row.querySelectorAll('td').forEach(td => cells.push(td.innerText.trim()));
                    if (cells.length > 0) antData.push(cells);
                });
                if (antData.length > 1) tableData.push(antData);
            }

            result['_tables'] = tableData;

            return result;
        """)

        logger.info(f"대시보드 KPI 추출: {dict((k,v) for k,v in (data or {}).items() if not k.startswith('_'))}")

        # ── Step 3: 대시보드 페이지 아래쪽 스크롤하여 캠페인 테이블 수집 ──
        campaign_tables = []
        try:
            # 페이지 끝까지 스크롤 (lazy-loading 테이블 트리거)
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

            self.get_dashboard_screenshot("dashboard_scrolled")

            campaign_tables = self.driver.execute_script("""
                const result = [];

                // 1) 일반 table
                document.querySelectorAll('table').forEach(table => {
                    const rows = [];
                    table.querySelectorAll('tr').forEach(tr => {
                        const cells = [];
                        tr.querySelectorAll('td, th').forEach(td => cells.push(td.innerText.trim()));
                        if (cells.length > 2) rows.push(cells);
                    });
                    if (rows.length > 1) result.push(rows);
                });

                // 2) ag-grid 테이블
                const agRows = document.querySelectorAll('.ag-row, [role="row"]');
                if (agRows.length > 1) {
                    const headers = [];
                    document.querySelectorAll('.ag-header-cell, .customHeaderLabel').forEach(h => {
                        const txt = h.innerText.trim().split('\\n')[0];
                        if (txt) headers.push(txt);
                    });
                    const agData = headers.length > 0 ? [headers] : [];
                    agRows.forEach(row => {
                        const cells = [];
                        row.querySelectorAll('.ag-cell, [role="gridcell"]').forEach(c => {
                            cells.push(c.innerText.trim());
                        });
                        if (cells.length > 2) agData.push(cells);
                    });
                    if (agData.length > 1) result.push(agData);
                }

                // 3) Ant Design 테이블
                const antTbody = document.querySelector('.ant-table-tbody');
                if (antTbody) {
                    const headers = [];
                    document.querySelectorAll('.ant-table-thead th').forEach(th => {
                        headers.push(th.innerText.trim().split('\\n')[0]);
                    });
                    const antData = headers.length > 0 ? [headers] : [];
                    antTbody.querySelectorAll('tr').forEach(row => {
                        const cells = [];
                        row.querySelectorAll('td').forEach(td => cells.push(td.innerText.trim()));
                        if (cells.length > 2) antData.push(cells);
                    });
                    if (antData.length > 1) result.push(antData);
                }

                return result;
            """) or []

            logger.info(f"대시보드 테이블 {len(campaign_tables)}개 수집")
            for i, table in enumerate(campaign_tables):
                if table:
                    logger.info(f"  테이블[{i}] 헤더: {table[0][:5] if table[0] else '없음'}... ({len(table)-1}행)")
        except Exception as e:
            logger.warning(f"캠페인 테이블 스크래핑 실패: {e}")

        if data:
            if campaign_tables:
                data['_tables'] = campaign_tables

            # JSON 파일로 저장
            debug_dir = Path(self.download_dir) / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            dom_file = str(debug_dir / "dom_scraped.json")
            with open(dom_file, "w", encoding="utf-8") as f:
                json_module.dump(data, f, ensure_ascii=False, indent=2, default=str)
            logger.info(f"DOM 데이터 저장: {dom_file}")

            return {"dom_data": data}

        return {}

    def _find_element_multi(self, selectors: list, timeout: int = 5):
        """여러 셀렉터를 순차적으로 시도하여 요소 찾기."""
        for by, value in selectors:
            try:
                element = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((by, value))
                )
                if element:
                    return element
            except Exception:
                continue
        return None

    def _wait_for_download(self, timeout: int = 30) -> str:
        """다운로드 완료 대기 후 파일 경로 반환."""
        end_time = time.time() + timeout
        while time.time() < end_time:
            # .crdownload (Chrome 다운로드 중) 파일이 없어질 때까지 대기
            files = glob.glob(os.path.join(self.download_dir, "*.crdownload"))
            if not files:
                # 최근 다운로드된 엑셀 파일 찾기
                xlsx_files = glob.glob(os.path.join(self.download_dir, "*.xlsx"))
                xls_files = glob.glob(os.path.join(self.download_dir, "*.xls"))
                csv_files = glob.glob(os.path.join(self.download_dir, "*.csv"))
                all_files = xlsx_files + xls_files + csv_files

                if all_files:
                    newest = max(all_files, key=os.path.getmtime)
                    if os.path.getmtime(newest) > time.time() - timeout:
                        return newest
            time.sleep(1)
        return ""

    def _save_debug_html(self, name: str) -> None:
        """디버그용 HTML 저장."""
        debug_dir = Path(self.download_dir) / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        filepath = debug_dir / f"{name}.html"
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            logger.info(f"디버그 HTML 저장: {filepath}")
        except Exception as e:
            logger.warning(f"디버그 HTML 저장 실패: {e}")

    def get_dashboard_screenshot(self, name: str = "dashboard") -> str:
        """스크린샷 저장 (디버그용)."""
        debug_dir = Path(self.download_dir) / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(debug_dir / f"{name}.png")
        try:
            self.driver.save_screenshot(filepath)
            logger.info(f"스크린샷 저장: {filepath}")
            return filepath
        except Exception as e:
            logger.warning(f"스크린샷 저장 실패: {e}")
            return ""
