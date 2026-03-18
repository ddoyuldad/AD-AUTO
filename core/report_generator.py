import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from core.api_client import (
    NaverAdsAPIClient, STAT_FIELDS_FULL,
    REGION_CODE_MAP, DAY_OF_WEEK_MAP,
)

logger = logging.getLogger(__name__)


def _safe_num(val, default=0):
    """API 응답에서 안전하게 숫자 추출 (dict/None 방어)"""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        try:
            return float(val) if '.' in val else int(val)
        except ValueError:
            return default
    return default


# ═══════════════════════════════════════════════════════
#  데이터 모델
# ═══════════════════════════════════════════════════════

@dataclass
class KeywordStats:
    keyword: str
    keyword_id: str
    adgroup_name: str
    campaign_name: str
    source: str = ""  # "powerlink" or "shopping"
    impressions: int = 0
    clicks: int = 0
    ctr: float = 0.0
    cpc: float = 0.0
    cost: float = 0.0
    conversions: int = 0
    conversion_rate: float = 0.0
    conv_revenue: float = 0.0
    roas: float = 0.0
    cost_per_conv: float = 0.0
    # 순위
    avg_rank: float = 0.0
    pc_avg_rank: float = 0.0
    mobile_avg_rank: float = 0.0
    # 메타데이터
    bid_amt: int = 0
    quality_index: int = 0


@dataclass
class AdGroupStats:
    adgroup_id: str
    adgroup_name: str
    campaign_name: str
    impressions: int = 0
    clicks: int = 0
    ctr: float = 0.0
    cpc: float = 0.0
    cost: float = 0.0
    conversions: int = 0
    conversion_rate: float = 0.0
    conv_revenue: float = 0.0
    roas: float = 0.0
    cost_per_conv: float = 0.0
    # 순위
    avg_rank: float = 0.0
    pc_avg_rank: float = 0.0
    mobile_avg_rank: float = 0.0
    # 메타데이터
    bid_amt: int = 0
    daily_budget: int = 0
    status: str = ""


@dataclass
class CampaignStats:
    campaign_id: str
    campaign_name: str
    campaign_type: str = ""
    impressions: int = 0
    clicks: int = 0
    ctr: float = 0.0
    cpc: float = 0.0
    cost: float = 0.0
    conversions: int = 0
    conversion_rate: float = 0.0
    conv_revenue: float = 0.0
    roas: float = 0.0
    cost_per_conv: float = 0.0
    # 순위
    avg_rank: float = 0.0
    # 메타데이터
    daily_budget: int = 0
    status: str = ""


@dataclass
class DeviceBreakdown:
    """PC vs 모바일 분리 통계"""
    pc_impressions: int = 0
    pc_clicks: int = 0
    pc_cost: float = 0.0
    pc_conversions: int = 0
    pc_conv_revenue: float = 0.0
    pc_ctr: float = 0.0
    pc_roas: float = 0.0
    mobile_impressions: int = 0
    mobile_clicks: int = 0
    mobile_cost: float = 0.0
    mobile_conversions: int = 0
    mobile_conv_revenue: float = 0.0
    mobile_ctr: float = 0.0
    mobile_roas: float = 0.0


@dataclass
class HourlyBucket:
    """시간대별 성과 (0~23시)"""
    hour: int = 0
    impressions: int = 0
    clicks: int = 0
    cost: float = 0.0
    conversions: int = 0
    conv_revenue: float = 0.0


@dataclass
class DayOfWeekBucket:
    """요일별 성과 (월~일)"""
    day: int = 0  # 1=월 ~ 7=일
    day_name: str = ""
    impressions: int = 0
    clicks: int = 0
    cost: float = 0.0
    conversions: int = 0
    conv_revenue: float = 0.0


@dataclass
class RegionBucket:
    """지역별 성과"""
    region_code: str = ""
    region_name: str = ""
    impressions: int = 0
    clicks: int = 0
    cost: float = 0.0
    conversions: int = 0
    conv_revenue: float = 0.0
    ctr: float = 0.0


@dataclass
class SearchTermStats:
    """실제 검색어 (EXPKEYWORD 보고서)"""
    search_term: str = ""
    keyword: str = ""
    campaign_name: str = ""
    adgroup_name: str = ""
    impressions: int = 0
    clicks: int = 0
    ctr: float = 0.0
    cost: float = 0.0
    conversions: int = 0
    conv_revenue: float = 0.0


@dataclass
class ConversionDetailBucket:
    """전환 유형별 상세"""
    conversion_type: str = ""
    direct_conversions: int = 0
    indirect_conversions: int = 0
    total_conversions: int = 0
    direct_revenue: float = 0.0
    indirect_revenue: float = 0.0
    total_revenue: float = 0.0


@dataclass
class AccountReport:
    account_name: str
    customer_id: str
    report_date: date
    date_from: date = None
    date_to: date = None
    campaigns: list[CampaignStats] = field(default_factory=list)
    adgroups: list[AdGroupStats] = field(default_factory=list)
    keywords: list[KeywordStats] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    total_cost: float = 0.0
    total_clicks: int = 0
    total_impressions: int = 0
    total_conversions: int = 0
    total_conv_revenue: float = 0.0
    total_roas: float = 0.0
    # 새 데이터
    device_breakdown: DeviceBreakdown = field(default_factory=DeviceBreakdown)
    hourly_stats: list[HourlyBucket] = field(default_factory=list)
    day_of_week_stats: list[DayOfWeekBucket] = field(default_factory=list)
    region_stats: list[RegionBucket] = field(default_factory=list)
    search_terms: list[SearchTermStats] = field(default_factory=list)
    conversion_details: list[ConversionDetailBucket] = field(default_factory=list)
    bizmoney_balance: float = 0.0


# 캠페인 유형 → 한글 매핑
CAMPAIGN_TYPE_MAP = {
    "WEB_SITE": "파워링크",
    "SHOPPING": "쇼핑검색",
    "POWER_CONTENTS": "파워컨텐츠",
    "BRAND_SEARCH": "브랜드검색",
    "PLACE": "플레이스",
    "CATALOG": "카탈로그",
}

# 전환 유형 코드 → 한글 매핑
CONVERSION_TYPE_MAP = {
    "purchase": "구매",
    "sign_up": "회원가입",
    "complete_registration": "회원가입",
    "cart": "장바구니",
    "add_to_cart": "장바구니",
    "apply": "신청/예약",
    "schedule": "신청/예약",
    "app_install": "앱설치",
    "begin_checkout": "결제시작",
    "lead": "잠재고객",
    "page_view": "페이지뷰",
    "start_trial": "체험시작",
    "subscribe": "구독",
    "add_payment_info": "결제정보등록",
    "etc": "기타",
    "other": "기타",
    "1": "구매",
    "2": "회원가입",
    "3": "장바구니",
    "4": "신청/예약",
    "5": "앱설치",
    "6": "기타",
}

# 캠페인 상태 코드 → 한글 매핑
STATUS_MAP = {
    "ELIGIBLE": "활성",
    "PAUSED": "일시중지",
    "SUSPENDED": "중지됨",
    "PENDING": "대기중",
    "OFF": "종료",
}


