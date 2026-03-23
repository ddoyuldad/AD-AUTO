# CLAUDE.md — naver-ads-bot 프로젝트 가이드

> 이 파일은 Claude(AI)가 이 프로젝트를 이해하고 작업을 이어갈 때 참고하는 컨텍스트 문서입니다.
> 마지막 업데이트: 2026-03-18

---

## 📌 프로젝트 개요

**네이버 검색광고 + 쿠팡 광고 + 네이버 GFA(성과형 DA) 자동화 봇**

- 네이버 검색광고 API를 통해 캠페인/키워드 실적을 수집하고 이메일 보고서 자동 발송
- 쿠팡 광고센터를 Selenium으로 스크래핑하여 보고서 수집
- 네이버 GFA(성과형 디스플레이 광고)를 Selenium으로 스크래핑
- Flask 웹 대시보드로 설정 관리, 즉시 실행, 스케줄 관리

---

## ✅ 완성된 기능

### 1. 네이버 검색광고 (API 연동)
- 네이버 검색광고 API(`api.naver.com`) 인증 (HMAC-SHA256 서명)
- 캠페인 / 광고그룹 / 키워드 실적 조회 (전일 기준)
- 파워링크 + 쇼핑 광고 통합 지표: 노출수, 클릭수, CTR, CPC, 전환수, ROAS, 평균순위 등
- 지역별 / 요일별 분석 지표 수집
- 캠페인 ON/OFF 제어 (API)
- 일일 예산 소진율 알림 (30분 간격 체크)
- HTML 이메일 보고서 자동 발송

### 2. 쿠팡 광고 (Selenium 스크래퍼)
- `advertising.coupang.com` 로그인 자동화
- 광고 보고서 엑셀 다운로드 (전일 기준)
- 다운로드 파일 파싱 후 이메일 보고서 발송
- 디버그 스크린샷/HTML 저장 (`downloads/coupang/debug/`)

### 3. 네이버 GFA (Selenium 스크래퍼)
- 네이버 광고주센터(`searchad.naver.com`) 로그인 자동화
- 2단계 인증(신규 기기 인증) 대기 처리
- 광고 계정 목록 → [성과형 DA] 버튼 클릭 → GFA 대시보드 이동
- 대시보드 데이터 스크래핑 및 이메일 보고서 발송
- 디버그 스크린샷/HTML 저장 (`downloads/gfa/debug/`)

### 4. 웹 대시보드 (Flask)
- 계정 설정 UI (네이버 / 쿠팡 / GFA 계정 등록·수정·삭제)
- 이메일 / 스케줄 / 알림 설정 UI
- 보고서 즉시 실행 버튼
- 캠페인 상태 조회 및 ON/OFF 토글
- 초기 설정 마법사 (셋업 모드)

### 5. 스케줄러 (APScheduler)
- 매일 지정 시각에 전체 보고서 자동 발송 (기본: 09:00)
- 30분마다 예산 소진율 체크 → 임계값 초과 시 알림 이메일 발송
- 매일 자정 알림 기록 초기화

---

## 📁 파일 구조

```
naver-ads-bot/
│
├── main.py                    # 진입점 — CLI 파싱, 로깅, 앱 실행
├── web_app.py                 # Flask 앱 팩토리 + 전체 API 라우트
├── requirements.txt           # 의존성 패키지 목록
├── config.json                # 실제 설정 파일 (Git 제외, .gitignore)
├── config.example.json        # 설정 파일 예시 (민감정보 없음)
├── config.template.json       # 자동 생성용 기본 템플릿
│
├── core/                      # 핵심 비즈니스 로직
│   ├── __init__.py
│   ├── api_client.py          # 네이버 검색광고 API 클라이언트
│   ├── config_manager.py      # 설정 데이터클래스 + 파일 로드/저장
│   ├── email_sender.py        # SMTP 이메일 발송 (네이버 메일)
│   ├── report_generator.py    # 네이버 검색광고 보고서 데이터 생성
│   ├── scheduler.py           # APScheduler 작업 등록 및 실행
│   ├── signature.py           # HMAC-SHA256 API 서명 생성
│   ├── coupang_scraper.py     # 쿠팡 광고 Selenium 스크래퍼
│   ├── coupang_report.py      # 쿠팡 보고서 데이터 가공 및 이메일 생성
│   ├── gfa_scraper.py         # 네이버 GFA Selenium 스크래퍼
│   └── gfa_report.py          # GFA 보고서 데이터 가공 및 이메일 생성
│
├── templates/                 # Jinja2 HTML 이메일 + 웹 대시보드 템플릿
│   ├── dashboard.html         # 웹 대시보드 메인 페이지
│   ├── report_email.html      # 네이버 검색광고 이메일 보고서
│   ├── alert_email.html       # 예산 초과 알림 이메일
│   ├── coupang_report_email.html  # 쿠팡 광고 이메일 보고서
│   └── gfa_report_email.html  # GFA 이메일 보고서
│
├── downloads/                 # 스크래퍼 다운로드 및 디버그 파일
│   ├── coupang/
│   │   └── debug/             # 쿠팡 디버그 스크린샷 + HTML
│   └── gfa/
│       └── debug/             # GFA 디버그 스크린샷 + HTML
│
├── logs/
│   ├── naver_ads_bot.log      # 메인 앱 로그
│   └── server.log             # 웹 서버 로그
│
├── 광고자동화_실행.bat          # Windows 실행 스크립트 (더블클릭 실행)
├── 광고자동화_시작.vbs          # 백그라운드 실행용 VBS 스크립트
├── start-server.bat           # 서버 시작 배치 파일
├── start-server.vbs           # 서버 시작 VBS 스크립트
└── 배포용_압축.bat             # 배포 ZIP 패키징 스크립트
```

