import argparse
import logging
import os
import sys
from pathlib import Path

# 프로젝트 루트로 작업 디렉토리 변경
os.chdir(Path(__file__).parent)

from core.api_client import NaverAdsAPIClient
from core.config_manager import ConfigManager
from core.email_sender import NaverEmailSender
from core.scheduler import JobScheduler


def setup_logging(log_file: str = "logs/naver_ads_bot.log") -> None:
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def validate_config(config) -> bool:
    logger = logging.getLogger(__name__)
    all_ok = True

    logger.info("=== SMTP 연결 테스트 ===")
    email_sender = NaverEmailSender(config.email.sender_email, config.email.app_password)
    if email_sender.test_connection():
        logger.info("SMTP 연결 성공")
    else:
        logger.error("SMTP 연결 실패 - 이메일 주소와 앱 비밀번호를 확인하세요")
        all_ok = False

    for account in config.accounts:
        logger.info(f"=== API 테스트: {account.name} ===")
        try:
            client = NaverAdsAPIClient(
                account.customer_id, account.api_key, account.secret_key
            )
            campaigns = client.get_campaigns()
            logger.info(f"  캠페인 {len(campaigns)}개 조회 성공")
        except Exception as e:
            logger.error(f"  API 연결 실패: {e}")
            all_ok = False

    return all_ok


def main():
    parser = argparse.ArgumentParser(
        description="네이버 검색광고 보고서 자동화 봇",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python main.py                  웹 대시보드 + 스케줄러 (기본)
  python main.py --port 8080      포트 지정
  python main.py --run-now        보고서 즉시 발송 (CLI)
  python main.py --check-alert    예산 알림 즉시 체크 (CLI)
  python main.py --validate       설정 검증 (API/SMTP 테스트)
        """,
    )
    parser.add_argument("--config", default="config.json", help="설정 파일 경로 (기본: config.json)")
    parser.add_argument("--port", type=int, default=5000, help="웹 대시보드 포트 (기본: 5000)")
    parser.add_argument("--run-now", action="store_true", help="보고서 즉시 실행 (CLI)")
    parser.add_argument("--check-alert", action="store_true", help="예산 알림 즉시 체크 (CLI)")
    parser.add_argument("--validate", action="store_true", help="설정 검증 (API/SMTP 연결 테스트)")

    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger(__name__)

    config_mgr = ConfigManager(args.config)

    # config.json이 없으면 템플릿에서 자동 생성 (첫 실행)
    setup_mode = False
    if not Path(args.config).exists():
        config_mgr.create_default()
        logger.info("config.json이 없어서 기본 설정 파일을 생성했습니다.")
        setup_mode = True

    try:
        config = config_mgr.load(strict=not setup_mode)
        logger.info(f"설정 로드 완료: 네이버 계정 {len(config.accounts)}개, 쿠팡 계정 {len(config.coupang_accounts)}개")
    except (FileNotFoundError, ValueError) as e:
        # 설정이 비어있으면 셋업 모드로 진입
        logger.warning(f"설정 불완전: {e} → 셋업 모드로 대시보드 시작")
        config = config_mgr.load(strict=False)
        setup_mode = True

    if not setup_mode and args.validate:
        ok = validate_config(config)
        sys.exit(0 if ok else 1)

    if not setup_mode and args.run_now:
        scheduler = JobScheduler(config)
        scheduler.run_reports_now()
        return

    if not setup_mode and args.check_alert:
        scheduler = JobScheduler(config)
        scheduler.run_alerts_now()
        return

    # 기본: 웹 대시보드 + 백그라운드 스케줄러
    from web_app import create_app

    app = create_app(config, args.config, setup_mode=setup_mode)
    logger.info(f"웹 대시보드 시작: http://localhost:{args.port}")
    if setup_mode:
        print(f"\n  ==============================================")
        print(f"    초기 설정 모드로 시작합니다.")
        print(f"    대시보드에서 계정 정보를 입력해주세요.")
        print(f"    대시보드: http://localhost:{args.port}")
        print(f"  ==============================================\n")
    else:
        print(f"\n  네이버 광고 대시보드: http://localhost:{args.port}\n")
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