class ReportGenerator:
    def __init__(self, client: NaverAdsAPIClient):
        self.client = client

    # ═══════════════════════════════════════════════════════
    #  메인 보고서 생성
    # ═══════════════════════════════════════════════════════

    def generate_report(self, date_from: date = None, date_to: date = None) -> AccountReport:
        """캠페인 + 광고그룹 + 키워드 + breakdown + 검색어 + 전환상세 보고서 생성"""
        start_time = time.time()

        if date_from is None:
            date_from = date.today() - timedelta(days=1)
        if date_to is None:
            date_to = date_from

        since_str = date_from.strftime("%Y-%m-%d")
        until_str = date_to.strftime("%Y-%m-%d")

        campaigns = self.client.get_campaigns()
        if not campaigns:
            logger.warning("캠페인이 없습니다")
            return AccountReport(
                account_name="",
                customer_id=self.client.customer_id,
                report_date=date_from,
                date_from=date_from,
                date_to=date_to,
            )

        campaign_map = {c["nccCampaignId"]: c.get("name", "이름없음") for c in campaigns}
        campaign_type_map = {c["nccCampaignId"]: c.get("campaignTp", "") for c in campaigns}
        campaign_ids = list(campaign_map.keys())

        # ── 캠페인 통계 ──
        stats_data = self.client.get_stats(
            ids=campaign_ids,
            fields=STAT_FIELDS_FULL,
            since=since_str,
            until=until_str,
        )

        stats_by_id = {}
        if stats_data:
            for item in stats_data:
                cid = item.get("id")
                if cid:
                    stats_by_id[cid] = item

        campaign_stats_list = []
        total_cost = 0.0
        total_clicks = 0
        total_impressions = 0
        total_conversions = 0
        total_conv_revenue = 0.0

        for cid, cname in campaign_map.items():
            stat = stats_by_id.get(cid, {})
            type_code = campaign_type_map.get(cid, "")
            raw_campaign = next((c for c in campaigns if c["nccCampaignId"] == cid), {})
            cs = CampaignStats(
                campaign_id=cid,
                campaign_name=cname,
                campaign_type=CAMPAIGN_TYPE_MAP.get(type_code, ""),
                impressions=_safe_num(stat.get("impCnt")),
                clicks=_safe_num(stat.get("clkCnt")),
                ctr=_safe_num(stat.get("ctr")),
                cpc=_safe_num(stat.get("cpc")),
                cost=_safe_num(stat.get("salesAmt")),
                conversions=_safe_num(stat.get("ccnt")),
                conversion_rate=_safe_num(stat.get("crto")),
                conv_revenue=_safe_num(stat.get("convAmt")),
                roas=_safe_num(stat.get("ror")),
                cost_per_conv=_safe_num(stat.get("cpConv")),
                avg_rank=_safe_num(stat.get("avgRnk")),
                daily_budget=_safe_num(raw_campaign.get("dailyBudget")),
                status=raw_campaign.get("status", "") or "",
            )
            campaign_stats_list.append(cs)
            total_cost += cs.cost
            total_clicks += cs.clicks
            total_impressions += cs.impressions
            total_conversions += cs.conversions
            total_conv_revenue += cs.conv_revenue

        campaign_stats_list.sort(key=lambda x: x.cost, reverse=True)

        # ── 광고그룹 + 파워링크 키워드 통계 ──
        all_adgroups = []
        powerlink_keywords = []
        try:
            all_adgroups, powerlink_keywords = self._collect_adgroup_and_keyword_stats(
                campaigns, campaign_map, since_str, until_str
            )
        except Exception as e:
            logger.error(f"광고그룹/키워드 통계 수집 실패: {e}", exc_info=True)

        # ── 쇼핑검색 키워드 (StatReport TSV) ──
        shopping_keywords = []
        if date_from == date_to:
            try:
                shopping_keywords = self._collect_shopping_keywords(
                    date_from, campaign_map, campaign_type_map
                )
            except Exception as e:
                logger.warning(f"쇼핑 키워드 수집 실패: {e}")

        # 파워링크 + 쇼핑 키워드 합치기
        all_keywords = powerlink_keywords + shopping_keywords
        all_keywords.sort(key=lambda x: x.cost, reverse=True)

        total_roas = 0.0
        if total_cost > 0:
            total_roas = (total_conv_revenue / total_cost) * 100

        report = AccountReport(
            account_name="",
            customer_id=self.client.customer_id,
            report_date=date_from,
            date_from=date_from,
            date_to=date_to,
            campaigns=campaign_stats_list,
            adgroups=all_adgroups,
            keywords=all_keywords,
            total_cost=total_cost,
            total_clicks=total_clicks,
            total_impressions=total_impressions,
            total_conversions=total_conversions,
            total_conv_revenue=total_conv_revenue,
            total_roas=total_roas,
        )

        # ── 디바이스 분석 (PC vs 모바일) ──
        try:
            report.device_breakdown = self._collect_device_breakdown(
                campaign_ids, since_str, until_str
            )
        except Exception as e:
            logger.warning(f"디바이스 breakdown 수집 실패: {e}")

        time.sleep(0.3)

        # ── 시간대별 분석 ──
        try:
            report.hourly_stats = self._collect_hourly_stats(
                campaign_ids, since_str, until_str
            )
        except Exception as e:
            logger.warning(f"시간대별 stats 수집 실패: {e}")

        time.sleep(0.3)

        # ── 요일별 분석 ──
        try:
            report.day_of_week_stats = self._collect_day_of_week_stats(
                campaign_ids, since_str, until_str
            )
        except Exception as e:
            logger.warning(f"요일별 stats 수집 실패: {e}")

        time.sleep(0.3)

        # ── 지역별 분석 ──
        try:
            report.region_stats = self._collect_region_stats(
                campaign_ids, since_str, until_str
            )
        except Exception as e:
            logger.warning(f"지역별 stats 수집 실패: {e}")

        # ── 실제 검색어 (EXPKEYWORD) ── 단일일자만
        if date_from == date_to:
            try:
                report.search_terms = self._collect_search_terms(
                    date_from, campaign_map
                )
            except Exception as e:
                logger.warning(f"검색어 수집 실패: {e}")

            # ── 쇼핑 키워드 전환 보완 ──
            try:
                self._fill_shopping_conversions(date_from, report.keywords)
            except Exception as e:
                logger.warning(f"쇼핑 키워드 전환 수집 실패: {e}")

            # ── 전환 상세 ──
            try:
                report.conversion_details = self._collect_conversion_details(date_from)
            except Exception as e:
                logger.warning(f"전환 상세 수집 실패: {e}")

        # ── 비즈머니 잔액 ──
        try:
            biz = self.client.get_bizmoney_balance()
            if isinstance(biz, dict):
                val = biz.get("bizmoney", biz.get("balance", 0))
                report.bizmoney_balance = _safe_num(val)
            elif isinstance(biz, (int, float)):
                report.bizmoney_balance = biz
            else:
                report.bizmoney_balance = 0
        except Exception as e:
            logger.warning(f"비즈머니 조회 실패: {e}")

        # ── 인사이트 생성 ──
        report.insights = self._generate_insights(report)

        elapsed = time.time() - start_time
        logger.info(f"보고서 생성 완료: {elapsed:.1f}초 소요")

        return report

    # ═══════════════════════════════════════════════════════
    #  디바이스 분석 (PC vs Mobile)
    # ═══════════════════════════════════════════════════════

    def _collect_device_breakdown(
        self, campaign_ids: list[str], since: str, until: str
    ) -> DeviceBreakdown:
        """PC / 모바일 분리 통계 수집"""
        fields = ["impCnt", "clkCnt", "salesAmt", "ccnt", "convAmt"]
        data = self.client.get_stats_with_breakdown(
            ids=campaign_ids, fields=fields,
            since=since, until=until, breakdown="pcMblTp",
        )

        db = DeviceBreakdown()
        if not data:
            return db

        device_names_found = set()

        def _add_to_device(device_raw: str, imp, clk, cost, conv, rev):
            device = device_raw.strip().upper()
            device_names_found.add(f"{device_raw}({device})")

            if device in ("PC",):
                db.pc_impressions += imp
                db.pc_clicks += clk
                db.pc_cost += cost
                db.pc_conversions += conv
                db.pc_conv_revenue += rev
            elif device in ("MBL", "MOBILE", "M") or "모바일" in device_raw or "모바일" in device:
                db.mobile_impressions += imp
                db.mobile_clicks += clk
                db.mobile_cost += cost
                db.mobile_conversions += conv
                db.mobile_conv_revenue += rev
            else:
                # 알 수 없는 유형은 로깅
                logger.warning(f"[디바이스] 알 수 없는 디바이스 유형: '{device_raw}' - 무시")

        for item in data:
            # breakdown 데이터는 item["breakdowns"] 안에 있음
            breakdowns = item.get("breakdowns", [])
            if breakdowns:
                for bd in breakdowns:
                    _add_to_device(
                        str(bd.get("name", "")),
                        _safe_num(bd.get("impCnt")),
                        _safe_num(bd.get("clkCnt")),
                        _safe_num(bd.get("salesAmt")),
                        _safe_num(bd.get("ccnt")),
                        _safe_num(bd.get("convAmt")),
                    )
            else:
                # 이전 API 형식 호환 (flat 구조)
                _add_to_device(
                    str(item.get("pcMblTp", "")),
                    _safe_num(item.get("impCnt")),
                    _safe_num(item.get("clkCnt")),
                    _safe_num(item.get("salesAmt")),
                    _safe_num(item.get("ccnt")),
                    _safe_num(item.get("convAmt")),
                )

        logger.info(f"[디바이스] 발견된 디바이스 유형: {device_names_found}")
        logger.info(
            f"[디바이스] PC: 비용={db.pc_cost:,.0f}원, 클릭={db.pc_clicks:,}, "
            f"노출={db.pc_impressions:,}, 전환={db.pc_conversions}, 전환매출={db.pc_conv_revenue:,.0f}원"
        )
        logger.info(
            f"[디바이스] Mobile: 비용={db.mobile_cost:,.0f}원, 클릭={db.mobile_clicks:,}, "
            f"노출={db.mobile_impressions:,}, 전환={db.mobile_conversions}, 전환매출={db.mobile_conv_revenue:,.0f}원"
        )

        # CTR / ROAS 계산
        if db.pc_impressions > 0:
            db.pc_ctr = db.pc_clicks / db.pc_impressions * 100
        if db.pc_cost > 0:
            db.pc_roas = db.pc_conv_revenue / db.pc_cost * 100
        if db.mobile_impressions > 0:
            db.mobile_ctr = db.mobile_clicks / db.mobile_impressions * 100
        if db.mobile_cost > 0:
            db.mobile_roas = db.mobile_conv_revenue / db.mobile_cost * 100

        total_dev_cost = db.pc_cost + db.mobile_cost
        if total_dev_cost > 0:
            pc_pct = db.pc_cost / total_dev_cost * 100
            mob_pct = db.mobile_cost / total_dev_cost * 100
            logger.info(f"[디바이스] 비율: PC {pc_pct:.1f}% / Mobile {mob_pct:.1f}%")

        return db

    # ═══════════════════════════════════════════════════════
    #  시간대별 분석 (24시간)
    # ═══════════════════════════════════════════════════════

    def _collect_hourly_stats(
        self, campaign_ids: list[str], since: str, until: str
    ) -> list[HourlyBucket]:
        """24시간 시간대별 통계 수집"""
        fields = ["impCnt", "clkCnt", "salesAmt", "ccnt", "convAmt"]
        data = self.client.get_stats_with_breakdown(
            ids=campaign_ids, fields=fields,
            since=since, until=until, breakdown="hh24",
        )

        hourly = defaultdict(lambda: {"imp": 0, "clk": 0, "cost": 0.0, "conv": 0, "rev": 0.0})
        if data:
            for item in data:
                # breakdown 데이터는 item["breakdowns"] 안에 있음
                breakdowns = item.get("breakdowns", [])
                if breakdowns:
                    for bd in breakdowns:
                        # name 형식: "00시~01시", "13시~14시" 등
                        name = str(bd.get("name", ""))
                        h = self._parse_hour_from_name(name)
                        hourly[h]["imp"] += _safe_num(bd.get("impCnt"))
                        hourly[h]["clk"] += _safe_num(bd.get("clkCnt"))
                        hourly[h]["cost"] += _safe_num(bd.get("salesAmt"))
                        hourly[h]["conv"] += _safe_num(bd.get("ccnt"))
                        hourly[h]["rev"] += _safe_num(bd.get("convAmt"))
                else:
                    h = int(_safe_num(item.get("hh24", 0)))
                    hourly[h]["imp"] += _safe_num(item.get("impCnt"))
                    hourly[h]["clk"] += _safe_num(item.get("clkCnt"))
                    hourly[h]["cost"] += _safe_num(item.get("salesAmt"))
                    hourly[h]["conv"] += _safe_num(item.get("ccnt"))
                    hourly[h]["rev"] += _safe_num(item.get("convAmt"))

        results = []
        for h in range(24):
            d = hourly[h]
            results.append(HourlyBucket(
                hour=h,
                impressions=d["imp"],
                clicks=d["clk"],
                cost=d["cost"],
                conversions=d["conv"],
                conv_revenue=d["rev"],
            ))
        return results

    @staticmethod
    def _parse_hour_from_name(name: str) -> int:
        """시간대 이름에서 시간 추출: '00시~01시' → 0, '13시~14시' → 13"""
        m = re.match(r'(\d{1,2})시', name)
        if m:
            return int(m.group(1))
        # 숫자만 있는 경우
        m = re.match(r'(\d{1,2})', name)
        if m:
            return int(m.group(1))
        return 0

    # ═══════════════════════════════════════════════════════
    #  요일별 분석 (월~일)
    # ═══════════════════════════════════════════════════════

    def _collect_day_of_week_stats(
        self, campaign_ids: list[str], since: str, until: str
    ) -> list[DayOfWeekBucket]:
        """요일별 통계 수집 (최소 7일 범위로 확장하여 모든 요일 데이터 확보)"""
        # 요일별 분석은 최소 7일 범위여야 모든 요일에 데이터가 있음
        since_dt = date.fromisoformat(since)
        until_dt = date.fromisoformat(until)
        range_days = (until_dt - since_dt).days + 1
        if range_days < 7:
            since_dt = until_dt - timedelta(days=6)
            since = since_dt.strftime("%Y-%m-%d")
            logger.info(f"[요일별] 날짜 범위를 7일로 확장: {since} ~ {until}")

        fields = ["impCnt", "clkCnt", "salesAmt", "ccnt", "convAmt"]
        data = self.client.get_stats_with_breakdown(
            ids=campaign_ids, fields=fields,
            since=since, until=until, breakdown="dayw",
        )

        # 요일 이름 → 순번 매핑 (API는 "월요일", "화요일" 등 풀네임 반환)
        day_name_order = {
            "월요일": 1, "화요일": 2, "수요일": 3, "목요일": 4,
            "금요일": 5, "토요일": 6, "일요일": 7,
            # 약칭 호환
            "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
        }
        day_short_name = {
            "월요일": "월", "화요일": "화", "수요일": "수", "목요일": "목",
            "금요일": "금", "토요일": "토", "일요일": "일",
        }

        daily = defaultdict(lambda: {"imp": 0, "clk": 0, "cost": 0.0, "conv": 0, "rev": 0.0})
        if data:
            for item in data:
                # breakdown 데이터는 item["breakdowns"] 안에 있음
                breakdowns = item.get("breakdowns", [])
                if breakdowns:
                    for bd in breakdowns:
                        d = str(bd.get("name", ""))
                        daily[d]["imp"] += _safe_num(bd.get("impCnt"))
                        daily[d]["clk"] += _safe_num(bd.get("clkCnt"))
                        daily[d]["cost"] += _safe_num(bd.get("salesAmt"))
                        daily[d]["conv"] += _safe_num(bd.get("ccnt"))
                        daily[d]["rev"] += _safe_num(bd.get("convAmt"))
                else:
                    d = str(item.get("dayw", ""))
                    daily[d]["imp"] += _safe_num(item.get("impCnt"))
                    daily[d]["clk"] += _safe_num(item.get("clkCnt"))
                    daily[d]["cost"] += _safe_num(item.get("salesAmt"))
                    daily[d]["conv"] += _safe_num(item.get("ccnt"))
                    daily[d]["rev"] += _safe_num(item.get("convAmt"))

        # 모든 수집된 요일에서 결과 생성
        results = []
        # 먼저 알려진 요일 순서로 정렬
        ordered_days = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
        # 코드 형식 호환
        code_days = ["1", "2", "3", "4", "5", "6", "7"]

        for full_name, code in zip(ordered_days, code_days):
            # API 풀네임 또는 코드 형식 둘 다 확인
            d = daily.get(full_name) or daily.get(code)
            if d is None:
                d = {"imp": 0, "clk": 0, "cost": 0.0, "conv": 0, "rev": 0.0}
            results.append(DayOfWeekBucket(
                day=day_name_order.get(full_name, 0),
                day_name=day_short_name.get(full_name, full_name[0] if full_name else code),
                impressions=d["imp"],
                clicks=d["clk"],
                cost=d["cost"],
                conversions=d["conv"],
                conv_revenue=d["rev"],
            ))
        return results

    # ═══════════════════════════════════════════════════════
    #  지역별 분석
    # ═══════════════════════════════════════════════════════

    def _collect_region_stats(
        self, campaign_ids: list[str], since: str, until: str
    ) -> list[RegionBucket]:
        """지역별 통계 수집"""
        fields = ["impCnt", "clkCnt", "salesAmt", "ccnt", "convAmt"]
        data = self.client.get_stats_with_breakdown(
            ids=campaign_ids, fields=fields,
            since=since, until=until, breakdown="regnNo",
        )

        # 지역 풀네임 → 약칭 매핑 (API는 "서울특별시" 등 풀네임 반환)
        region_short_name = {
            "서울특별시": "서울", "인천광역시": "인천", "경기도": "경기",
            "강원특별자치도": "강원", "강원도": "강원",
            "대전광역시": "대전", "세종특별자치시": "세종",
            "충청남도": "충남", "충청북도": "충북",
            "부산광역시": "부산", "울산광역시": "울산",
            "경상남도": "경남", "경상북도": "경북",
            "대구광역시": "대구", "전라남도": "전남",
            "전북특별자치도": "전북", "전라북도": "전북",
            "광주광역시": "광주", "제주특별자치도": "제주",
            "국내 - 상세 위치 확인불가": "기타(국내)",
            "대한민국외": "해외",
        }

        region_agg = defaultdict(lambda: {"imp": 0, "clk": 0, "cost": 0.0, "conv": 0, "rev": 0.0})
        if data:
            for item in data:
                # breakdown 데이터는 item["breakdowns"] 안에 있음
                breakdowns = item.get("breakdowns", [])
                if breakdowns:
                    for bd in breakdowns:
                        r_name = str(bd.get("name", ""))
                        region_agg[r_name]["imp"] += _safe_num(bd.get("impCnt"))
                        region_agg[r_name]["clk"] += _safe_num(bd.get("clkCnt"))
                        region_agg[r_name]["cost"] += _safe_num(bd.get("salesAmt"))
                        region_agg[r_name]["conv"] += _safe_num(bd.get("ccnt"))
                        region_agg[r_name]["rev"] += _safe_num(bd.get("convAmt"))
                else:
                    r_code = str(item.get("regnNo", ""))
                    region_agg[r_code]["imp"] += _safe_num(item.get("impCnt"))
                    region_agg[r_code]["clk"] += _safe_num(item.get("clkCnt"))
                    region_agg[r_code]["cost"] += _safe_num(item.get("salesAmt"))
                    region_agg[r_code]["conv"] += _safe_num(item.get("ccnt"))
                    region_agg[r_code]["rev"] += _safe_num(item.get("convAmt"))

        results = []
        for r_name, d in region_agg.items():
            if d["cost"] == 0 and d["imp"] == 0:
                continue
            ctr = (d["clk"] / d["imp"] * 100) if d["imp"] > 0 else 0.0
            # 약칭 변환: "서울특별시" → "서울", 또는 REGION_CODE_MAP 코드 매핑
            short_name = region_short_name.get(r_name) or REGION_CODE_MAP.get(r_name, r_name)
            results.append(RegionBucket(
                region_code=r_name,
                region_name=short_name,
                impressions=d["imp"],
                clicks=d["clk"],
                cost=d["cost"],
                conversions=d["conv"],
                conv_revenue=d["rev"],
                ctr=ctr,
            ))
        results.sort(key=lambda x: x.cost, reverse=True)
        logger.info(f"지역별 통계 {len(results)}개 수집 완료")
        return results

    # ═══════════════════════════════════════════════════════
    #  실제 검색어 분석 (EXPKEYWORD)
    # ═══════════════════════════════════════════════════════

    def _collect_search_terms(
        self, target_date: date, campaign_map: dict
    ) -> list[SearchTermStats]:
        """EXPKEYWORD StatReport로 실제 검색어 수집"""
        date_str = target_date.strftime("%Y-%m-%d")

        tsv = self.client.wait_and_download_stat_report("EXPKEYWORD", date_str)
        if not tsv or not tsv.strip():
            return []

        # EXPKEYWORD TSV 컬럼:
        # [0]=date [1]=customerId [2]=campaignId [3]=adGroupId
        # [4]=keyword(매칭된) [5]=searchTerm(실제검색어)
        # [6]=impCnt [7]=clkCnt [8]=salesAmt [9]=ccnt [10]=convAmt
        term_agg = defaultdict(lambda: {
            "keyword": "", "campaign": "", "adgroup": "",
            "imp": 0, "clk": 0, "cost": 0.0, "conv": 0, "rev": 0.0
        })

        for line in tsv.strip().split("\n"):
            cols = line.split("\t")
            if len(cols) < 9:
                continue

            try:
                campaign_id = cols[2]
                keyword = cols[4] if len(cols) > 4 else ""
                search_term = cols[5] if len(cols) > 5 else cols[4]
                imp = int(cols[6]) if len(cols) > 6 else 0
                clk = int(cols[7]) if len(cols) > 7 else 0
                cost = float(cols[8]) if len(cols) > 8 else 0.0
                conv = int(cols[9]) if len(cols) > 9 else 0
                rev = float(cols[10]) if len(cols) > 10 else 0.0
            except (ValueError, IndexError):
                continue

            agg = term_agg[search_term]
            agg["keyword"] = keyword
            agg["campaign"] = campaign_map.get(campaign_id, "")
            agg["imp"] += imp
            agg["clk"] += clk
            agg["cost"] += cost
            agg["conv"] += conv
            agg["rev"] += rev

        results = []
        for term, d in term_agg.items():
            if d["cost"] == 0 and d["imp"] == 0:
                continue
            ctr = (d["clk"] / d["imp"] * 100) if d["imp"] > 0 else 0.0
            results.append(SearchTermStats(
                search_term=term,
                keyword=d["keyword"],
                campaign_name=d["campaign"],
                impressions=d["imp"],
                clicks=d["clk"],
                ctr=ctr,
                cost=d["cost"],
                conversions=d["conv"],
                conv_revenue=d["rev"],
            ))

        results.sort(key=lambda x: x.cost, reverse=True)
        logger.info(f"검색어 {len(results)}개 수집 완료")
        return results

    # ═══════════════════════════════════════════════════════
    #  쇼핑 키워드 전환 보완
    # ═══════════════════════════════════════════════════════

    def _fill_shopping_conversions(
        self, target_date: date, keywords: list[KeywordStats]
    ) -> None:
        """SHOPPINGKEYWORD_CONVERSION_DETAIL로 쇼핑 키워드 전환 데이터 보완"""
        date_str = target_date.strftime("%Y-%m-%d")

        try:
            tsv = self.client.wait_and_download_stat_report(
                "SHOPPINGKEYWORD_CONVERSION_DETAIL", date_str
            )
        except Exception as e:
            logger.warning(f"SHOPPINGKEYWORD_CONVERSION_DETAIL 실패: {e}")
            return

        if not tsv or not tsv.strip():
            return

        # 키워드별 전환 집계
        conv_agg = defaultdict(lambda: {"conv": 0, "rev": 0.0})
        for line in tsv.strip().split("\n"):
            cols = line.split("\t")
            if len(cols) < 10:
                continue
            try:
                kw_text = cols[4]
                conv = int(cols[-2]) if cols[-2].strip().isdigit() else 0
                rev = float(cols[-1]) if cols[-1].strip().replace(".", "").isdigit() else 0.0
            except (ValueError, IndexError):
                continue
            conv_agg[kw_text]["conv"] += conv
            conv_agg[kw_text]["rev"] += rev

        # 기존 쇼핑 키워드에 전환 데이터 매핑
        for kw in keywords:
            if kw.source == "shopping" and kw.keyword in conv_agg:
                d = conv_agg[kw.keyword]
                kw.conversions = d["conv"]
                kw.conv_revenue = d["rev"]
                if kw.cost > 0 and kw.conv_revenue > 0:
                    kw.roas = kw.conv_revenue / kw.cost * 100

    # ═══════════════════════════════════════════════════════
    #  전환 상세 분석 (AD_CONVERSION_DETAIL)
    # ═══════════════════════════════════════════════════════

    def _collect_conversion_details(
        self, target_date: date
    ) -> list[ConversionDetailBucket]:
        """AD_CONVERSION_DETAIL StatReport로 전환 유형별 분석"""
        date_str = target_date.strftime("%Y-%m-%d")

        try:
            tsv = self.client.wait_and_download_stat_report(
                "AD_CONVERSION_DETAIL", date_str
            )
        except Exception as e:
            logger.warning(f"AD_CONVERSION_DETAIL 실패: {e}")
            return []

        if not tsv or not tsv.strip():
            return []

        lines = tsv.strip().split("\n")

        # AD_CONVERSION_DETAIL TSV 실제 컬럼 (15컬럼):
        # [0]=statDt [1]=customerId [2]=campaignId [3]=adGroupId
        # [4]=keyword(-) [5]=adId [6]=businessChannelId
        # [7]=hour [8]=? [9]=? [10]=device(M/P) [11]=?
        # [12]=conversionType(purchase,sign_up 등) [13]=convCount [14]=convRevenue

        # 전환유형 컬럼 인덱스 자동 감지
        conv_type_col = -1
        if lines:
            first_cols = lines[0].split("\t")
            logger.debug(f"[전환상세] 첫 줄 ({len(first_cols)}컬럼): {first_cols}")
            # 알려진 전환유형 키워드로 컬럼 찾기
            known_conv_types = {"purchase", "sign_up", "cart", "apply", "app_install", "etc",
                                "add_to_cart", "begin_checkout", "page_view", "complete_registration",
                                "lead", "schedule", "start_trial", "subscribe", "add_payment_info"}
            for ci in range(len(first_cols)):
                if first_cols[ci].strip().lower() in known_conv_types:
                    conv_type_col = ci
                    break
            if conv_type_col == -1:
                # 마지막 3개 컬럼이 convType, convCount, convRevenue인 패턴
                # 뒤에서 3번째가 영문 알파벳이면 전환유형
                for ci in range(len(first_cols) - 1, 3, -1):
                    val = first_cols[ci].strip().lower()
                    if val and val.isalpha() and len(val) > 2:
                        conv_type_col = ci
                        break
                    elif val and '_' in val and not val.startswith('nad') and not val.startswith('ncc'):
                        conv_type_col = ci
                        break

        logger.debug(f"[전환상세] 전환유형 컬럼 인덱스: {conv_type_col}")

        # 전환 유형별 집계
        type_agg = defaultdict(lambda: {
            "direct_conv": 0, "indirect_conv": 0,
            "direct_rev": 0.0, "indirect_rev": 0.0
        })

        for line in lines:
            cols = line.split("\t")
            if len(cols) < 8:
                continue

            try:
                if conv_type_col >= 0 and conv_type_col < len(cols):
                    conv_type = cols[conv_type_col].strip()
                    # 전환유형 뒤에 오는 숫자 컬럼들이 전환 수와 매출
                    conv_count = 0
                    conv_revenue = 0.0
                    # conv_type 뒤의 컬럼들 탐색
                    remaining = cols[conv_type_col + 1:]
                    for r in remaining:
                        r_stripped = r.strip()
                        if r_stripped.replace(".", "").replace("-", "").isdigit():
                            if conv_count == 0:
                                conv_count = int(float(r_stripped))
                            else:
                                conv_revenue = float(r_stripped)
                                break
                else:
                    # 자동감지 실패 시: 마지막 3개 컬럼 사용
                    conv_type = cols[-3].strip() if len(cols) >= 3 else "etc"
                    conv_count = int(float(cols[-2].strip())) if len(cols) >= 2 and cols[-2].strip().replace(".", "").isdigit() else 0
                    conv_revenue = float(cols[-1].strip()) if cols[-1].strip().replace(".", "").isdigit() else 0.0
            except (ValueError, IndexError):
                continue

            # ID 형식은 스킵
            if conv_type.startswith("nad-") or conv_type.startswith("ncc") or conv_type.startswith("bsn-") or conv_type.startswith("cmp-") or conv_type.startswith("grp-"):
                continue
            # 순수 숫자만 있는 건 스킵 (날짜, ID 등)
            if conv_type.replace(".", "").replace("-", "").isdigit():
                continue
            if not conv_type or conv_type == "-":
                continue

            agg = type_agg[conv_type]
            agg["direct_conv"] += conv_count
            agg["direct_rev"] += conv_revenue

        results = []
        for ctype, d in type_agg.items():
            total_conv = d["direct_conv"] + d["indirect_conv"]
            total_rev = d["direct_rev"] + d["indirect_rev"]
            if total_conv == 0 and total_rev == 0:
                continue
            results.append(ConversionDetailBucket(
                conversion_type=CONVERSION_TYPE_MAP.get(ctype, ctype),
                direct_conversions=d["direct_conv"],
                indirect_conversions=d["indirect_conv"],
                total_conversions=total_conv,
                direct_revenue=d["direct_rev"],
                indirect_revenue=d["indirect_rev"],
                total_revenue=total_rev,
            ))
        results.sort(key=lambda x: x.total_conversions, reverse=True)
        logger.info(f"전환 상세 {len(results)}건 수집 완료 (유형: {[r.conversion_type for r in results]})")
        return results

    # ═══════════════════════════════════════════════════════
    #  쇼핑 키워드 수집 (기존)
    # ═══════════════════════════════════════════════════════

    def _collect_shopping_keywords(
        self, target_date: date, campaign_map: dict, campaign_type_map: dict,
    ) -> list[KeywordStats]:
        """SHOPPINGKEYWORD_DETAIL StatReport로 쇼핑 검색어 데이터 수집"""
        date_str = target_date.strftime("%Y-%m-%d")

        try:
            tsv = self.client.wait_and_download_stat_report(
                "SHOPPINGKEYWORD_DETAIL", date_str
            )
        except Exception as e:
            logger.warning(f"SHOPPINGKEYWORD_DETAIL 다운로드 실패: {e}")
            return []

        if not tsv or not tsv.strip():
            return []

        cid_name_map = {}
        for cid, cname in campaign_map.items():
            cid_name_map[cid] = cname

        agid_name_map = {}
        for cid in campaign_map:
            if campaign_type_map.get(cid) != "SHOPPING":
                continue
            try:
                adgroups = self.client.get_adgroups(cid)
                if adgroups:
                    for ag in adgroups:
                        agid_name_map[ag["nccAdgroupId"]] = ag.get("name", "이름없음")
            except Exception:
                pass

        kw_agg = defaultdict(lambda: {"imp": 0, "clk": 0, "cost": 0, "campaigns": set(), "adgroups": set()})

        for line in tsv.strip().split("\n"):
            cols = line.split("\t")
            if len(cols) < 14:
                continue

            keyword = cols[4]
            campaign_id = cols[2]
            adgroup_id = cols[3]

            try:
                imp = int(cols[11])
                clk = int(cols[12])
                cost = int(cols[13])
            except (ValueError, IndexError):
                continue

            agg = kw_agg[keyword]
            agg["imp"] += imp
            agg["clk"] += clk
            agg["cost"] += cost
            agg["campaigns"].add(campaign_id)
            agg["adgroups"].add(adgroup_id)

        results = []
        for keyword, data in kw_agg.items():
            if data["cost"] == 0 and data["imp"] == 0:
                continue

            cname = "쇼핑검색"
            for cid in data["campaigns"]:
                if cid in cid_name_map:
                    cname = cid_name_map[cid]
                    break

            ag_name = ""
            for agid in data["adgroups"]:
                if agid in agid_name_map:
                    ag_name = agid_name_map[agid]
                    break

            imp = data["imp"]
            clk = data["clk"]
            cost = data["cost"]
            ctr = (clk / imp * 100) if imp > 0 else 0.0
            cpc = (cost / clk) if clk > 0 else 0.0

            results.append(KeywordStats(
                keyword=keyword,
                keyword_id="",
                adgroup_name=ag_name,
                campaign_name=cname,
                source="shopping",
                impressions=imp,
                clicks=clk,
                ctr=ctr,
                cpc=cpc,
                cost=cost,
            ))

        results.sort(key=lambda x: x.cost, reverse=True)
        logger.info(f"쇼핑 키워드 {len(results)}개 수집 완료")
        return results

    # ═══════════════════════════════════════════════════════
    #  광고그룹 + 키워드 통계 수집 (기존 확장)
    # ═══════════════════════════════════════════════════════

    def _collect_adgroup_and_keyword_stats(
        self, campaigns: list[dict], campaign_map: dict,
        since: str, until: str,
    ) -> tuple[list[AdGroupStats], list[KeywordStats]]:
        """캠페인 → 광고그룹 → 키워드 순으로 탐색, 그룹/키워드 통계 수집"""
        adgroup_info = {}
        keyword_info = {}
        all_adgroup_ids = []
        all_keyword_ids = []

        for campaign in campaigns:
            cid = campaign["nccCampaignId"]
            cname = campaign_map.get(cid, "이름없음")

            try:
                adgroups = self.client.get_adgroups(cid)
            except Exception as e:
                logger.warning(f"[{cname}] 그룹 조회 실패: {e}")
                continue

            if not adgroups:
                continue

            for ag in adgroups:
                ag_id = ag.get("nccAdgroupId")
                ag_name = ag.get("name", "이름없음")

                if ag_id:
                    adgroup_info[ag_id] = {
                        "name": ag_name,
                        "campaign_name": cname,
                        "bid_amt": _safe_num(ag.get("bidAmt")),
                        "daily_budget": _safe_num(ag.get("dailyBudget")),
                        "status": ag.get("status", "") or "",
                    }
                    all_adgroup_ids.append(ag_id)

                try:
                    keywords = self.client.get_keywords(ag_id)
                except Exception as e:
                    logger.warning(f"[{cname}/{ag_name}] 키워드 조회 실패: {e}")
                    continue

                if not keywords:
                    continue

                for kw in keywords:
                    kw_id = kw.get("nccKeywordId")
                    kw_text = kw.get("keyword", "")
                    if kw_id and kw_text:
                        keyword_info[kw_id] = {
                            "keyword": kw_text,
                            "adgroup_name": ag_name,
                            "campaign_name": cname,
                            "bid_amt": _safe_num(kw.get("bidAmt")),
                            "quality_index": _safe_num(kw.get("nccQi")),
                        }
                        all_keyword_ids.append(kw_id)

        # 광고그룹 통계
        adgroup_stats_list = self._batch_get_stats(
            all_adgroup_ids, adgroup_info, since, until, "adgroup"
        )

        # 파워링크 키워드 통계
        keyword_stats_list = self._batch_get_stats(
            all_keyword_ids, keyword_info, since, until, "keyword"
        )
        for kw in keyword_stats_list:
            kw.source = "powerlink"

        return adgroup_stats_list, keyword_stats_list

    def _batch_get_stats(self, ids: list[str], info_map: dict,
                          since: str, until: str,
                          entity_type: str) -> list:
        """ID 목록을 100개씩 배치로 나눠서 통계 조회"""
        results = []
        chunk_size = 100

        for i in range(0, len(ids), chunk_size):
            chunk = ids[i:i + chunk_size]
            try:
                stats = self.client.get_stats(
                    ids=chunk,
                    fields=STAT_FIELDS_FULL,
                    since=since,
                    until=until,
                )
            except Exception as e:
                logger.warning(f"{entity_type} 통계 조회 실패 (chunk {i}): {e}")
                continue

            if not stats:
                continue

            for stat in stats:
                item_id = stat.get("id")
                info = info_map.get(item_id)
                if not info:
                    continue

                cost = _safe_num(stat.get("salesAmt"))
                if cost == 0 and _safe_num(stat.get("impCnt")) == 0:
                    continue

                if entity_type == "adgroup":
                    results.append(AdGroupStats(
                        adgroup_id=item_id,
                        adgroup_name=info["name"],
                        campaign_name=info["campaign_name"],
                        impressions=_safe_num(stat.get("impCnt")),
                        clicks=_safe_num(stat.get("clkCnt")),
                        ctr=_safe_num(stat.get("ctr")),
                        cpc=_safe_num(stat.get("cpc")),
                        cost=cost,
                        conversions=_safe_num(stat.get("ccnt")),
                        conversion_rate=_safe_num(stat.get("crto")),
                        conv_revenue=_safe_num(stat.get("convAmt")),
                        roas=_safe_num(stat.get("ror")),
                        cost_per_conv=_safe_num(stat.get("cpConv")),
                        avg_rank=_safe_num(stat.get("avgRnk")),
                        pc_avg_rank=_safe_num(stat.get("pcNxAvgRnk")),
                        mobile_avg_rank=_safe_num(stat.get("mblNxAvgRnk")),
                        bid_amt=_safe_num(info.get("bid_amt")),
                        daily_budget=_safe_num(info.get("daily_budget")),
                        status=info.get("status", "") or "",
                    ))
                else:
                    results.append(KeywordStats(
                        keyword=info["keyword"],
                        keyword_id=item_id,
                        adgroup_name=info["adgroup_name"],
                        campaign_name=info["campaign_name"],
                        impressions=_safe_num(stat.get("impCnt")),
                        clicks=_safe_num(stat.get("clkCnt")),
                        ctr=_safe_num(stat.get("ctr")),
                        cpc=_safe_num(stat.get("cpc")),
                        cost=cost,
                        conversions=_safe_num(stat.get("ccnt")),
                        conversion_rate=_safe_num(stat.get("crto")),
                        conv_revenue=_safe_num(stat.get("convAmt")),
                        roas=_safe_num(stat.get("ror")),
                        cost_per_conv=_safe_num(stat.get("cpConv")),
                        avg_rank=_safe_num(stat.get("avgRnk")),
                        pc_avg_rank=_safe_num(stat.get("pcNxAvgRnk")),
                        mobile_avg_rank=_safe_num(stat.get("mblNxAvgRnk")),
                        bid_amt=_safe_num(info.get("bid_amt")),
                        quality_index=_safe_num(info.get("quality_index")),
                    ))

        results.sort(key=lambda x: x.cost, reverse=True)
        return results

    # ═══════════════════════════════════════════════════════
    #  AI 인사이트 생성 (강화)
    # ═══════════════════════════════════════════════════════

    def _generate_insights(self, report: AccountReport) -> list[str]:
        """보고서 데이터를 분석하여 상세 인사이트 생성"""
        insights = []

        if not report.campaigns:
            return insights

        # ── 1. 전체 성과 종합 분석 ──
        if report.total_cost > 0:
            avg_cpc = report.total_cost / report.total_clicks if report.total_clicks > 0 else 0
            avg_ctr = report.total_clicks / report.total_impressions * 100 if report.total_impressions > 0 else 0
            conv_rate = report.total_conversions / report.total_clicks * 100 if report.total_clicks > 0 else 0
            cpa = report.total_cost / report.total_conversions if report.total_conversions > 0 else 0

            summary = (
                f"[전체 성과] 총 광고비 {report.total_cost:,.0f}원 집행. "
                f"노출 {report.total_impressions:,}회에서 {report.total_clicks:,}건 클릭 유입 "
                f"(CTR {avg_ctr:.2f}%, 평균 CPC {avg_cpc:,.0f}원). "
            )
            if report.total_conversions > 0:
                summary += (
                    f"전환 {report.total_conversions}건 발생 (전환율 {conv_rate:.2f}%, "
                    f"전환당비용 CPA {cpa:,.0f}원), 전환매출 {report.total_conv_revenue:,.0f}원."
                )
            else:
                summary += "전환이 발생하지 않았습니다. 랜딩페이지 및 키워드 적합성 점검이 필요합니다."
            insights.append(summary)

        # ── 2. ROAS 심층 분석 ──
        if report.total_cost > 0:
            if report.total_roas >= 500:
                insights.append(
                    f"[ROAS 분석] ROAS {report.total_roas:,.0f}%로 매우 우수한 효율입니다. "
                    f"광고비 1원당 {report.total_roas/100:.1f}원의 매출을 만들고 있습니다. "
                    f"현재 전략을 유지하되, 추가 예산 확대를 검토해 보세요."
                )
            elif report.total_roas >= 300:
                insights.append(
                    f"[ROAS 분석] ROAS {report.total_roas:,.0f}%로 우수한 광고 효율입니다. "
                    f"광고비 {report.total_cost:,.0f}원 대비 전환매출 {report.total_conv_revenue:,.0f}원 발생. "
                    f"성과 좋은 키워드에 예산을 집중하면 더 높은 ROAS 달성이 가능합니다."
                )
            elif report.total_roas >= 100:
                gap = report.total_conv_revenue - report.total_cost
                insights.append(
                    f"[ROAS 분석] ROAS {report.total_roas:,.0f}%로 손익분기를 넘겼습니다. "
                    f"순이익 약 {gap:,.0f}원이지만 마진율을 고려하면 실질 수익은 더 적을 수 있습니다. "
                    f"전환 없는 키워드를 정리하고 고효율 키워드에 집중하세요."
                )
            elif report.total_roas > 0:
                loss = report.total_cost - report.total_conv_revenue
                insights.append(
                    f"[ROAS 분석] ROAS {report.total_roas:,.0f}%로 광고비 대비 수익이 부족합니다. "
                    f"광고비 {report.total_cost:,.0f}원 투입 대비 매출 {report.total_conv_revenue:,.0f}원으로 "
                    f"약 {loss:,.0f}원 적자. 저성과 키워드 제외, 입찰가 하향, 타겟팅 재검토가 시급합니다."
                )
            else:
                insights.append(
                    f"[ROAS 분석] 전환매출이 0원입니다. 전환 추적 코드가 정상 작동하는지 확인하고, "
                    f"랜딩페이지 전환율 개선이 필요합니다."
                )

        # ── 3. 캠페인 유형별 비교 분석 ──
        type_stats = {}
        for c in report.campaigns:
            tp = c.campaign_type or "기타"
            if tp not in type_stats:
                type_stats[tp] = {"cost": 0, "clicks": 0, "conv": 0, "revenue": 0, "imp": 0, "count": 0}
            type_stats[tp]["cost"] += c.cost
            type_stats[tp]["clicks"] += c.clicks
            type_stats[tp]["conv"] += c.conversions
            type_stats[tp]["revenue"] += c.conv_revenue
            type_stats[tp]["imp"] += c.impressions
            type_stats[tp]["count"] += 1

        if len(type_stats) >= 2:
            parts = []
            for tp, s in sorted(type_stats.items(), key=lambda x: x[1]["cost"], reverse=True):
                roas = (s["revenue"] / s["cost"] * 100) if s["cost"] > 0 else 0
                ctr = (s["clicks"] / s["imp"] * 100) if s["imp"] > 0 else 0
                parts.append(
                    f"{tp} {s['count']}개: 비용 {s['cost']:,.0f}원, "
                    f"클릭 {s['clicks']:,}, CTR {ctr:.2f}%, "
                    f"전환 {s['conv']}건, ROAS {roas:,.0f}%"
                )
            insights.append(f"[캠페인 유형 비교] " + " / ".join(parts))

        # ── 4. 캠페인별 예산 소진율 분석 ──
        budget_alerts = []
        for c in report.campaigns:
            if c.daily_budget > 0 and c.cost > 0:
                utilization = c.cost / c.daily_budget * 100
                if utilization >= 90:
                    budget_alerts.append(
                        f"'{c.campaign_name}' 예산 {utilization:.0f}% 소진 "
                        f"({c.cost:,.0f}/{c.daily_budget:,.0f}원)"
                    )
        if budget_alerts:
            insights.append(
                f"[예산 경고] 일예산 90% 이상 소진된 캠페인: " + ", ".join(budget_alerts) +
                " - 예산 증액 또는 입찰가 조정을 검토하세요."
            )

        # ── 5. 최고/최저 ROAS 광고그룹 상세 ──
        high_roas_groups = [ag for ag in report.adgroups if ag.roas > 0 and ag.cost > 0]
        if high_roas_groups:
            best = max(high_roas_groups, key=lambda x: x.roas)
            insights.append(
                f"[최고 효율 광고그룹] '{best.adgroup_name}' - "
                f"ROAS {best.roas:,.0f}% (비용 {best.cost:,.0f}원 -> 전환매출 {best.conv_revenue:,.0f}원, "
                f"전환 {best.conversions}건, CPC {best.cpc:,.0f}원). "
                f"이 그룹의 키워드와 소재를 다른 그룹에도 벤치마킹하세요."
            )

        low_roas_groups = [ag for ag in report.adgroups if ag.cost > 5000 and ag.roas < 50 and ag.roas >= 0]
        if low_roas_groups:
            worst = min(low_roas_groups, key=lambda x: x.roas)
            insights.append(
                f"[최저 효율 광고그룹] '{worst.adgroup_name}' - "
                f"ROAS {worst.roas:,.0f}% (비용 {worst.cost:,.0f}원, 전환 {worst.conversions}건). "
                f"입찰가 하향 또는 키워드 재검토가 필요합니다."
            )

        # ── 6. 비용만 발생한 광고그룹 경고 ──
        wasted_groups = [
            ag for ag in report.adgroups
            if ag.cost > 0 and ag.conversions == 0 and ag.conv_revenue == 0
        ]
        if wasted_groups:
            wasted_cost = sum(ag.cost for ag in wasted_groups)
            wasted_pct = wasted_cost / report.total_cost * 100 if report.total_cost > 0 else 0
            top_wasted = sorted(wasted_groups, key=lambda x: x.cost, reverse=True)[:5]
            names = ", ".join(f"'{ag.adgroup_name}'({ag.cost:,.0f}원/{ag.clicks}클릭)" for ag in top_wasted)
            insights.append(
                f"[비용 낭비 경고] 전환 없이 비용만 발생한 광고그룹 {len(wasted_groups)}개, "
                f"낭비 비용 {wasted_cost:,.0f}원 (전체의 {wasted_pct:.1f}%): {names}. "
                f"3일 이상 전환 없으면 일시중지를 검토하세요."
            )

        # ── 7. 디바이스(PC/모바일) 심층 분석 ──
        db = report.device_breakdown
        total_dev_cost = db.pc_cost + db.mobile_cost
        if total_dev_cost > 0:
            mobile_cost_pct = db.mobile_cost / total_dev_cost * 100
            pc_cost_pct = 100 - mobile_cost_pct
            total_dev_clicks = db.pc_clicks + db.mobile_clicks
            mobile_click_pct = db.mobile_clicks / total_dev_clicks * 100 if total_dev_clicks > 0 else 0
            pc_click_pct = 100 - mobile_click_pct if total_dev_clicks > 0 else 0

            device_msg = (
                f"[디바이스 분석] "
                f"PC: 비용 {db.pc_cost:,.0f}원({pc_cost_pct:.0f}%), "
                f"클릭 {db.pc_clicks:,}({pc_click_pct:.0f}%), CTR {db.pc_ctr:.2f}%, "
                f"전환 {db.pc_conversions}건, ROAS {db.pc_roas:,.0f}% / "
                f"모바일: 비용 {db.mobile_cost:,.0f}원({mobile_cost_pct:.0f}%), "
                f"클릭 {db.mobile_clicks:,}({mobile_click_pct:.0f}%), CTR {db.mobile_ctr:.2f}%, "
                f"전환 {db.mobile_conversions}건, ROAS {db.mobile_roas:,.0f}%. "
            )
            # 실행 가능한 조언 추가
            if db.pc_roas > 0 and db.mobile_roas > 0:
                if db.pc_roas > db.mobile_roas * 1.5:
                    device_msg += "PC의 ROAS가 모바일보다 1.5배 이상 높습니다. PC 입찰 가중치를 높이고 모바일 랜딩페이지를 개선하세요."
                elif db.mobile_roas > db.pc_roas * 1.5:
                    device_msg += "모바일의 ROAS가 PC보다 1.5배 이상 높습니다. 모바일 입찰 가중치를 높이는 것을 권장합니다."
                else:
                    device_msg += "PC와 모바일의 효율이 유사합니다."
            elif db.pc_roas > 0 and db.mobile_roas == 0 and db.mobile_cost > 0:
                device_msg += "모바일에서 전환이 없습니다. 모바일 랜딩페이지 최적화가 시급합니다."
            elif db.mobile_roas > 0 and db.pc_roas == 0 and db.pc_cost > 0:
                device_msg += "PC에서 전환이 없습니다. PC 랜딩페이지 점검이 필요합니다."
            insights.append(device_msg)

        # ── 8. 시간대별 심층 분석 ──
        if report.hourly_stats:
            cost_hours = [h for h in report.hourly_stats if h.cost > 0]
            if cost_hours:
                total_hourly_cost = sum(h.cost for h in cost_hours)
                peak_hours = sorted(cost_hours, key=lambda x: x.cost, reverse=True)[:3]
                low_hours = sorted([h for h in cost_hours if h.cost > 0], key=lambda x: x.cost)[:3]

                peak_info = ", ".join(
                    f"{h.hour}시({h.cost:,.0f}원/{h.clicks}클릭/{h.conversions}전환)" for h in peak_hours
                )
                low_info = ", ".join(f"{h.hour}시({h.cost:,.0f}원)" for h in low_hours)

                time_msg = f"[시간대 분석] 비용 집중 시간: {peak_info}. 비용 적은 시간: {low_info}. "

                # 전환 효율이 높은 시간대 분석
                conv_hours = [h for h in report.hourly_stats if h.conversions > 0]
                if conv_hours:
                    best_conv_hour = max(conv_hours, key=lambda x: x.conversions)
                    best_roas_hours = [h for h in conv_hours if h.cost > 0]
                    if best_roas_hours:
                        best_eff = max(best_roas_hours, key=lambda x: x.conv_revenue / x.cost if x.cost > 0 else 0)
                        eff_roas = best_eff.conv_revenue / best_eff.cost * 100 if best_eff.cost > 0 else 0
                        time_msg += f"최다 전환 시간: {best_conv_hour.hour}시({best_conv_hour.conversions}건). "
                        if eff_roas > 0:
                            time_msg += f"가장 효율적인 시간: {best_eff.hour}시(ROAS {eff_roas:,.0f}%). "

                # 비용 지출은 있지만 전환 없는 시간대
                waste_hours = [h for h in cost_hours if h.conversions == 0 and h.cost > 1000]
                if waste_hours:
                    waste_total = sum(h.cost for h in waste_hours)
                    waste_hour_list = ", ".join(f"{h.hour}시" for h in sorted(waste_hours, key=lambda x: x.cost, reverse=True)[:5])
                    time_msg += f"전환 없이 비용 발생한 시간대: {waste_hour_list} (총 {waste_total:,.0f}원). 해당 시간대 입찰 하향을 검토하세요."

                insights.append(time_msg)

        # ── 9. 요일별 심층 분석 ──
        if report.day_of_week_stats:
            cost_days = [d for d in report.day_of_week_stats if d.cost > 0]
            if len(cost_days) >= 2:
                total_week_cost = sum(d.cost for d in cost_days)
                best_day = max(cost_days, key=lambda x: x.conv_revenue if x.conv_revenue > 0 else 0)
                worst_day = max(cost_days, key=lambda x: x.cost if x.conversions == 0 else 0)
                highest_cost_day = max(cost_days, key=lambda x: x.cost)

                weekday_cost = sum(d.cost for d in cost_days if d.day <= 5)
                weekend_cost = sum(d.cost for d in cost_days if d.day >= 6)
                weekday_conv = sum(d.conversions for d in cost_days if d.day <= 5)
                weekend_conv = sum(d.conversions for d in cost_days if d.day >= 6)

                day_msg = f"[요일별 분석] "
                day_parts = []
                for d in sorted(cost_days, key=lambda x: x.day):
                    roas = (d.conv_revenue / d.cost * 100) if d.cost > 0 else 0
                    day_parts.append(
                        f"{d.day_name}({d.cost:,.0f}원/{d.clicks}클릭/{d.conversions}전환)"
                    )
                day_msg += " > ".join(day_parts) + ". "

                if weekday_cost > 0 and weekend_cost > 0:
                    day_msg += (
                        f"주중 비용 {weekday_cost:,.0f}원/전환 {weekday_conv}건, "
                        f"주말 비용 {weekend_cost:,.0f}원/전환 {weekend_conv}건. "
                    )
                    if weekday_conv > 0 and weekend_conv > 0:
                        wd_cpa = weekday_cost / weekday_conv
                        we_cpa = weekend_cost / weekend_conv
                        if wd_cpa < we_cpa * 0.7:
                            day_msg += "주중의 전환 효율이 주말보다 높습니다. 주말 예산을 줄이는 것을 검토하세요."
                        elif we_cpa < wd_cpa * 0.7:
                            day_msg += "주말의 전환 효율이 주중보다 높습니다. 주말 예산을 늘리는 것을 검토하세요."
                    elif weekday_conv > 0 and weekend_conv == 0 and weekend_cost > 0:
                        day_msg += "주말에 전환이 없습니다. 주말 입찰 가중치를 낮추는 것을 권장합니다."

                insights.append(day_msg)

        # ── 10. 지역별 심층 분석 ──
        if report.region_stats and len(report.region_stats) >= 3:
            total_region_cost = sum(r.cost for r in report.region_stats)
            top5 = report.region_stats[:5]
            top5_info = ", ".join(
                f"{r.region_name}({r.cost:,.0f}원/{r.clicks}클릭/CTR {r.ctr:.2f}%/{r.conversions}전환)"
                for r in top5
            )
            top5_cost = sum(r.cost for r in top5)
            top5_pct = top5_cost / total_region_cost * 100 if total_region_cost > 0 else 0

            region_msg = (
                f"[지역 분석] 상위 5개 지역이 전체의 {top5_pct:.0f}%: {top5_info}. "
            )

            # 전환 효율 좋은/나쁜 지역
            conv_regions = [r for r in report.region_stats if r.conversions > 0 and r.cost > 0]
            no_conv_regions = [r for r in report.region_stats if r.conversions == 0 and r.cost > 1000]
            if conv_regions:
                best_region = max(conv_regions, key=lambda x: x.conversions / x.cost if x.cost > 0 else 0)
                region_msg += f"전환 효율 최고 지역: {best_region.region_name}. "
            if no_conv_regions:
                waste_region_cost = sum(r.cost for r in no_conv_regions)
                waste_names = ", ".join(r.region_name for r in no_conv_regions[:3])
                region_msg += f"전환 없이 비용 발생 지역: {waste_names} (총 {waste_region_cost:,.0f}원)."

            insights.append(region_msg)

        # ── 11. 쇼핑검색 키워드 심층 분석 ──
        shopping_kws = [kw for kw in report.keywords if kw.source == "shopping" and kw.cost > 0]
        if shopping_kws:
            total_shop_cost = sum(kw.cost for kw in shopping_kws)
            total_shop_conv = sum(kw.conversions for kw in shopping_kws)
            total_shop_rev = sum(kw.conv_revenue for kw in shopping_kws)
            shop_roas = (total_shop_rev / total_shop_cost * 100) if total_shop_cost > 0 else 0

            top5_shop = shopping_kws[:5]
            top5_info = ", ".join(
                f"'{kw.keyword}'({kw.cost:,.0f}원/{kw.clicks}클릭/{kw.conversions}전환)"
                for kw in top5_shop
            )
            shop_msg = (
                f"[쇼핑검색 분석] 총 {len(shopping_kws)}개 검색어, "
                f"비용 {total_shop_cost:,.0f}원, 전환 {total_shop_conv}건, "
                f"ROAS {shop_roas:,.0f}%. 상위 5개: {top5_info}."
            )

            # 클릭 높지만 전환 없는 쇼핑 키워드
            waste_shop = [kw for kw in shopping_kws if kw.clicks >= 5 and kw.conversions == 0]
            if waste_shop:
                waste_info = ", ".join(
                    f"'{kw.keyword}'({kw.cost:,.0f}원/{kw.clicks}클릭)" for kw in waste_shop[:3]
                )
                waste_total = sum(kw.cost for kw in waste_shop)
                shop_msg += f" 전환 없는 고클릭 검색어(제외 후보): {waste_info} (총 {waste_total:,.0f}원 낭비)."

            insights.append(shop_msg)

        # ── 12. 파워링크 키워드 분석 ──
        pl_kws = [kw for kw in report.keywords if kw.source == "powerlink" and kw.cost > 0]
        if pl_kws:
            total_pl_cost = sum(kw.cost for kw in pl_kws)
            total_pl_conv = sum(kw.conversions for kw in pl_kws)
            total_pl_rev = sum(kw.conv_revenue for kw in pl_kws)
            pl_roas = (total_pl_rev / total_pl_cost * 100) if total_pl_cost > 0 else 0

            top3_pl = pl_kws[:3]
            top3_info = ", ".join(
                f"'{kw.keyword}'({kw.cost:,.0f}원/QI:{kw.quality_index}/ROAS:{kw.roas:,.0f}%)"
                for kw in top3_pl
            )
            insights.append(
                f"[파워링크 분석] 총 {len(pl_kws)}개 키워드, "
                f"비용 {total_pl_cost:,.0f}원, 전환 {total_pl_conv}건, ROAS {pl_roas:,.0f}%. "
                f"상위: {top3_info}."
            )

        # ── 13. 클릭 대비 전환 효율 분석 ──
        if report.total_clicks > 0 and report.total_cost > 0:
            conv_kws = [kw for kw in report.keywords if kw.conversions > 0 and kw.cost > 0]
            no_conv_kws = [kw for kw in report.keywords if kw.clicks >= 3 and kw.conversions == 0 and kw.cost > 0]
            if no_conv_kws:
                waste_cost = sum(kw.cost for kw in no_conv_kws)
                waste_pct = waste_cost / report.total_cost * 100
                top_waste = sorted(no_conv_kws, key=lambda x: x.cost, reverse=True)[:5]
                waste_names = ", ".join(f"'{kw.keyword}'({kw.cost:,.0f}원/{kw.clicks}클릭)" for kw in top_waste)
                insights.append(
                    f"[비효율 키워드 경고] 3클릭 이상이지만 전환 없는 키워드 {len(no_conv_kws)}개, "
                    f"총 {waste_cost:,.0f}원 낭비 (전체의 {waste_pct:.1f}%): {waste_names}. "
                    f"제외 키워드 등록 또는 입찰가 하향을 검토하세요."
                )

        # ── 14. 품질지수 분석 ──
        qi_kws = [kw for kw in report.keywords if kw.quality_index > 0 and kw.source == "powerlink"]
        if qi_kws:
            avg_qi = sum(kw.quality_index for kw in qi_kws) / len(qi_kws)
            high_qi = [kw for kw in qi_kws if kw.quality_index >= 7]
            mid_qi = [kw for kw in qi_kws if 4 <= kw.quality_index < 7]
            low_qi = [kw for kw in qi_kws if kw.quality_index < 4]

            qi_msg = (
                f"[품질지수 분석] 평균 QI {avg_qi:.1f} "
                f"(높음 {len(high_qi)}개 / 보통 {len(mid_qi)}개 / 낮음 {len(low_qi)}개). "
            )
            if low_qi:
                low_qi_sorted = sorted(low_qi, key=lambda x: x.cost, reverse=True)[:3]
                low_info = ", ".join(
                    f"'{kw.keyword}'(QI:{kw.quality_index}, CPC {kw.cpc:,.0f}원)" for kw in low_qi_sorted
                )
                qi_msg += (
                    f"품질지수 낮은 키워드: {low_info}. "
                    f"QI가 낮으면 같은 순위에 더 높은 CPC를 지불합니다. "
                    f"광고 소재 관련성 개선, 랜딩페이지 매칭을 점검하세요."
                )
            insights.append(qi_msg)

        # ── 15. 검색어 분석 ──
        if report.search_terms:
            waste_terms = [t for t in report.search_terms if t.clicks >= 3 and t.conversions == 0]
            if waste_terms:
                waste_cost = sum(t.cost for t in waste_terms)
                top5 = waste_terms[:5]
                terms_info = ", ".join(f"'{t.search_term}'({t.cost:,.0f}원/{t.clicks}클릭)" for t in top5)
                insights.append(
                    f"[검색어 낭비 경고] 전환 없는 검색어 {len(waste_terms)}개, "
                    f"총 {waste_cost:,.0f}원 낭비: {terms_info}. "
                    f"네이버 검색광고에서 '제외 키워드'로 등록하면 광고비를 절약할 수 있습니다."
                )

        # ── 16. 순위 분석 ──
        ranked_kws = [kw for kw in report.keywords if kw.avg_rank > 0 and kw.cost > 0]
        if ranked_kws:
            avg_rank = sum(kw.avg_rank for kw in ranked_kws) / len(ranked_kws)
            high_rank_kws = [kw for kw in ranked_kws if kw.avg_rank <= 3]
            low_rank_kws = [kw for kw in ranked_kws if kw.avg_rank >= 8]

            rank_msg = f"[순위 분석] 평균 광고 순위 {avg_rank:.1f}위. "
            if high_rank_kws:
                rank_msg += f"상위 노출(1~3위) 키워드 {len(high_rank_kws)}개. "
            if low_rank_kws:
                low_names = ", ".join(
                    f"'{kw.keyword}'({kw.avg_rank:.1f}위)" for kw in sorted(low_rank_kws, key=lambda x: x.avg_rank, reverse=True)[:3]
                )
                rank_msg += f"하위 노출(8위 이하) 키워드: {low_names}. 입찰가 인상 또는 품질지수 개선이 필요합니다."

            # PC/모바일 순위 괴리
            rank_diff_kws = [
                kw for kw in report.keywords
                if kw.pc_avg_rank > 0 and kw.mobile_avg_rank > 0
                and abs(kw.pc_avg_rank - kw.mobile_avg_rank) > 3
                and kw.cost > 0
            ]
            if rank_diff_kws:
                top2 = sorted(rank_diff_kws, key=lambda x: abs(x.pc_avg_rank - x.mobile_avg_rank), reverse=True)[:2]
                diff_info = ", ".join(
                    f"'{kw.keyword}'(PC {kw.pc_avg_rank:.1f}위/모바일 {kw.mobile_avg_rank:.1f}위)"
                    for kw in top2
                )
                rank_msg += f" PC/모바일 순위 차이 큰 키워드: {diff_info}."

            insights.append(rank_msg)

        # ── 17. 전환 상세 분석 ──
        if report.conversion_details:
            conv_parts = []
            for cv in report.conversion_details:
                conv_parts.append(
                    f"{cv.conversion_type}: {cv.total_conversions}건(매출 {cv.total_revenue:,.0f}원)"
                )
            insights.append(
                f"[전환 유형 분석] " + ", ".join(conv_parts) + ". "
                f"전환 유형별 성과를 추적하여 가장 효율적인 전환 경로에 집중하세요."
            )

        # ── 18. 비즈머니 잔액 경고 ──
        if report.bizmoney_balance and report.bizmoney_balance > 0 and report.total_cost > 0:
            days_remaining = report.bizmoney_balance / report.total_cost if report.total_cost > 0 else 999
            if days_remaining < 3:
                insights.append(
                    f"[비즈머니 경고] 잔액 {report.bizmoney_balance:,.0f}원으로 "
                    f"현재 소진 속도 기준 약 {days_remaining:.1f}일분입니다. 즉시 충전이 필요합니다."
                )
            elif days_remaining < 7:
                insights.append(
                    f"[비즈머니 알림] 잔액 {report.bizmoney_balance:,.0f}원 "
                    f"(현재 속도 기준 약 {days_remaining:.0f}일분). 충전을 준비하세요."
                )

        # ── 19. 종합 개선 제안 ──
        suggestions = []
        if wasted_groups and len(wasted_groups) >= 3:
            suggestions.append("전환 없는 광고그룹 정리")
        if report.total_roas > 0 and report.total_roas < 100:
            suggestions.append("저성과 키워드 제외 및 입찰가 조정")
        low_qi_cost_kws = [kw for kw in report.keywords if kw.quality_index > 0 and kw.quality_index < 4 and kw.cost > 1000]
        if low_qi_cost_kws:
            suggestions.append("품질지수 낮은 키워드 소재 개선")
        if total_dev_cost > 0:
            pc_pct = db.pc_cost / total_dev_cost * 100
            if pc_pct > 70 and db.pc_roas < db.mobile_roas:
                suggestions.append("PC 입찰가 하향 조정")
            elif pc_pct < 30 and db.mobile_roas < db.pc_roas:
                suggestions.append("모바일 입찰가 하향 조정")
        if suggestions:
            insights.append(f"[종합 개선 제안] 우선 실행 항목: " + " / ".join(suggestions))

        return insights

    # ═══════════════════════════════════════════════════════
    #  정렬 + 유틸리티
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def sort_report(report: AccountReport,
                    adgroup_sort_by: str = "cost",
                    adgroup_sort_order: str = "desc",
                    keyword_sort_by: str = "cost",
                    keyword_sort_order: str = "desc") -> None:
        """광고그룹/키워드 리스트를 지정된 기준으로 정렬 (in-place)"""
        valid_fields = {"impressions", "clicks", "ctr", "cpc", "cost",
                        "conversions", "conv_revenue", "roas",
                        "avg_rank", "bid_amt", "quality_index"}

        if adgroup_sort_by in valid_fields and report.adgroups:
            reverse = adgroup_sort_order != "asc"
            report.adgroups.sort(
                key=lambda x: getattr(x, adgroup_sort_by, 0), reverse=reverse
            )

        if keyword_sort_by in valid_fields and report.keywords:
            reverse = keyword_sort_order != "asc"
            report.keywords.sort(
                key=lambda x: getattr(x, keyword_sort_by, 0), reverse=reverse
            )

    def generate_daily_report(self, target_date: date = None) -> AccountReport:
        """하루 보고서 (하위 호환)"""
        if target_date is None:
            target_date = date.today() - timedelta(days=1)
        return self.generate_report(date_from=target_date, date_to=target_date)

    def get_daily_cost(self, target_date: date = None) -> float:
        if target_date is None:
            target_date = date.today()

        date_str = target_date.strftime("%Y-%m-%d")

        campaigns = self.client.get_campaigns()
        if not campaigns:
            return 0.0

        campaign_ids = [c["nccCampaignId"] for c in campaigns]

        stats_data = self.client.get_stats(
            ids=campaign_ids,
            fields=["salesAmt"],
            since=date_str,
            until=date_str,
        )

        total = 0.0
        if stats_data:
            for item in stats_data:
                total += item.get("salesAmt", 0.0)

        return total
