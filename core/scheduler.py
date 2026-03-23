import logging
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from core.api_client import NaverAdsAPIClient
from core.config_manager import AppConfig
from core.email_sender import NaverEmailSender
from core.report_generator import ReportGenerator

logger = logging.getLogger(__name__)


class JobScheduler:
    def __init__(self, config: AppConfig):
        self.config = config
        self.scheduler = BackgroundScheduler(timezone="Asia/Seoul")
        self._alerted_today = set()

    def setup_jobs(self) -> None:
        hour, minute = map(int, self.config.schedule.report_time.split(":"))

        self.scheduler.add_job(
            func=self._run_daily_reports,
            trigger=CronTrigger(hour=hour, minute=minute),
            id="daily_report",
            name="일일 광고 보고서",
        )
        logger.info(f"일일 보고서 스케줄 등록: 매일 {self.config.schedule.report_time}")

        if self.config.alert.enabled:
            self.scheduler.add_job(
                func=self._run_budget_alerts,
                trigger=IntervalTrigger(minutes=30),
                id="budget_alert",
                name="예산 알림 체크 (30분마다)",
            )
            logger.info("예산 알림 등록: 30분마다 체크")

            # 매일 자정에 알림 기록 초기화
            self.scheduler.add_job(
                func=self._reset_alert_history,
                trigger=CronTrigger(hour=0, minute=0),
                id="reset_alerts",
                name="알림 기록 초기화",
            )

    def start(self) -> None:
        self.setup_jobs()
        self.scheduler.start()
        logger.info("스케줄러 시작 (백그라운드)")

    def run_reports_now(self) -> None:
        logger.info("보고서 즉시 실행")
        self._run_daily_reports()

    def run_alerts_now(self) -> None:
        logger.info("예산 알림 즉시 실행")
        self._run_budget_alerts()

    def get_current_costs(self) -> list[dict]:
        """모든 계정의 현재 광고비 + 비즈머니 잔액 조회 (화면 표시용)"""
        results = []
        today = date.today()

        for account in self.config.accounts:
            try:
                client = NaverAdsAPIClient(
                    account.customer_id, account.api_key, account.secret_key
                )
                generator = ReportGenerator(client)
                daily_cost = generator.get_daily_cost(today)
                threshold = self.config.alert.daily_spend_threshold

                # 비즈머니 잔액 조회
                bizmoney = None
                try:
                    biz_data = client.get_bizmoney_balance()
                    if isinstance(biz_data, dict):
                        bizmoney = biz_data.get("bizmoney", biz_data.get("balance"))
                    elif isinstance(biz_data, (int, float)):
                        bizmoney = biz_data
                    logger.info(f"[{account.name}] 비즈머니 응답: {biz_data}")
                except Exception as e:
                    logger.warning(f"[{account.name}] 비즈머니 조회 실패: {e}")

                results.append({
                    "name": account.name,
                    "customer_id": account.customer_id,
                    "daily_cost": daily_cost,
                    "threshold": threshold,
                    "bizmoney": bizmoney,
                    "status": "warning" if daily_cost < threshold else "ok",
                    "error": None,
                })
            except Exception as e:
                results.append({
                    "name": account.name,
                    "customer_id": account.customer_id,
                    "daily_cost": 0,
                    "threshold": self.config.alert.daily_spend_threshold,
                    "bizmoney": None,
                    "status": "error",
                    "error": str(e),
                })

        return results

    def send_report_for_account(self, account_index: int,
                                date_from: date = None, date_to: date = None,
                                sort_options: dict = None) -> dict:
        """특정 계정 보고서를 즉시 생성하여 발송 (기간 선택 가능)"""
        if account_index >= len(self.config.accounts):
            return {"success": False, "message": "잘못된 계정 인덱스"}

        account = self.config.accounts[account_index]
        email_sender = NaverEmailSender(
            self.config.email.sender_email, self.config.email.app_password,
            server_url=self.config.server_url,
        )

        if date_from is None:
            date_from = date.today() - timedelta(days=1)
        if date_to is None:
            date_to = date_from

        try:
            client = NaverAdsAPIClient(
                account.customer_id, account.api_key, account.secret_key
            )
            generator = ReportGenerator(client)
            report = generator.generate_report(date_from, date_to)
            report.account_name = account.name

            if sort_options:
                ReportGenerator.sort_report(
                    report,
                    adgroup_sort_by=sort_options.get("adgroup_sort_by", "cost"),
                    adgroup_sort_order=sort_options.get("adgroup_sort_order", "desc"),
                    keyword_sort_by=sort_options.get("keyword_sort_by", "cost"),
                    keyword_sort_order=sort_options.get("keyword_sort_order", "desc"),
                )

            for recipient in account.report_recipients:
                email_sender.send_report(recipient, report, sort_options)

            period = date_from.strftime("%m/%d")
            if date_from != date_to:
                period += f" ~ {date_to.strftime('%m/%d')}"
            return {"success": True, "message": f"[{account.name}] {period} 보고서 발송 완료"}
        except Exception as e:
            logger.error(f"[{account.name}] 보고서 발송 실패: {e}", exc_info=True)
            return {"success": False, "message": f"[{account.name}] 발송 실패: {e}"}

    def _reset_alert_history(self) -> None:
        self._alerted_today.clear()
        logger.info("예산 알림 기록 초기화")

    def _run_daily_reports(self) -> None:
        email_sender = NaverEmailSender(
            self.config.email.sender_email, self.config.email.app_password,
            server_url=self.config.server_url,
        )
        yesterday = date.today() - timedelta(days=1)

        for account in self.config.accounts:
            try:
                client = NaverAdsAPIClient(
                    account.customer_id, account.api_key, account.secret_key
                )
                generator = ReportGenerator(client)
                report = generator.generate_daily_report(yesterday)
                report.account_name = account.name

                for recipient in account.report_recipients:
                    email_sender.send_report(recipient, report)

                logger.info(f"[{account.name}] 보고서 발송 완료")
            except Exception as e:
                logger.error(f"[{account.name}] 보고서 발송 실패: {e}", exc_info=True)

    def _run_budget_alerts(self) -> None:
        email_sender = NaverEmailSender(
            self.config.email.sender_email, self.config.email.app_password,
            server_url=self.config.server_url,
        )
        threshold = self.config.alert.daily_spend_threshold
        today = date.today()

        for account in self.config.accounts:
            alert_key = f"{account.customer_id}_{today}"

            # 오늘 이미 알림 보낸 계정은 스킵
            if alert_key in self._alerted_today:
                continue

            try:
                client = NaverAdsAPIClient(
                    account.customer_id, account.api_key, account.secret_key
                )
                generator = ReportGenerator(client)
                daily_cost = generator.get_daily_cost(today)

                if daily_cost < threshold:
                    logger.warning(
                        f"[{account.name}] 광고비 알림: {daily_cost:,.0f}원 < {threshold:,.0f}원"
                    )
                    for recipient in account.report_recipients:
                        email_sender.send_budget_alert(
                            recipient, account.name, daily_cost, threshold
                        )
                    self._alerted_today.add(alert_key)
                else:
                    logger.info(f"[{account.name}] 광고비 정상: {daily_cost:,.0f}원")

            except Exception as e:
                logger.error(f"[{account.name}] 예산 알림 실패: {e}", exc_info=True)

    # ── GFA 광고 보고서 ──

    def send_gfa_report(self, date_from: date = None,
                         date_to: date = None,
                         account_index: int = 0) -> dict:
        """네이버 GFA 보고서 생성 및 발송 (Selenium 스크래핑)."""
        if not self.config.gfa_accounts:
            return {"success": False, "message": "GFA 설정이 없습니다"}
        if account_index < 0 or account_index >= len(self.config.gfa_accounts):
            return {"success": False, "message": f"잘못된 GFA 계정 인덱스: {account_index}"}

        gfa = self.config.gfa_accounts[account_index]

        if date_from is None:
            date_from = date.today() - timedelta(days=1)
        if date_to is None:
            date_to = date_from

        try:
            from core.gfa_scraper import GfaAdsScraper
            from core.gfa_report import (
                parse_gfa_dom_data, parse_gfa_api_data, GfaReport,
            )

            email_sender = NaverEmailSender(
                self.config.email.sender_email, self.config.email.app_password,
                server_url=self.config.server_url,
            )

            logger.info(f"GFA 보고서 생성 시작: {date_from} ~ {date_to}")

            scraper = GfaAdsScraper(
                naver_id=gfa.naver_id,
                naver_password=gfa.naver_password,
                ad_account_id=gfa.ad_account_id,
                headless=gfa.headless,
            )

            try:
                scraper.start()
                login_ok = scraper.login()
                if not login_ok:
                    return {
                        "success": False,
                        "message": "GFA 로그인 실패. 2단계 인증이 활성화된 경우 핸드폰에서 승인이 필요합니다. downloads/gfa/debug 폴더의 스크린샷을 확인하세요."
                    }

                scraper.get_screenshot("after_login")

                result = scraper.download_dashboard_data(date_from, date_to)

                if not result:
                    return {
                        "success": False,
                        "message": "GFA 보고서 다운로드 실패. downloads/gfa/debug 폴더를 확인하세요."
                    }

                report = None
                data_source = "unknown"

                if "api_data" in result:
                    report = parse_gfa_api_data(result["api_data"], date_from, date_to)
                    data_source = "내부 API"
                elif "dom_data" in result:
                    report = parse_gfa_dom_data(result["dom_data"], date_from, date_to)
                    data_source = "대시보드 스크래핑"
                else:
                    return {"success": False, "message": "수집된 데이터가 없습니다"}

                report.account_name = gfa.name

                # 실제 조회 기간 반영 (GFA URL에서 감지된 기간 우선)
                actual_range = result.get("actual_date_range")
                if actual_range:
                    from datetime import datetime as dt
                    try:
                        report.date_from = dt.strptime(actual_range[0], "%Y-%m-%d").date()
                        report.date_to = dt.strptime(actual_range[1], "%Y-%m-%d").date()
                        logger.info(f"GFA 실제 조회 기간 반영: {report.date_from} ~ {report.date_to}")
                    except Exception:
                        report.date_from = date_from
                        report.date_to = date_to
                else:
                    report.date_from = date_from
                    report.date_to = date_to

                logger.info(f"GFA 데이터 수집 완료 (소스: {data_source})")

                period = report.date_from.strftime("%m/%d")
                if report.date_from != report.date_to:
                    period += f" ~ {report.date_to.strftime('%m/%d')}"

                # 이메일 발송 (실패해도 데이터 수집 성공으로 처리)
                try:
                    for recipient in gfa.report_recipients:
                        email_sender.send_gfa_report(recipient, report)
                    return {
                        "success": True,
                        "message": f"[GFA] {period} 보고서 발송 완료 ({data_source})"
                    }
                except Exception as email_err:
                    logger.error(f"GFA 이메일 발송 실패: {email_err}")
                    return {
                        "success": False,
                        "message": f"[GFA] {period} 데이터 수집 성공, 이메일 발송 실패: {email_err}"
                    }

            finally:
                scraper.close()

        except ImportError as e:
            logger.error(f"GFA 모듈 import 실패: {e}")
            return {"success": False, "message": f"GFA 모듈 오류: {e}"}
        except Exception as e:
            logger.error(f"GFA 보고서 실패: {e}", exc_info=True)
            return {"success": False, "message": f"GFA 보고서 실패: {e}"}

    # ── 쿠팡 광고 보고서 ──

    def send_coupang_report(self, date_from: date = None,
                             date_to: date = None,
                             account_index: int = 0) -> dict:
        """쿠팡 광고 보고서 생성 및 발송."""
        if not self.config.coupang_accounts:
            return {"success": False, "message": "쿠팡 설정이 없습니다"}
        if account_index < 0 or account_index >= len(self.config.coupang_accounts):
            return {"success": False, "message": f"잘못된 쿠팡 계정 인덱스: {account_index}"}

        coupang = self.config.coupang_accounts[account_index]

        if date_from is None:
            date_from = date.today() - timedelta(days=1)
        if date_to is None:
            date_to = date_from

        try:
            from core.coupang_scraper import CoupangAdsScraper
            from core.coupang_report import (
                parse_coupang_excel, parse_dom_data, parse_api_data, CoupangReport,
            )

            email_sender = NaverEmailSender(
                self.config.email.sender_email, self.config.email.app_password,
                server_url=self.config.server_url,
            )

            logger.info(f"쿠팡 보고서 생성 시작: {date_from} ~ {date_to}")

            scraper = CoupangAdsScraper(
                wing_id=coupang.wing_id,
                wing_password=coupang.wing_password,
                headless=coupang.headless,
            )

            try:
                scraper.start()
                login_ok = scraper.login()
                if not login_ok:
                    return {"success": False, "message": "쿠팡 로그인 실패"}

                scraper.get_dashboard_screenshot("after_login")

                # 보고서 다운로드 (여러 방법 자동 시도)
                result = scraper.download_dashboard_data(date_from, date_to)

                if not result:
                    return {
                        "success": False,
                        "message": "쿠팡 보고서 다운로드 실패. downloads/coupang/debug 폴더를 확인하세요."
                    }

                # 결과 유형에 따라 파싱
                report = None
                data_source = "unknown"

                if "report_file" in result:
                    report = parse_coupang_excel(result["report_file"])
                    data_source = "엑셀 파일"
                elif "api_data" in result:
                    report = parse_api_data(result["api_data"], date_from, date_to)
                    data_source = "내부 API"
                elif "dom_data" in result:
                    report = parse_dom_data(result["dom_data"], date_from, date_to)
                    data_source = "대시보드 스크래핑"
                else:
                    return {"success": False, "message": "다운로드된 데이터가 없습니다"}

                report.account_name = coupang.name
                report.date_from = date_from
                report.date_to = date_to

                logger.info(f"쿠팡 데이터 수집 완료 (소스: {data_source})")

                # 이메일 발송
                for recipient in coupang.report_recipients:
                    email_sender.send_coupang_report(recipient, report, account_index=account_index)

                period = date_from.strftime("%m/%d")
                if date_from != date_to:
                    period += f" ~ {date_to.strftime('%m/%d')}"
                return {
                    "success": True,
                    "message": f"[쿠팡] {period} 보고서 발송 완료 ({data_source})"
                }

            finally:
                scraper.close()

        except ImportError as e:
            logger.error(f"쿠팡 모듈 import 실패: {e}")
            return {"success": False, "message": f"쿠팡 모듈 오류: {e}"}
        except Exception as e:
            logger.error(f"쿠팡 보고서 실패: {e}", exc_info=True)
            return {"success": False, "message": f"쿠팡 보고서 실패: {e}"}
