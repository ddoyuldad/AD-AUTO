import logging
from datetime import date, datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request, redirect, url_for

from core.api_client import NaverAdsAPIClient
from core.config_manager import AppConfig, ConfigManager, AdAccount, CoupangAccount, GfaAccount
from core.scheduler import JobScheduler

logger = logging.getLogger(__name__)


def create_app(config: AppConfig, config_path: str = "config.json",
               setup_mode: bool = False) -> Flask:
    template_dir = str(Path(__file__).parent / "templates")
    app = Flask(__name__, template_folder=template_dir)
    config_mgr = ConfigManager(config_path)

    scheduler = None
    if not setup_mode and config.accounts and config.email.sender_email:
        scheduler = JobScheduler(config)
        scheduler.start()

    @app.route("/")
    def dashboard():
        return render_template(
            "dashboard.html",
            accounts=[
                {"name": a.name, "customer_id": a.customer_id}
                for a in config.accounts
            ],
            schedule_report_time=config.schedule.report_time if config.schedule else "09:00",
            alert_threshold=config.alert.daily_spend_threshold if config.alert else 50000,
            has_coupang=True,
            coupang_count=len(config.coupang_accounts),
            has_gfa=True,
            gfa_count=len(config.gfa_accounts),
            setup_mode=setup_mode,
        )

    @app.route("/api/accounts")
    def api_accounts():
        """등록된 계정 목록 조회"""
        show_full = request.args.get("full") == "1"
        accounts = []
        for i, a in enumerate(config.accounts):
            acc = {
                "index": i,
                "name": a.name,
                "customer_id": a.customer_id,
                "api_key": a.api_key if show_full else a.api_key[:20] + "...",
                "secret_key": a.secret_key if show_full else a.secret_key[:10] + "...",
                "report_recipients": a.report_recipients,
            }
            accounts.append(acc)
        return jsonify({"success": True, "accounts": accounts})

    @app.route("/api/accounts", methods=["POST"])
    def api_add_account():
        """새 계정 추가"""
        data = request.get_json()
        required = ["name", "customer_id", "api_key", "secret_key"]
        for key in required:
            if not data.get(key):
                return jsonify({"success": False, "message": f"'{key}' 값이 필요합니다"})

        try:
            raw = config_mgr.load_raw()
            default_recipients = [config.email.sender_email] if config.email and config.email.sender_email else []
            new_acc = {
                "name": data["name"],
                "customer_id": str(data["customer_id"]),
                "api_key": data["api_key"],
                "secret_key": data["secret_key"],
                "report_recipients": data.get("report_recipients", default_recipients),
            }
            raw["accounts"].append(new_acc)
            config_mgr.save_raw(raw)

            # 메모리 config에도 반영
            config.accounts.append(AdAccount(
                name=new_acc["name"],
                customer_id=new_acc["customer_id"],
                api_key=new_acc["api_key"],
                secret_key=new_acc["secret_key"],
                report_recipients=new_acc["report_recipients"],
            ))

            logger.info(f"계정 추가: {new_acc['name']}")
            return jsonify({"success": True, "message": f"[{new_acc['name']}] 계정 추가 완료"})
        except Exception as e:
            logger.error(f"계정 추가 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/accounts/<int:index>", methods=["PUT"])
    def api_update_account(index):
        """계정 수정"""
        if index < 0 or index >= len(config.accounts):
            return jsonify({"success": False, "message": "잘못된 계정 인덱스"})

        data = request.get_json()
        try:
            raw = config_mgr.load_raw()
            acc = raw["accounts"][index]

            if data.get("name"):
                acc["name"] = data["name"]
                config.accounts[index].name = data["name"]
            if data.get("customer_id"):
                acc["customer_id"] = str(data["customer_id"])
                config.accounts[index].customer_id = str(data["customer_id"])
            if data.get("api_key"):
                acc["api_key"] = data["api_key"]
                config.accounts[index].api_key = data["api_key"]
            if data.get("secret_key"):
                acc["secret_key"] = data["secret_key"]
                config.accounts[index].secret_key = data["secret_key"]
            if "report_recipients" in data:
                acc["report_recipients"] = data["report_recipients"]
                config.accounts[index].report_recipients = data["report_recipients"]

            config_mgr.save_raw(raw)
            logger.info(f"계정 수정: {acc['name']}")
            return jsonify({"success": True, "message": f"[{acc['name']}] 계정 수정 완료"})
        except Exception as e:
            logger.error(f"계정 수정 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/accounts/<int:index>", methods=["DELETE"])
    def api_delete_account(index):
        """계정 삭제"""
        if index < 0 or index >= len(config.accounts):
            return jsonify({"success": False, "message": "잘못된 계정 인덱스"})

        try:
            name = config.accounts[index].name
            raw = config_mgr.load_raw()
            raw["accounts"].pop(index)
            config_mgr.save_raw(raw)
            config.accounts.pop(index)

            logger.info(f"계정 삭제: {name}")
            return jsonify({"success": True, "message": f"[{name}] 계정 삭제 완료"})
        except Exception as e:
            logger.error(f"계정 삭제 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/costs")
    def api_costs():
        if not scheduler:
            return jsonify({"success": False, "message": "계정을 먼저 등록해주세요 (설정 후 서버 재시작 필요)"})
        try:
            costs = scheduler.get_current_costs()
            return jsonify({"success": True, "costs": costs})
        except Exception as e:
            logger.error(f"광고비 조회 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    def _extract_sort_options(data: dict) -> dict:
        return {
            "adgroup_sort_by": data.get("adgroup_sort_by", "cost"),
            "adgroup_sort_order": data.get("adgroup_sort_order", "desc"),
            "keyword_sort_by": data.get("keyword_sort_by", "cost"),
            "keyword_sort_order": data.get("keyword_sort_order", "desc"),
        }

    @app.route("/api/send-report", methods=["POST"])
    def api_send_report():
        if not scheduler:
            return jsonify({"success": False, "message": "계정/이메일 설정 후 서버를 재시작해주세요"})
        data = request.get_json()
        account_index = data.get("account_index", 0)
        date_from_str = data.get("date_from")
        date_to_str = data.get("date_to")
        sort_options = _extract_sort_options(data)

        date_from = None
        date_to = None
        if date_from_str:
            date_from = datetime.strptime(date_from_str, "%Y-%m-%d").date()
        if date_to_str:
            date_to = datetime.strptime(date_to_str, "%Y-%m-%d").date()

        try:
            result = scheduler.send_report_for_account(
                account_index, date_from, date_to, sort_options
            )
            return jsonify(result)
        except Exception as e:
            logger.error(f"보고서 발송 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/send-all-reports", methods=["POST"])
    def api_send_all_reports():
        if not scheduler:
            return jsonify({"success": False, "message": "계정/이메일 설정 후 서버를 재시작해주세요"})
        data = request.get_json() or {}
        date_from_str = data.get("date_from")
        date_to_str = data.get("date_to")

        date_from = None
        date_to = None
        if date_from_str:
            date_from = datetime.strptime(date_from_str, "%Y-%m-%d").date()
        if date_to_str:
            date_to = datetime.strptime(date_to_str, "%Y-%m-%d").date()

        sort_options = _extract_sort_options(data)

        try:
            results = []
            for i in range(len(config.accounts)):
                result = scheduler.send_report_for_account(i, date_from, date_to, sort_options)
                results.append(result)

            failed = [r for r in results if not r["success"]]
            if failed:
                return jsonify({"success": False, "message": " / ".join(r["message"] for r in failed)})
            return jsonify({"success": True, "message": "전체 보고서 발송 완료"})
        except Exception as e:
            logger.error(f"전체 보고서 발송 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    # ── 캠페인 ON/OFF 제어 ──

    @app.route("/api/campaigns")
    def api_campaigns():
        """모든 계정의 캠페인 목록 조회 (ON/OFF 제어용)"""
        all_campaigns = []
        for account in config.accounts:
            try:
                client = NaverAdsAPIClient(
                    account.customer_id, account.api_key, account.secret_key
                )
                campaigns = client.get_campaigns()
                for c in campaigns:
                    all_campaigns.append({
                        "campaign_id": c.get("nccCampaignId"),
                        "name": c.get("name"),
                        "status": c.get("status"),
                        "userLock": c.get("userLock", False),
                        "account": account.name,
                    })
            except Exception as e:
                logger.error(f"캠페인 조회 실패 ({account.name}): {e}")
        return jsonify({"success": True, "campaigns": all_campaigns})

    def _find_account_for_campaign(campaign_id: str):
        """캠페인 ID로 어떤 계정 소속인지 찾기"""
        for account in config.accounts:
            try:
                client = NaverAdsAPIClient(
                    account.customer_id, account.api_key, account.secret_key
                )
                campaigns = client.get_campaigns()
                for c in campaigns:
                    if c.get("nccCampaignId") == campaign_id:
                        return account, client, c
            except Exception:
                continue
        return None, None, None

    @app.route("/campaign/<campaign_id>/toggle")
    def campaign_toggle_page(campaign_id):
        """이메일에서 클릭 시 보여줄 캠페인 ON/OFF 확인 페이지"""
        action = request.args.get("action", "pause")  # pause or resume
        account, client, campaign = _find_account_for_campaign(campaign_id)

        if not campaign:
            return render_template_string(CAMPAIGN_ERROR_HTML, message="캠페인을 찾을 수 없습니다.")

        campaign_name = campaign.get("name", "이름없음")
        status = campaign.get("status", "")
        user_lock = campaign.get("userLock", False)
        current_status = "일시중지" if user_lock else "활성"
        action_label = "일시중지" if action == "pause" else "활성화"

        return render_template_string(
            CAMPAIGN_TOGGLE_HTML,
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            current_status=current_status,
            action=action,
            action_label=action_label,
            account_name=account.name if account else "",
        )

    @app.route("/api/campaign/<campaign_id>/toggle", methods=["POST"])
    def api_campaign_toggle(campaign_id):
        """캠페인 ON/OFF 실행 API"""
        data = request.get_json() or {}
        action = data.get("action", request.args.get("action", "pause"))

        account, client, campaign = _find_account_for_campaign(campaign_id)
        if not client or not campaign:
            return jsonify({"success": False, "message": "캠페인을 찾을 수 없습니다"})

        try:
            if action == "pause":
                client.pause_campaign(campaign_id)
                msg = f"'{campaign.get('name', '')}' 캠페인이 일시중지되었습니다."
            else:
                client.resume_campaign(campaign_id)
                msg = f"'{campaign.get('name', '')}' 캠페인이 활성화되었습니다."

            logger.info(msg)
            return jsonify({"success": True, "message": msg})
        except Exception as e:
            logger.error(f"캠페인 상태 변경 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    # ── 광고그룹 ON/OFF ──

    def _find_account_for_adgroup(adgroup_id: str):
        """광고그룹 ID로 어떤 계정 소속인지 찾기"""
        for account in config.accounts:
            try:
                client = NaverAdsAPIClient(
                    account.customer_id, account.api_key, account.secret_key
                )
                campaigns = client.get_campaigns()
                for c in campaigns:
                    adgroups = client.get_adgroups(c["nccCampaignId"])
                    for ag in adgroups:
                        if ag.get("nccAdgroupId") == adgroup_id:
                            return account, client, ag
            except Exception:
                continue
        return None, None, None

    @app.route("/adgroup/<adgroup_id>/toggle")
    def adgroup_toggle_page(adgroup_id):
        """이메일에서 클릭 시 보여줄 광고그룹 ON/OFF 확인 페이지"""
        action = request.args.get("action", "pause")
        account, client, adgroup = _find_account_for_adgroup(adgroup_id)

        if not adgroup:
            return render_template_string(CAMPAIGN_ERROR_HTML, message="광고그룹을 찾을 수 없습니다.")

        ag_name = adgroup.get("name", "이름없음")
        user_lock = adgroup.get("userLock", False)
        current_status = "일시중지" if user_lock else "활성"
        action_label = "일시중지" if action == "pause" else "활성화"

        return render_template_string(
            ADGROUP_TOGGLE_HTML,
            adgroup_id=adgroup_id,
            adgroup_name=ag_name,
            current_status=current_status,
            action=action,
            action_label=action_label,
            account_name=account.name if account else "",
        )

    @app.route("/api/adgroup/<adgroup_id>/toggle", methods=["POST"])
    def api_adgroup_toggle(adgroup_id):
        """광고그룹 ON/OFF 실행 API"""
        data = request.get_json() or {}
        action = data.get("action", request.args.get("action", "pause"))

        account, client, adgroup = _find_account_for_adgroup(adgroup_id)
        if not client or not adgroup:
            return jsonify({"success": False, "message": "광고그룹을 찾을 수 없습니다"})

        try:
            if action == "pause":
                client.pause_adgroup(adgroup_id)
                msg = f"'{adgroup.get('name', '')}' 광고그룹이 일시중지되었습니다."
            else:
                client.resume_adgroup(adgroup_id)
                msg = f"'{adgroup.get('name', '')}' 광고그룹이 활성화되었습니다."

            logger.info(msg)
            return jsonify({"success": True, "message": msg})
        except Exception as e:
            logger.error(f"광고그룹 상태 변경 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    # ── 설정 관리 API ──

    @app.route("/api/settings")
    def api_get_settings():
        """현재 설정 조회"""
        try:
            raw = config_mgr.load_raw()
            email_cfg = raw.get("email", {})
            schedule_cfg = raw.get("schedule", {})
            alert_cfg = raw.get("alert", {})
            return jsonify({
                "success": True,
                "settings": {
                    "email": {
                        "sender_email": email_cfg.get("sender_email", ""),
                        "app_password": email_cfg.get("app_password", ""),
                    },
                    "schedule": {
                        "report_time": schedule_cfg.get("report_time", "09:00"),
                        "alert_check_time": schedule_cfg.get("alert_check_time", "23:00"),
                    },
                    "alert": {
                        "enabled": alert_cfg.get("enabled", True),
                        "daily_spend_threshold": alert_cfg.get("daily_spend_threshold", 50000),
                    },
                    "server_url": raw.get("server_url", ""),
                },
            })
        except Exception as e:
            logger.error(f"설정 조회 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/settings/email", methods=["PUT"])
    def api_update_email_settings():
        """이메일 설정 수정"""
        data = request.get_json()
        try:
            raw = config_mgr.load_raw()
            if "email" not in raw:
                raw["email"] = {}
            if data.get("sender_email"):
                raw["email"]["sender_email"] = data["sender_email"]
                config.email.sender_email = data["sender_email"]
            if data.get("app_password"):
                raw["email"]["app_password"] = data["app_password"]
                config.email.app_password = data["app_password"]
            config_mgr.save_raw(raw)
            logger.info("이메일 설정 수정 완료")
            return jsonify({"success": True, "message": "이메일 설정이 저장되었습니다"})
        except Exception as e:
            logger.error(f"이메일 설정 수정 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/settings/schedule", methods=["PUT"])
    def api_update_schedule_settings():
        """스케줄 설정 수정"""
        data = request.get_json()
        try:
            raw = config_mgr.load_raw()
            if "schedule" not in raw:
                raw["schedule"] = {}
            if data.get("report_time"):
                raw["schedule"]["report_time"] = data["report_time"]
                config.schedule.report_time = data["report_time"]
            if data.get("alert_check_time"):
                raw["schedule"]["alert_check_time"] = data["alert_check_time"]
                config.schedule.alert_check_time = data["alert_check_time"]
            config_mgr.save_raw(raw)
            logger.info("스케줄 설정 수정 완료")
            return jsonify({"success": True, "message": "스케줄 설정이 저장되었습니다"})
        except Exception as e:
            logger.error(f"스케줄 설정 수정 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/settings/alert", methods=["PUT"])
    def api_update_alert_settings():
        """알림 설정 수정"""
        data = request.get_json()
        try:
            raw = config_mgr.load_raw()
            if "alert" not in raw:
                raw["alert"] = {}
            if "enabled" in data:
                raw["alert"]["enabled"] = bool(data["enabled"])
                config.alert.enabled = bool(data["enabled"])
            if "daily_spend_threshold" in data:
                raw["alert"]["daily_spend_threshold"] = float(data["daily_spend_threshold"])
                config.alert.daily_spend_threshold = float(data["daily_spend_threshold"])
            config_mgr.save_raw(raw)
            logger.info("알림 설정 수정 완료")
            return jsonify({"success": True, "message": "알림 설정이 저장되었습니다"})
        except Exception as e:
            logger.error(f"알림 설정 수정 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/settings/server-url", methods=["PUT"])
    def api_update_server_url():
        """서버 URL 수정"""
        data = request.get_json()
        try:
            raw = config_mgr.load_raw()
            raw["server_url"] = data.get("server_url", "")
            config.server_url = data.get("server_url", "")
            config_mgr.save_raw(raw)
            logger.info(f"서버 URL 수정: {config.server_url}")
            return jsonify({"success": True, "message": "서버 URL이 저장되었습니다"})
        except Exception as e:
            logger.error(f"서버 URL 수정 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    # ── 쿠팡 계정 관리 (CRUD) ──

    @app.route("/api/coupang-accounts")
    def api_coupang_accounts():
        """쿠팡 계정 목록 조회"""
        accounts = []
        for i, c in enumerate(config.coupang_accounts):
            accounts.append({
                "index": i,
                "name": c.name,
                "wing_id": c.wing_id,
                "wing_password": c.wing_password,
                "report_recipients": c.report_recipients,
                "headless": c.headless,
            })
        return jsonify({"success": True, "accounts": accounts})

    @app.route("/api/coupang-accounts", methods=["POST"])
    def api_add_coupang_account():
        """쿠팡 계정 추가"""
        data = request.get_json()
        if not data.get("wing_id"):
            return jsonify({"success": False, "message": "Wing ID가 필요합니다"})
        if not data.get("wing_password"):
            return jsonify({"success": False, "message": "Wing 비밀번호가 필요합니다"})

        try:
            raw = config_mgr.load_raw()
            if "coupang_accounts" not in raw:
                # 기존 단일 coupang → 배열로 마이그레이션
                old = raw.pop("coupang", None)
                raw["coupang_accounts"] = [old] if old and old.get("wing_id") else []

            new_acc = {
                "name": data.get("name", "쿠팡 광고"),
                "wing_id": data["wing_id"],
                "wing_password": data["wing_password"],
                "report_recipients": data.get("report_recipients", []),
                "headless": data.get("headless", True),
            }
            raw["coupang_accounts"].append(new_acc)
            config_mgr.save_raw(raw)

            # 메모리에도 반영
            config.coupang_accounts.append(CoupangAccount(
                name=new_acc["name"],
                wing_id=new_acc["wing_id"],
                wing_password=new_acc["wing_password"],
                report_recipients=new_acc["report_recipients"],
                headless=new_acc["headless"],
            ))

            logger.info(f"쿠팡 계정 추가: {new_acc['name']} ({new_acc['wing_id']})")
            return jsonify({"success": True, "message": f"[{new_acc['name']}] 쿠팡 계정 추가 완료"})
        except Exception as e:
            logger.error(f"쿠팡 계정 추가 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/coupang-accounts/<int:index>", methods=["PUT"])
    def api_update_coupang_account(index):
        """쿠팡 계정 수정"""
        if index < 0 or index >= len(config.coupang_accounts):
            return jsonify({"success": False, "message": "잘못된 계정 인덱스"})

        data = request.get_json()
        try:
            raw = config_mgr.load_raw()
            if "coupang_accounts" not in raw:
                old = raw.pop("coupang", None)
                raw["coupang_accounts"] = [old] if old and old.get("wing_id") else []

            cpg = raw["coupang_accounts"][index]
            mem = config.coupang_accounts[index]

            if "name" in data:
                cpg["name"] = data["name"]; mem.name = data["name"]
            if "wing_id" in data:
                cpg["wing_id"] = data["wing_id"]; mem.wing_id = data["wing_id"]
            if "wing_password" in data:
                cpg["wing_password"] = data["wing_password"]; mem.wing_password = data["wing_password"]
            if "report_recipients" in data:
                cpg["report_recipients"] = data["report_recipients"]; mem.report_recipients = data["report_recipients"]
            if "headless" in data:
                cpg["headless"] = bool(data["headless"]); mem.headless = bool(data["headless"])

            config_mgr.save_raw(raw)
            logger.info(f"쿠팡 계정 수정: {cpg['name']}")
            return jsonify({"success": True, "message": f"[{cpg['name']}] 쿠팡 계정 수정 완료"})
        except Exception as e:
            logger.error(f"쿠팡 계정 수정 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/coupang-accounts/<int:index>", methods=["DELETE"])
    def api_delete_coupang_account(index):
        """쿠팡 계정 삭제"""
        if index < 0 or index >= len(config.coupang_accounts):
            return jsonify({"success": False, "message": "잘못된 계정 인덱스"})

        try:
            name = config.coupang_accounts[index].name
            raw = config_mgr.load_raw()
            if "coupang_accounts" not in raw:
                old = raw.pop("coupang", None)
                raw["coupang_accounts"] = [old] if old and old.get("wing_id") else []
            raw["coupang_accounts"].pop(index)
            config_mgr.save_raw(raw)
            config.coupang_accounts.pop(index)

            logger.info(f"쿠팡 계정 삭제: {name}")
            return jsonify({"success": True, "message": f"[{name}] 쿠팡 계정 삭제 완료"})
        except Exception as e:
            logger.error(f"쿠팡 계정 삭제 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    # ── 쿠팡 광고 보고서 ──

    @app.route("/api/send-coupang-report", methods=["POST"])
    def api_send_coupang_report():
        """쿠팡 광고 보고서 생성 및 발송"""
        if not scheduler:
            return jsonify({"success": False, "message": "계정/이메일 설정 후 서버를 재시작해주세요"})
        data = request.get_json() or {}
        from datetime import datetime as dt

        date_from = None
        date_to = None
        if data.get("date_from"):
            date_from = dt.strptime(data["date_from"], "%Y-%m-%d").date()
        if data.get("date_to"):
            date_to = dt.strptime(data["date_to"], "%Y-%m-%d").date()

        account_index = data.get("account_index", 0)

        try:
            result = scheduler.send_coupang_report(date_from, date_to, account_index=account_index)
            return jsonify(result)
        except Exception as e:
            logger.error(f"쿠팡 보고서 발송 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/send-all-coupang-reports", methods=["POST"])
    def api_send_all_coupang_reports():
        """모든 쿠팡 계정 보고서 발송"""
        if not scheduler:
            return jsonify({"success": False, "message": "계정/이메일 설정 후 서버를 재시작해주세요"})
        data = request.get_json() or {}
        from datetime import datetime as dt

        date_from = None
        date_to = None
        if data.get("date_from"):
            date_from = dt.strptime(data["date_from"], "%Y-%m-%d").date()
        if data.get("date_to"):
            date_to = dt.strptime(data["date_to"], "%Y-%m-%d").date()

        try:
            results = []
            for i in range(len(config.coupang_accounts)):
                result = scheduler.send_coupang_report(date_from, date_to, account_index=i)
                results.append(result)

            failed = [r for r in results if not r["success"]]
            if failed:
                return jsonify({"success": False, "message": " / ".join(r["message"] for r in failed)})
            return jsonify({"success": True, "message": f"쿠팡 전체 {len(results)}개 계정 보고서 발송 완료"})
        except Exception as e:
            logger.error(f"쿠팡 전체 보고서 발송 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    # ── 쿠팡 캠페인 ON/OFF ──

    @app.route("/api/coupang-campaigns")
    def api_coupang_campaigns():
        """쿠팡 캠페인 목록 조회.

        cache_only=true 이면 dom_scraped.json에서 빠르게 반환.
        아니면 Selenium으로 실시간 조회 (30~60초 소요).
        """
        account_index = request.args.get("account_index", 0, type=int)
        cache_only = request.args.get("cache_only", "false").lower() == "true"

        if account_index >= len(config.coupang_accounts):
            return jsonify({"success": False, "campaigns": [], "message": "잘못된 계정"})

        # 캐시 모드: dom_scraped.json에서 빠르게 캠페인 이름 반환
        if cache_only:
            try:
                import json as _json
                dom_file = Path(__file__).parent / "downloads" / "coupang" / "debug" / "dom_scraped.json"
                if dom_file.exists():
                    with open(dom_file, "r", encoding="utf-8") as f:
                        dom_data = _json.load(f)
                    names = dom_data.get("_campaign_names", [])
                    if names:
                        campaigns = [{"name": n, "status": "ON", "index": i} for i, n in enumerate(names)]
                        return jsonify({"success": True, "campaigns": campaigns, "cached": True})
            except Exception:
                pass
            return jsonify({"success": True, "campaigns": [], "message": "캐시 데이터 없음"})

        # 실시간 조회: Selenium으로 로그인 후 캠페인 목록 가져오기
        coupang = config.coupang_accounts[account_index]
        try:
            from core.coupang_scraper import CoupangAdsScraper
            scraper = CoupangAdsScraper(
                wing_id=coupang.wing_id,
                wing_password=coupang.wing_password,
                headless=coupang.headless,
            )
            scraper.start()
            if not scraper.login():
                scraper.close()
                return jsonify({"success": False, "campaigns": [], "message": "쿠팡 로그인 실패"})

            campaigns = scraper.get_campaign_list()
            scraper.close()
            return jsonify({"success": True, "campaigns": campaigns})
        except Exception as e:
            logger.error(f"쿠팡 캠페인 조회 실패: {e}", exc_info=True)
            return jsonify({"success": False, "campaigns": [], "message": str(e)})

    @app.route("/api/coupang-campaign/toggle", methods=["POST"])
    def api_coupang_campaign_toggle():
        """쿠팡 캠페인 ON/OFF 토글 (Selenium)."""
        data = request.get_json() or {}
        campaign_name = data.get("campaign_name", "")
        action = data.get("action", "pause")  # pause=OFF, resume=ON
        account_index = data.get("account_index", 0)

        if not campaign_name:
            return jsonify({"success": False, "message": "캠페인 이름이 필요합니다"})

        if account_index >= len(config.coupang_accounts):
            return jsonify({"success": False, "message": "잘못된 계정"})

        coupang = config.coupang_accounts[account_index]
        try:
            from core.coupang_scraper import CoupangAdsScraper
            scraper = CoupangAdsScraper(
                wing_id=coupang.wing_id,
                wing_password=coupang.wing_password,
                headless=coupang.headless,
            )
            scraper.start()
            if not scraper.login():
                scraper.close()
                return jsonify({"success": False, "message": "쿠팡 로그인 실패"})

            result = scraper.toggle_campaign(campaign_name, action)
            scraper.close()
            return jsonify(result)
        except Exception as e:
            logger.error(f"쿠팡 캠페인 토글 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    # ── GFA 계정 관리 (CRUD) ──

    @app.route("/api/gfa-accounts")
    def api_gfa_accounts():
        """GFA 계정 목록 조회"""
        accounts = []
        for i, g in enumerate(config.gfa_accounts):
            accounts.append({
                "index": i,
                "name": g.name,
                "naver_id": g.naver_id,
                "ad_account_id": g.ad_account_id,
                "has_password": bool(g.naver_password),
                "headless": g.headless,
                "report_recipients": g.report_recipients,
            })
        return jsonify({"success": True, "accounts": accounts})

    @app.route("/api/gfa-accounts", methods=["POST"])
    def api_add_gfa_account():
        """GFA 계정 추가"""
        data = request.get_json()
        if not data.get("naver_id"):
            return jsonify({"success": False, "message": "네이버 ID가 필요합니다"})

        try:
            raw = config_mgr.load_raw()
            if "gfa_accounts" not in raw:
                raw["gfa_accounts"] = []

            new_acc = {
                "name": data.get("name", "네이버 GFA"),
                "naver_id": data["naver_id"],
                "naver_password": data.get("naver_password", ""),
                "ad_account_id": data.get("ad_account_id", ""),
                "report_recipients": data.get("report_recipients", []),
                "headless": data.get("headless", False),
            }
            raw["gfa_accounts"].append(new_acc)
            config_mgr.save_raw(raw)

            config.gfa_accounts.append(GfaAccount(
                name=new_acc["name"],
                naver_id=new_acc["naver_id"],
                naver_password=new_acc["naver_password"],
                ad_account_id=new_acc["ad_account_id"],
                report_recipients=new_acc["report_recipients"],
                headless=new_acc["headless"],
            ))

            logger.info(f"GFA 계정 추가: {new_acc['name']}")
            return jsonify({"success": True, "message": f"[{new_acc['name']}] GFA 계정 추가 완료"})
        except Exception as e:
            logger.error(f"GFA 계정 추가 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/gfa-accounts/<int:index>", methods=["PUT"])
    def api_update_gfa_account(index):
        """GFA 계정 수정"""
        if index < 0 or index >= len(config.gfa_accounts):
            return jsonify({"success": False, "message": "잘못된 계정 인덱스"})

        data = request.get_json()
        try:
            raw = config_mgr.load_raw()
            if "gfa_accounts" not in raw:
                raw["gfa_accounts"] = []

            gfa = raw["gfa_accounts"][index]
            mem = config.gfa_accounts[index]

            if "name" in data:
                gfa["name"] = data["name"]; mem.name = data["name"]
            if "naver_id" in data:
                gfa["naver_id"] = data["naver_id"]; mem.naver_id = data["naver_id"]
            if data.get("naver_password"):
                gfa["naver_password"] = data["naver_password"]; mem.naver_password = data["naver_password"]
            if "ad_account_id" in data:
                gfa["ad_account_id"] = data["ad_account_id"]; mem.ad_account_id = data["ad_account_id"]
            if "report_recipients" in data:
                gfa["report_recipients"] = data["report_recipients"]; mem.report_recipients = data["report_recipients"]
            if "headless" in data:
                gfa["headless"] = data["headless"]; mem.headless = data["headless"]

            config_mgr.save_raw(raw)
            logger.info(f"GFA 계정 수정: {gfa['name']}")
            return jsonify({"success": True, "message": f"[{gfa['name']}] GFA 계정 수정 완료"})
        except Exception as e:
            logger.error(f"GFA 계정 수정 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/gfa-accounts/<int:index>", methods=["DELETE"])
    def api_delete_gfa_account(index):
        """GFA 계정 삭제"""
        if index < 0 or index >= len(config.gfa_accounts):
            return jsonify({"success": False, "message": "잘못된 계정 인덱스"})

        try:
            name = config.gfa_accounts[index].name
            raw = config_mgr.load_raw()
            if "gfa_accounts" not in raw:
                raw["gfa_accounts"] = []
            raw["gfa_accounts"].pop(index)
            config_mgr.save_raw(raw)
            config.gfa_accounts.pop(index)

            logger.info(f"GFA 계정 삭제: {name}")
            return jsonify({"success": True, "message": f"[{name}] GFA 계정 삭제 완료"})
        except Exception as e:
            logger.error(f"GFA 계정 삭제 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    # ── GFA 보고서 ──

    @app.route("/api/send-gfa-report", methods=["POST"])
    def api_send_gfa_report():
        """GFA 보고서 생성 및 발송"""
        if not scheduler:
            return jsonify({"success": False, "message": "계정/이메일 설정 후 서버를 재시작해주세요"})
        data = request.get_json() or {}
        from datetime import datetime as dt

        date_from = None
        date_to = None
        if data.get("date_from"):
            date_from = dt.strptime(data["date_from"], "%Y-%m-%d").date()
        if data.get("date_to"):
            date_to = dt.strptime(data["date_to"], "%Y-%m-%d").date()

        account_index = data.get("account_index", 0)

        try:
            result = scheduler.send_gfa_report(date_from, date_to, account_index=account_index)
            return jsonify(result)
        except Exception as e:
            logger.error(f"GFA 보고서 발송 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/send-all-gfa-reports", methods=["POST"])
    def api_send_all_gfa_reports():
        """모든 GFA 계정 보고서 발송"""
        if not scheduler:
            return jsonify({"success": False, "message": "계정/이메일 설정 후 서버를 재시작해주세요"})
        data = request.get_json() or {}
        from datetime import datetime as dt

        date_from = None
        date_to = None
        if data.get("date_from"):
            date_from = dt.strptime(data["date_from"], "%Y-%m-%d").date()
        if data.get("date_to"):
            date_to = dt.strptime(data["date_to"], "%Y-%m-%d").date()

        try:
            results = []
            for i in range(len(config.gfa_accounts)):
                result = scheduler.send_gfa_report(date_from, date_to, account_index=i)
                results.append(result)

            failed = [r for r in results if not r["success"]]
            if failed:
                return jsonify({"success": False, "message": " / ".join(r["message"] for r in failed)})
            return jsonify({"success": True, "message": f"GFA 전체 {len(results)}개 계정 보고서 발송 완료"})
        except Exception as e:
            logger.error(f"GFA 전체 보고서 발송 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/coupang-test-login", methods=["POST"])
    def api_coupang_test_login():
        """쿠팡 로그인 테스트 (디버그용)"""
        data = request.get_json() or {}
        account_index = data.get("account_index", 0)

        if not config.coupang_accounts:
            return jsonify({"success": False, "message": "쿠팡 설정이 없습니다"})
        if account_index < 0 or account_index >= len(config.coupang_accounts):
            return jsonify({"success": False, "message": "잘못된 계정 인덱스"})

        cpg = config.coupang_accounts[account_index]
        try:
            from core.coupang_scraper import CoupangAdsScraper

            scraper = CoupangAdsScraper(
                wing_id=cpg.wing_id,
                wing_password=cpg.wing_password,
                headless=cpg.headless,
            )
            scraper.start()
            try:
                login_ok = scraper.login()
                screenshot = scraper.get_dashboard_screenshot("test_login")
                return jsonify({
                    "success": login_ok,
                    "message": "로그인 성공" if login_ok else "로그인 실패",
                    "screenshot": screenshot,
                    "current_url": scraper.driver.current_url if scraper.driver else "",
                })
            finally:
                scraper.close()
        except Exception as e:
            logger.error(f"쿠팡 로그인 테스트 실패: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)})

    # 간단한 HTML 템플릿 (별도 파일 없이 인라인)
    from flask import render_template_string

    CAMPAIGN_TOGGLE_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>캠페인 상태 변경</title>
<style>
body{font-family:'Malgun Gothic',sans-serif;background:#f0f2f5;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;}
.card{background:#fff;border-radius:12px;padding:32px;max-width:400px;width:90%;box-shadow:0 2px 12px rgba(0,0,0,0.08);text-align:center;}
h2{color:#1a472a;margin:0 0 8px;}
.status{color:#888;font-size:14px;margin-bottom:20px;}
.btn{display:inline-block;padding:12px 32px;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer;border:none;color:#fff;margin:6px;}
.btn-pause{background:#ef4444;}
.btn-resume{background:#10b981;}
.btn-cancel{background:#ccc;color:#555;}
.result{margin-top:16px;padding:12px;border-radius:8px;display:none;}
.result.ok{background:#d1fae5;color:#065f46;display:block;}
.result.err{background:#fee2e2;color:#991b1b;display:block;}
</style></head>
<body>
<div class="card">
  <h2>{{ campaign_name }}</h2>
  <p class="status">계정: {{ account_name }} | 현재 상태: {{ current_status }}</p>
  <div id="buttons">
    <p>이 캠페인을 <strong>{{ action_label }}</strong>하시겠습니까?</p>
    <button class="btn {% if action == 'pause' %}btn-pause{% else %}btn-resume{% endif %}" onclick="doToggle()">{{ action_label }}</button>
    <button class="btn btn-cancel" onclick="window.close()">취소</button>
  </div>
  <div id="result" class="result"></div>
</div>
<script>
function doToggle(){
  document.getElementById('buttons').style.display='none';
  fetch('/api/campaign/{{ campaign_id }}/toggle',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:'{{ action }}'})
  })
  .then(r=>r.json())
  .then(d=>{
    var el=document.getElementById('result');
    el.textContent=d.message;
    el.className='result '+(d.success?'ok':'err');
  })
  .catch(e=>{
    var el=document.getElementById('result');
    el.textContent='오류: '+e;
    el.className='result err';
  });
}
</script>
</body></html>
"""

    ADGROUP_TOGGLE_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>광고그룹 상태 변경</title>
<style>
body{font-family:'Malgun Gothic',sans-serif;background:#f0f2f5;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;}
.card{background:#fff;border-radius:12px;padding:32px;max-width:400px;width:90%;box-shadow:0 2px 12px rgba(0,0,0,0.08);text-align:center;}
h2{color:#1a472a;margin:0 0 8px;}
.status{color:#888;font-size:14px;margin-bottom:20px;}
.btn{display:inline-block;padding:12px 32px;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer;border:none;color:#fff;margin:6px;}
.btn-pause{background:#ef4444;}
.btn-resume{background:#10b981;}
.btn-cancel{background:#ccc;color:#555;}
.result{margin-top:16px;padding:12px;border-radius:8px;display:none;}
.result.ok{background:#d1fae5;color:#065f46;display:block;}
.result.err{background:#fee2e2;color:#991b1b;display:block;}
</style></head>
<body>
<div class="card">
  <h2>{{ adgroup_name }}</h2>
  <p class="status">계정: {{ account_name }} | 현재 상태: {{ current_status }}</p>
  <div id="buttons">
    <p>이 광고그룹을 <strong>{{ action_label }}</strong>하시겠습니까?</p>
    <button class="btn {% if action == 'pause' %}btn-pause{% else %}btn-resume{% endif %}" onclick="doToggle()">{{ action_label }}</button>
    <button class="btn btn-cancel" onclick="window.close()">취소</button>
  </div>
  <div id="result" class="result"></div>
</div>
<script>
function doToggle(){
  document.getElementById('buttons').style.display='none';
  fetch('/api/adgroup/{{ adgroup_id }}/toggle',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:'{{ action }}'})
  })
  .then(r=>r.json())
  .then(d=>{
    var el=document.getElementById('result');
    el.textContent=d.message;
    el.className='result '+(d.success?'ok':'err');
  })
  .catch(e=>{
    var el=document.getElementById('result');
    el.textContent='오류: '+e;
    el.className='result err';
  });
}
</script>
</body></html>
"""

    CAMPAIGN_ERROR_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>오류</title>
<style>body{font-family:'Malgun Gothic',sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#f0f2f5;}
.card{background:#fff;border-radius:12px;padding:32px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,0.08);}</style></head>
<body><div class="card"><h2 style="color:#ef4444;">{{ message }}</h2><p>서버가 실행 중인지 확인하세요.</p></div></body></html>
"""

    return app
