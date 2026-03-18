import json
import logging
import time
from datetime import datetime, timedelta

import requests

from core.signature import generate_signature, get_timestamp

logger = logging.getLogger(__name__)

# 기본 지표 (캠페인/그룹 단위)
STAT_FIELDS = ["impCnt", "clkCnt", "ctr", "cpc", "salesAmt", "ccnt", "crto"]

# 확장 지표 (ROAS, 전환매출, 전환당비용, 광고순위 포함)
STAT_FIELDS_FULL = [
    "impCnt", "clkCnt", "ctr", "cpc", "salesAmt",
    "ccnt", "crto", "convAmt", "ror", "cpConv",
    "avgRnk", "pcNxAvgRnk", "mblNxAvgRnk",
]

# 지역코드 → 한글 매핑
REGION_CODE_MAP = {
    "01": "서울", "02": "인천", "03": "경기",
    "04": "강원", "05": "대전", "06": "세종",
    "07": "충남", "08": "충북", "09": "부산",
    "10": "울산", "11": "경남", "12": "경북",
    "13": "대구", "14": "전남", "15": "전북",
    "16": "광주", "17": "제주",
}

# 요일코드 → 한글 매핑
DAY_OF_WEEK_MAP = {
    "1": "월", "2": "화", "3": "수", "4": "목",
    "5": "금", "6": "토", "7": "일",
}