---

## ⚙️ 설정 파일 구조 (`config.json`)

```json
{
  "accounts": [
    {
      "name": "계정명",
      "customer_id": "네이버 광고 고객번호",
      "api_key": "API 액세스 라이선스",
      "secret_key": "API 시크릿 키",
      "report_recipients": ["수신자@email.com"]
    }
  ],
  "coupang_accounts": [
    {
      "name": "쿠팡 광고",
      "wing_id": "쿠팡 Wing ID",
      "wing_password": "비밀번호",
      "report_recipients": ["수신자@email.com"],
      "headless": true
    }
  ],
  "gfa_accounts": [
    {
      "name": "네이버 GFA",
      "naver_id": "네이버 로그인 ID",
      "naver_password": "네이버 비밀번호",
      "ad_account_id": "광고주센터 계정 고유번호",
      "report_recipients": ["수신자@email.com"],
      "headless": false
    }
  ],
  "email": {
    "sender_email": "발신자@naver.com",
    "app_password": "네이버 메일 앱 비밀번호"
  },
  "schedule": {
    "report_time": "09:00"
  },
  "alert": {
    "enabled": true,
    "daily_spend_threshold": 50000
  },
  "server_url": "http://192.168.x.x:5000"
}
```

---

## 🚀 실행 방법

```bash
# 의존성 설치
pip install -r requirements.txt

# 웹 대시보드 + 자동 스케줄러 (기본)
python main.py

# 포트 변경
python main.py --port 8080

# 보고서 즉시 발송
python main.py --run-now

# 예산 알림 즉시 체크
python main.py --check-alert

# API / SMTP 연결 검증
python main.py --validate
```

---

## 🌐 웹 대시보드 API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/` | 메인 대시보드 |
| GET | `/api/accounts` | 계정 목록 조회 |
| POST | `/api/accounts` | 계정 추가 |
| PUT | `/api/accounts/<idx>` | 계정 수정 |
| DELETE | `/api/accounts/<idx>` | 계정 삭제 |
| GET | `/api/campaigns/<idx>` | 캠페인 목록 조회 |
| POST | `/api/campaigns/<idx>/<cid>/toggle` | 캠페인 ON/OFF |
| GET | `/api/config` | 전체 설정 조회 |
| POST | `/api/config` | 설정 저장 |
| POST | `/api/run-report` | 보고서 즉시 실행 |
| POST | `/api/run-alert` | 알림 즉시 체크 |
| GET | `/api/status` | 스케줄러 상태 |

---

## 🔧 의존성 패키지

| 패키지 | 용도 |
|--------|------|
| `Flask` | 웹 대시보드 서버 |
| `APScheduler` | 스케줄 작업 관리 |
| `requests` | 네이버 API HTTP 클라이언트 |
| `Selenium` | 쿠팡/GFA 브라우저 자동화 |
| `webdriver-manager` | ChromeDriver 자동 설치 |
| `openpyxl` | 쿠팡 엑셀 보고서 파싱 |
| `Jinja2` | HTML 이메일 템플릿 렌더링 |

---

## ⚠️ 주의 사항

- `config.json`은 민감정보 포함 → `.gitignore`에 등록됨
- GFA 스크래퍼는 네이버 2단계 인증 발생 시 수동 개입 필요 (`headless: false` 권장)
- 쿠팡 스크래퍼는 `headless: true`로 운영 가능
- 네이버 메일 발신 시 앱 비밀번호(일반 비밀번호 X) 사용 필수
- `downloads/` 폴더는 디버그용 → 용량 커질 경우 주기적 삭제 필요
- `logs/` 폴더 로그는 자동 누적 → 운영 환경에서 로테이션 고려

---

## 🗂️ 핵심 데이터 모델 (`core/config_manager.py`)

| 클래스 | 설명 |
|--------|------|
| `AdAccount` | 네이버 검색광고 계정 |
| `CoupangAccount` | 쿠팡 광고 계정 |
| `GfaAccount` | 네이버 GFA 계정 |
| `EmailConfig` | 이메일 발신 설정 |
| `ScheduleConfig` | 보고서 발송 시각 설정 |
| `AlertConfig` | 예산 알림 설정 |
| `AppConfig` | 전체 앱 설정 통합 |
