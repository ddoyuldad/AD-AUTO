import logging
import socket
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from core.report_generator import AccountReport

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def _detect_local_ip() -> str:
    """로컬 네트워크 IP 자동 감지 (같은 네트워크에서 접근 가능한 IP)"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


class NaverEmailSender:
    SMTP_SERVER = "smtp.naver.com"
    SMTP_PORT = 587

    def __init__(self, sender_email: str, app_password: str,
                 server_url: str = ""):
        self.sender_email = sender_email
        self.app_password = app_password
        self.server_url = server_url
        self.template_env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=True,
        )

    def _get_server_url(self) -> str:
        """서버 URL 반환 (설정 > 자동감지 순)"""
        if self.server_url:
            return self.server_url.rstrip("/")
        local_ip = _detect_local_ip()
        return f"http://{local_ip}:5000"

    def send_report(self, recipient: str, report: AccountReport,
                    sort_options: dict = None) -> None:
        template = self.template_env.get_template("report_email.html")
        server_url = self._get_server_url()
        html_body = template.render(
            report=report,
            sort_options=sort_options or {},
            server_url=server_url,
        )
        logger.info(f"이메일 캠페인 제어 URL: {server_url}")

        subject = f"[네이버 광고 리포트] {report.account_name} - {report.report_date.strftime('%Y-%m-%d')}"
        self._send_html_email(recipient, subject, html_body)
        logger.info(f"보고서 메일 발송 완료: {report.account_name} -> {recipient}")

    def send_budget_alert(self, recipient: str, account_name: str,
                          daily_cost: float, threshold: float) -> None:
        template = self.template_env.get_template("alert_email.html")
        html_body = template.render(
            account_name=account_name,
            daily_cost=daily_cost,
            threshold=threshold,
        )

        subject = f"[예산 알림] {account_name} - 일 소진액 {daily_cost:,.0f}원 (기준: {threshold:,.0f}원 미만)"
        self._send_html_email(recipient, subject, html_body)
        logger.info(f"예산 알림 메일 발송 완료: {account_name} -> {recipient}")

    def _send_html_email(self, recipient: str, subject: str, html_body: str) -> None:
        from email.header import Header

        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = self.sender_email
        msg["To"] = recipient
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(self.SMTP_SERVER, self.SMTP_PORT) as server:
            server.starttls()
            server.login(self.sender_email, self.app_password)
            server.sendmail(self.sender_email, recipient, msg.as_string())

    def send_coupang_report(self, recipient: str, report) -> None:
        """쿠팡 광고 보고서 이메일 발송."""
        template = self.template_env.get_template("coupang_report_email.html")
        html_body = template.render(report=report)

        date_str = ""
        if report.date_from and report.date_to and report.date_from != report.date_to:
            date_str = f"{report.date_from.strftime('%Y-%m-%d')} ~ {report.date_to.strftime('%Y-%m-%d')}"
        elif report.report_date:
            date_str = report.report_date.strftime('%Y-%m-%d')

        subject = f"[쿠팡 광고 리포트] {report.account_name} - {date_str}"
        self._send_html_email(recipient, subject, html_body)
        logger.info(f"쿠팡 보고서 메일 발송 완료: {report.account_name} -> {recipient}")

    def send_gfa_report(self, recipient: str, report) -> None:
        """네이버 GFA 보고서 이메일 발송."""
        template = self.template_env.get_template("gfa_report_email.html")
        html_body = template.render(report=report)

        date_str = ""
        if report.date_from and report.date_to and report.date_from != report.date_to:
            date_str = f"{report.date_from.strftime('%Y-%m-%d')} ~ {report.date_to.strftime('%Y-%m-%d')}"
        elif report.date_from:
            date_str = report.date_from.strftime('%Y-%m-%d')

        subject = f"[네이버 GFA 리포트] {report.account_name} - {date_str}"
        self._send_html_email(recipient, subject, html_body)
        logger.info(f"GFA 보고서 메일 발송 완료: {report.account_name} -> {recipient}")

    def test_connection(self) -> bool:
        try:
            with smtplib.SMTP(self.SMTP_SERVER, self.SMTP_PORT) as server:
                server.starttls()
                server.login(self.sender_email, self.app_password)
            logger.info("SMTP 연결 테스트 성공")
            return True
        except Exception as e:
            logger.error(f"SMTP 연결 실패: {e}")
            return False
