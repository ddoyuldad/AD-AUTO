import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AdAccount:
    name: str
    customer_id: str
    api_key: str
    secret_key: str
    report_recipients: list[str] = field(default_factory=list)


@dataclass
class EmailConfig:
    sender_email: str
    app_password: str


@dataclass
class ScheduleConfig:
    report_time: str = "09:00"
    alert_check_time: str = "23:00"


@dataclass
class AlertConfig:
    enabled: bool = True
    daily_spend_threshold: float = 50000.0


@dataclass
class CoupangAccount:
    name: str = "쿠팡 광고"
    wing_id: str = ""
    wing_password: str = ""
    report_recipients: list[str] = field(default_factory=list)
    headless: bool = True  # 브라우저 숨김 모드


@dataclass
class GfaAccount:
    name: str = "네이버 GFA"
    naver_id: str = ""             # 네이버 로그인 ID
    naver_password: str = ""       # 네이버 로그인 비밀번호
    ad_account_id: str = ""        # 광고주센터 계정 고유번호 (예: 1749323)
    report_recipients: list[str] = field(default_factory=list)
    headless: bool = False         # 브라우저 숨김 모드


@dataclass
class AppConfig:
    accounts: list[AdAccount] = field(default_factory=list)
    email: EmailConfig = None
    schedule: ScheduleConfig = None
    alert: AlertConfig = None
    server_url: str = ""  # 캠페인 제어 링크용 (예: http://172.30.1.48:5000)
    coupang_accounts: list[CoupangAccount] = field(default_factory=list)
    gfa_accounts: list[GfaAccount] = field(default_factory=list)

    @property
    def coupang(self):
        """하위 호환: 첫 번째 쿠팡 계정 반환 (없으면 None)."""
        return self.coupang_accounts[0] if self.coupang_accounts else None


class ConfigManager:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)

    def save_raw(self, raw: dict) -> None:
        """config.json에 원본 dict를 저장."""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

    def load_raw(self) -> dict:
        """config.json을 원본 dict로 읽기."""
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def create_default(self) -> None:
        """config.template.json을 복사하여 config.json 생성 (첫 실행 시)."""
        template = self.config_path.parent / "config.template.json"
        if template.exists():
            shutil.copy(template, self.config_path)
        else:
            default = {
                "accounts": [],
                "email": {"sender_email": "", "app_password": ""},
                "schedule": {"report_time": "09:00", "alert_check_time": "23:00"},
                "alert": {"enabled": True, "daily_spend_threshold": 50000.0},
                "server_url": "",
                "coupang_accounts": [],
                "gfa_accounts": [],
            }
            self.save_raw(default)

    def load(self, strict: bool = True) -> AppConfig:
        if not self.config_path.exists():
            if strict:
                raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {self.config_path}")
            self.create_default()

        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        if strict:
            self._validate(raw)
        return self._parse(raw)

    def _validate(self, raw: dict) -> None:
        if "accounts" not in raw or not raw["accounts"]:
            raise ValueError("최소 1개 이상의 광고 계정이 필요합니다 (accounts)")

        for i, acc in enumerate(raw["accounts"]):
            for key in ("name", "customer_id", "api_key", "secret_key"):
                if key not in acc or not acc[key]:
                    raise ValueError(f"accounts[{i}]에 '{key}' 값이 필요합니다")

        if "email" not in raw:
            raise ValueError("이메일 설정이 필요합니다 (email)")
        for key in ("sender_email", "app_password"):
            if key not in raw["email"] or not raw["email"][key]:
                raise ValueError(f"email.{key} 값이 필요합니다")

    def _parse(self, raw: dict) -> AppConfig:
        email_raw = raw.get("email", {})
        sender_email = email_raw.get("sender_email", "")

        accounts = []
        for acc in raw.get("accounts", []):
            accounts.append(AdAccount(
                name=acc["name"],
                customer_id=str(acc["customer_id"]),
                api_key=acc["api_key"],
                secret_key=acc["secret_key"],
                report_recipients=acc.get("report_recipients", [sender_email] if sender_email else []),
            ))

        email = EmailConfig(
            sender_email=sender_email,
            app_password=email_raw.get("app_password", ""),
        )

        sched_raw = raw.get("schedule", {})
        schedule = ScheduleConfig(
            report_time=sched_raw.get("report_time", "09:00"),
            alert_check_time=sched_raw.get("alert_check_time", "23:00"),
        )

        alert_raw = raw.get("alert", {})
        alert = AlertConfig(
            enabled=alert_raw.get("enabled", True),
            daily_spend_threshold=alert_raw.get("daily_spend_threshold", 50000.0),
        )

        # 쿠팡 광고 설정 (배열 또는 단일 객체 모두 지원)
        coupang_accounts = []
        coupang_raw = raw.get("coupang_accounts") or raw.get("coupang")

        if coupang_raw:
            # 단일 객체 → 배열로 변환 (하위 호환)
            if isinstance(coupang_raw, dict):
                coupang_raw = [coupang_raw]

            for cpg in coupang_raw:
                if cpg.get("wing_id"):
                    coupang_accounts.append(CoupangAccount(
                        name=cpg.get("name", "쿠팡 광고"),
                        wing_id=cpg["wing_id"],
                        wing_password=cpg.get("wing_password", ""),
                        report_recipients=cpg.get(
                            "report_recipients", [sender_email] if sender_email else []
                        ),
                        headless=cpg.get("headless", True),
                    ))

        # GFA 광고 설정
        gfa_accounts = []
        for gfa in raw.get("gfa_accounts", []):
            if gfa.get("naver_id"):
                gfa_accounts.append(GfaAccount(
                    name=gfa.get("name", "네이버 GFA"),
                    naver_id=gfa["naver_id"],
                    naver_password=gfa.get("naver_password", ""),
                    ad_account_id=gfa.get("ad_account_id", ""),
                    report_recipients=gfa.get(
                        "report_recipients", [sender_email] if sender_email else []
                    ),
                    headless=gfa.get("headless", False),
                ))

        return AppConfig(
            accounts=accounts,
            email=email,
            schedule=schedule,
            alert=alert,
            server_url=raw.get("server_url", ""),
            coupang_accounts=coupang_accounts,
            gfa_accounts=gfa_accounts,
        )