class NaverAdsAPIClient:
    BASE_URL = "https://api.naver.com"

    def __init__(self, customer_id: str, api_key: str, secret_key: str):
        self.customer_id = customer_id
        self.api_key = api_key
        self.secret_key = secret_key
        self.session = requests.Session()

    def _build_headers(self, method: str, uri: str) -> dict:
        timestamp = get_timestamp()
        signature = generate_signature(timestamp, method, uri, self.secret_key)
        return {
            "Content-Type": "application/json; charset=UTF-8",
            "X-Timestamp": timestamp,
            "X-API-KEY": self.api_key,
            "X-Customer": str(self.customer_id),
            "X-Signature": signature,
        }

    def _request(self, method: str, uri: str, params: dict = None,
                 body: dict = None, max_retries: int = 3) -> any:
        url = f"{self.BASE_URL}{uri}"
        headers = self._build_headers(method, uri)

        for attempt in range(max_retries):
            try:
                resp = self.session.request(
                    method, url, headers=headers,
                    params=params, json=body, timeout=30,
                )

                if resp.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning(f"Rate limited, {wait}초 대기 후 재시도 ({attempt + 1}/{max_retries})")
                    time.sleep(wait)
                    headers = self._build_headers(method, uri)
                    continue

                resp.raise_for_status()
                if resp.content:
                    return resp.json()
                return None

            except requests.exceptions.HTTPError as e:
                logger.error(f"API 오류 [{resp.status_code}]: {resp.text}")
                if attempt < max_retries - 1 and resp.status_code >= 500:
                    time.sleep(2 ** attempt)
                    headers = self._build_headers(method, uri)
                    continue
                raise
            except requests.exceptions.RequestException as e:
                logger.error(f"네트워크 오류: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    headers = self._build_headers(method, uri)
                    continue
                raise

    def get_campaigns(self) -> list[dict]:
        uri = "/ncc/campaigns"
        return self._request("GET", uri)

    def get_adgroups(self, campaign_id: str) -> list[dict]:
        uri = "/ncc/adgroups"
        return self._request("GET", uri, params={"nccCampaignId": campaign_id})

    def get_keywords(self, adgroup_id: str) -> list[dict]:
        """광고그룹의 키워드 목록 조회."""
        uri = "/ncc/keywords"
        return self._request("GET", uri, params={"nccAdgroupId": adgroup_id})

    def get_bizmoney_balance(self) -> dict:
        """비즈머니 잔액 조회."""
        uri = "/billing/bizmoney"
        return self._request("GET", uri)

    def update_campaign(self, campaign_id: str, fields: dict) -> dict:
        """
        캠페인 상태 업데이트.

        Args:
            campaign_id: 캠페인 ID (nccCampaignId)
            fields: 업데이트할 필드 (예: {"userLock": True} 로 일시중지)
        """
        uri = f"/ncc/campaigns/{campaign_id}"
        body = {"nccCampaignId": campaign_id, **fields}
        # 네이버 API는 fields 파라미터로 업데이트할 필드명을 지정해야 함
        field_names = ",".join(fields.keys())
        return self._request("PUT", uri, params={"fields": field_names}, body=body)

    def pause_campaign(self, campaign_id: str) -> dict:
        """캠페인 일시중지 (userLock=True)."""
        logger.info(f"캠페인 일시중지: {campaign_id}")
        return self.update_campaign(campaign_id, {"userLock": True})

    def resume_campaign(self, campaign_id: str) -> dict:
        """캠페인 재개 (userLock=False)."""
        logger.info(f"캠페인 재개: {campaign_id}")
        return self.update_campaign(campaign_id, {"userLock": False})

    def update_adgroup(self, adgroup_id: str, fields: dict) -> dict:
        """광고그룹 상태 업데이트."""
        uri = f"/ncc/adgroups/{adgroup_id}"
        body = {"nccAdgroupId": adgroup_id, **fields}
        field_names = ",".join(fields.keys())
        return self._request("PUT", uri, params={"fields": field_names}, body=body)

    def pause_adgroup(self, adgroup_id: str) -> dict:
        """광고그룹 일시중지 (userLock=True)."""
        logger.info(f"광고그룹 일시중지: {adgroup_id}")
        return self.update_adgroup(adgroup_id, {"userLock": True})

    def resume_adgroup(self, adgroup_id: str) -> dict:
        """광고그룹 재개 (userLock=False)."""
        logger.info(f"광고그룹 재개: {adgroup_id}")
        return self.update_adgroup(adgroup_id, {"userLock": False})

    def get_stats(self, ids: list[str], fields: list[str], since: str, until: str) -> list[dict]:
        """
        통계 데이터 조회.

        Args:
            ids: 캠페인/광고그룹/키워드 ID 리스트
            fields: 조회할 지표 리스트
            since: 시작일 (YYYY-MM-DD)
            until: 종료일 (YYYY-MM-DD)
        """
        uri = "/stats"
        params = {
            "ids": ids,
            "fields": json.dumps(fields),
            "timeRange": json.dumps({"since": since, "until": until}),
        }
        result = self._request("GET", uri, params=params)
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return result

    def get_stats_with_breakdown(
        self, ids: list[str], fields: list[str],
        since: str, until: str, breakdown: str,
    ) -> list[dict]:
        """
        Breakdown 차원이 포함된 통계 조회.

        Args:
            ids: entity ID 리스트
            fields: 지표 리스트
            since/until: 날짜 범위 (YYYY-MM-DD)
            breakdown: pcMblTp | hh24 | dayw | regnNo
        Note: breakdown은 파워링크/쇼핑에서 7일 윈도우 제한이 있음
        """
        all_data = []
        # 7일 윈도우 제한 대응: 자동 분할
        for chunk_since, chunk_until in self._split_date_range(since, until, max_days=7):
            uri = "/stats"
            params = {
                "ids": ids,
                "fields": json.dumps(fields),
                "timeRange": json.dumps({"since": chunk_since, "until": chunk_until}),
                "breakdown": breakdown,
            }
            result = self._request("GET", uri, params=params)
            if isinstance(result, dict) and "data" in result:
                all_data.extend(result["data"])
            elif isinstance(result, list):
                all_data.extend(result)
        return all_data

    @staticmethod
    def _split_date_range(since: str, until: str, max_days: int = 7):
        """날짜 범위를 max_days 단위로 분할하여 yield."""
        start = datetime.strptime(since, "%Y-%m-%d").date()
        end = datetime.strptime(until, "%Y-%m-%d").date()
        while start <= end:
            chunk_end = min(start + timedelta(days=max_days - 1), end)
            yield start.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")
            start = chunk_end + timedelta(days=1)

    # ── StatReport API (비동기 대량 보고서) ──

    def create_stat_report(self, report_type: str, stat_date: str) -> dict:
        """
        StatReport 생성 요청.

        Args:
            report_type: 보고서 유형 (AD, AD_CONVERSION, EXPKEYWORD 등)
            stat_date: 통계 날짜 (YYYY-MM-DD)
        """
        uri = "/stat-reports"
        body = {"reportTp": report_type, "statDt": stat_date}
        return self._request("POST", uri, body=body)

    def get_stat_report_status(self, report_job_id: str) -> dict:
        """StatReport 상태 조회."""
        uri = f"/stat-reports/{report_job_id}"
        return self._request("GET", uri)

    def _download_from_url(self, download_url: str) -> str:
        """downloadUrl에서 TSV 데이터 다운로드 (인증 헤더 포함)."""
        uri = "/report-download"
        headers = self._build_headers("GET", uri)
        resp = self.session.get(download_url, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.text

    def delete_stat_report(self, report_job_id: str) -> None:
        """StatReport 삭제."""
        uri = f"/stat-reports/{report_job_id}"
        self._request("DELETE", uri)

    def wait_and_download_stat_report(self, report_type: str, stat_date: str,
                                       poll_interval: int = 3, max_wait: int = 120) -> str:
        """
        StatReport 생성 → 완료 대기 → TSV 다운로드를 한번에 처리.

        Returns:
            TSV 텍스트 데이터
        """
        result = self.create_stat_report(report_type, stat_date)
        job_id = result.get("reportJobId")
        if not job_id:
            raise RuntimeError(f"StatReport 생성 실패: {result}")

        logger.info(f"StatReport 생성: type={report_type}, date={stat_date}, jobId={job_id}")

        elapsed = 0
        while elapsed < max_wait:
            status = self.get_stat_report_status(job_id)
            state = status.get("status")
            if state == "BUILT":
                logger.info(f"StatReport 완료: {job_id}")
                download_url = status.get("downloadUrl", "")
                if download_url:
                    tsv = self._download_from_url(download_url)
                else:
                    raise RuntimeError(f"downloadUrl이 없습니다: {status}")
                self.delete_stat_report(job_id)
                return tsv
            elif state in ("REGIST", "RUNNING"):
                time.sleep(poll_interval)
                elapsed += poll_interval
            else:
                raise RuntimeError(f"StatReport 실패 (status={state}): {status}")

        raise TimeoutError(f"StatReport 시간 초과 ({max_wait}초): {job_id}")
