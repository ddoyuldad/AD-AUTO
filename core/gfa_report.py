"""
네이버 GFA 보고서 데이터 모델 및 파싱.
스크래핑한 DOM/API 데이터를 GfaReport로 변환.
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import date

logger = logging.getLogger(__name__)


# ── 데이터 모델 ──

@dataclass
class GfaCampaignStats:
    name: str
    status: str = ""            # 운영가능/중지 등
    objective: str = ""         # ADVoost 쇼핑, 트래픽 등
    budget: float = 0.0         # 캠페인 예산
    budget_usage: str = ""      # 예산 소진율 (예: "32%")
    impressions: int = 0
    clicks: int = 0
    cost: float = 0.0
    conversions: int = 0
    conv_revenue: float = 0.0
    ctr: float = 0.0
    cpc: float = 0.0
    cpm: float = 0.0
    roas: float = 0.0
    cost_per_result: float = 0.0  # 결과당 비용


@dataclass
class GfaReport:
    account_name: str = ""
    report_date: date = None
    date_from: date = None
    date_to: date = None

    # 요약 지표
    total_impressions: int = 0
    total_clicks: int = 0
    total_ctr: float = 0.0
    total_cost: float = 0.0
    total_conversions: int = 0
    total_conv_revenue: float = 0.0
    total_roas: float = 0.0
    total_cpc: float = 0.0
    total_cpm: float = 0.0
    total_cvr: float = 0.0       # 전환율

    # 캠페인 상세
    campaigns: list = field(default_factory=list)

    # AI 인사이트
    insights: list = field(default_factory=list)


# ── 컬럼 매핑 (한글 → 영문 필드) ──

COLUMN_MAP = {
    # 캠페인명
    "캠페인": "campaign_name",
    "캠페인명": "campaign_name",
    "캠페인 이름": "campaign_name",
    "캠페인이름": "campaign_name",
    # 노출
    "노출수": "impressions",
    "노출": "impressions",
    "광고노출수": "impressions",
    "광고 노출수": "impressions",
    "Imp": "impressions",
    "Impressions": "impressions",
    # 클릭
    "클릭수": "clicks",
    "클릭": "clicks",
    "광고클릭수": "clicks",
    "광고 클릭수": "clicks",
    "Clicks": "clicks",
    # CTR
    "CTR": "ctr",
    "클릭률": "ctr",
    "클릭율": "ctr",
    # 비용
    "광고비": "cost",
    "비용": "cost",
    "집행 광고비": "cost",
    "소진액": "cost",
    "광고비(원)": "cost",
    "총비용": "cost",
    "Cost": "cost",
    "Spend": "cost",
    # CPM
    "CPM": "cpm",
    # 전환
    "전환수": "conversions",
    "전환": "conversions",
    "결과": "conversions",
    "총 전환수": "conversions",
    "Conversions": "conversions",
    # 전환매출
    "전환매출": "conv_revenue",
    "전환매출액": "conv_revenue",
    "전환 매출": "conv_revenue",
    "총 전환매출액": "conv_revenue",
    # CPC
    "CPC": "cpc",
    "클릭당비용": "cpc",
    "클릭당 비용": "cpc",
    # ROAS
    "ROAS": "roas",
    "광고수익률": "roas",
    "광고 수익률": "roas",
    "ROAS(%)": "roas",
}


# ── 안전 변환 ──

def _safe_int(val) -> int:
    """안전한 정수 변환 (한글 단위 제거)."""
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip()
    for unit in ("원", "%", "회", "개", "건", "평균", "₩", "￦"):
        s = s.replace(unit, "")
    s = re.sub(r'[가-힣]+.*$', '', s)
    s = s.replace(",", "").replace(" ", "").strip()
    if not s or s == "-":
        return 0
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def _safe_float(val) -> float:
    """안전한 실수 변환 (한글 단위 제거)."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    for unit in ("원", "%", "회", "개", "건", "평균", "₩", "￦"):
        s = s.replace(unit, "")
    s = re.sub(r'[가-힣]+.*$', '', s)
    s = s.replace(",", "").replace(" ", "").strip()
    if not s or s == "-":
        return 0.0
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


# ── DOM 데이터 파싱 ──

def parse_gfa_dom_data(dom_data: dict, date_from: date, date_to: date) -> GfaReport:
    """스크래핑한 DOM 데이터를 GfaReport로 변환."""
    report = GfaReport(
        date_from=date_from,
        date_to=date_to,
        report_date=date_from,
    )

    kpi = dom_data.get("kpi", {})
    headers = dom_data.get("headers", [])
    campaign_rows = dom_data.get("campaigns", [])

    # KPI 요약 데이터 적용
    if kpi:
        report.total_impressions = _safe_int(kpi.get("impressions"))
        report.total_clicks = _safe_int(kpi.get("clicks"))
        report.total_cost = _safe_float(kpi.get("cost"))
        report.total_conversions = _safe_int(kpi.get("conversions"))
        report.total_conv_revenue = _safe_float(kpi.get("conv_revenue"))
        report.total_ctr = _safe_float(kpi.get("ctr"))
        report.total_roas = _safe_float(kpi.get("roas"))

    # 테이블 데이터 → 캠페인 목록 파싱
    if headers and campaign_rows:
        col_map = {}
        for i, h in enumerate(headers):
            h_clean = h.strip()
            if h_clean in COLUMN_MAP:
                col_map[COLUMN_MAP[h_clean]] = i

        for row in campaign_rows:
            if not row or len(row) < 2:
                continue

            name_idx = col_map.get("campaign_name", 0)
            name = row[name_idx] if name_idx < len(row) else ""

            if not name or name in ("합계", "전체", "총합", "소계"):
                continue

            campaign = GfaCampaignStats(
                name=name,
                impressions=_safe_int(row[col_map["impressions"]]) if "impressions" in col_map and col_map["impressions"] < len(row) else 0,
                clicks=_safe_int(row[col_map["clicks"]]) if "clicks" in col_map and col_map["clicks"] < len(row) else 0,
                cost=_safe_float(row[col_map["cost"]]) if "cost" in col_map and col_map["cost"] < len(row) else 0,
                conversions=_safe_int(row[col_map["conversions"]]) if "conversions" in col_map and col_map["conversions"] < len(row) else 0,
                conv_revenue=_safe_float(row[col_map["conv_revenue"]]) if "conv_revenue" in col_map and col_map["conv_revenue"] < len(row) else 0,
                ctr=_safe_float(row[col_map["ctr"]]) if "ctr" in col_map and col_map["ctr"] < len(row) else 0,
                cpc=_safe_float(row[col_map["cpc"]]) if "cpc" in col_map and col_map["cpc"] < len(row) else 0,
                cpm=_safe_float(row[col_map["cpm"]]) if "cpm" in col_map and col_map["cpm"] < len(row) else 0,
                roas=_safe_float(row[col_map["roas"]]) if "roas" in col_map and col_map["roas"] < len(row) else 0,
            )

            _fill_calculated_fields(campaign)
            report.campaigns.append(campaign)

    # extra 데이터 (상태, 목적, 예산 등) 병합
    extra_list = dom_data.get("extra", [])
    for extra in extra_list:
        for c in report.campaigns:
            if c.name == extra.get("name"):
                c.status = extra.get("status", "")
                c.objective = extra.get("objective", "")
                c.budget = _safe_float(extra.get("budget", 0))
                c.budget_usage = extra.get("budget_usage", "")
                c.cost_per_result = _safe_float(extra.get("cost_per_result", 0))
                break

    # 캠페인으로부터 합계 계산 (KPI가 비어있는 경우)
    _calculate_totals(report)

    # 인사이트 생성
    report.insights = generate_gfa_insights(report)

    return report


# ── API 데이터 파싱 ──

def parse_gfa_api_data(api_data: list, date_from: date, date_to: date) -> GfaReport:
    """캡처된 내부 API 데이터를 GfaReport로 변환."""
    report = GfaReport(
        date_from=date_from,
        date_to=date_to,
        report_date=date_from,
    )

    for item in api_data:
        data = item.get("data")
        url = item.get("url", "")

        if not data:
            continue

        items_list = None
        if isinstance(data, list):
            items_list = data
        elif isinstance(data, dict):
            for key in ("content", "data", "items", "result", "campaigns", "list"):
                if key in data and isinstance(data[key], list):
                    items_list = data[key]
                    break
            if not items_list:
                _try_extract_summary(report, data)

        if items_list:
            for entry in items_list:
                if not isinstance(entry, dict):
                    continue
                name = (
                    entry.get("campaignName")
                    or entry.get("campaign_name")
                    or entry.get("name")
                    or entry.get("adSetName")
                    or entry.get("creativeName")
                    or ""
                )
                if not name:
                    continue

                campaign = GfaCampaignStats(
                    name=name,
                    impressions=_safe_int(entry.get("impressions") or entry.get("impCount") or entry.get("imps")),
                    clicks=_safe_int(entry.get("clicks") or entry.get("clickCount")),
                    cost=_safe_float(entry.get("cost") or entry.get("sales") or entry.get("spend") or entry.get("adCost")),
                    conversions=_safe_int(entry.get("conversions") or entry.get("convCount")),
                    conv_revenue=_safe_float(entry.get("convRevenue") or entry.get("convSales")),
                    ctr=_safe_float(entry.get("ctr")),
                    cpc=_safe_float(entry.get("cpc")),
                    roas=_safe_float(entry.get("roas")),
                )
                _fill_calculated_fields(campaign)
                report.campaigns.append(campaign)

    _calculate_totals(report)
    report.insights = generate_gfa_insights(report)
    return report


def _try_extract_summary(report: GfaReport, data: dict) -> None:
    """API 응답의 dict에서 요약 데이터 추출 시도."""
    mapping = {
        "total_impressions": ["totalImpressions", "totalImpCount", "impressions", "impCount"],
        "total_clicks": ["totalClicks", "totalClickCount", "clicks", "clickCount"],
        "total_cost": ["totalCost", "totalSales", "cost", "sales", "spend"],
        "total_conversions": ["totalConversions", "totalConvCount", "conversions", "convCount"],
        "total_conv_revenue": ["totalConvRevenue", "totalConvSales", "convRevenue", "convSales"],
    }
    for attr, keys in mapping.items():
        for key in keys:
            if key in data and data[key]:
                current = getattr(report, attr, 0)
                if not current:
                    if "float" in str(type(getattr(report, attr))):
                        setattr(report, attr, _safe_float(data[key]))
                    else:
                        setattr(report, attr, _safe_int(data[key]))
                break


# ── 공통 헬퍼 ──

def _fill_calculated_fields(campaign: GfaCampaignStats) -> None:
    """CTR, CPC, CPM, ROAS 계산 (누락 시)."""
    if not campaign.ctr and campaign.impressions > 0:
        campaign.ctr = round(campaign.clicks / campaign.impressions * 100, 2)
    if not campaign.cpc and campaign.clicks > 0:
        campaign.cpc = round(campaign.cost / campaign.clicks, 0)
    if not campaign.cpm and campaign.impressions > 0:
        campaign.cpm = round(campaign.cost / campaign.impressions * 1000, 0)
    if not campaign.roas and campaign.cost > 0 and campaign.conv_revenue > 0:
        campaign.roas = round(campaign.conv_revenue / campaign.cost * 100, 1)
    if not campaign.cost_per_result and campaign.conversions > 0:
        campaign.cost_per_result = round(campaign.cost / campaign.conversions, 0)


def _calculate_totals(report: GfaReport) -> None:
    """캠페인 데이터로부터 합계 계산 (비어있는 경우만)."""
    if not report.campaigns:
        return

    if not report.total_cost:
        report.total_impressions = sum(c.impressions for c in report.campaigns)
        report.total_clicks = sum(c.clicks for c in report.campaigns)
        report.total_cost = sum(c.cost for c in report.campaigns)
        report.total_conversions = sum(c.conversions for c in report.campaigns)
        report.total_conv_revenue = sum(c.conv_revenue for c in report.campaigns)

    if report.total_impressions > 0 and not report.total_ctr:
        report.total_ctr = round(report.total_clicks / report.total_impressions * 100, 2)
    if report.total_clicks > 0 and not report.total_cpc:
        report.total_cpc = round(report.total_cost / report.total_clicks, 0)
    if report.total_impressions > 0 and not report.total_cpm:
        report.total_cpm = round(report.total_cost / report.total_impressions * 1000, 0)
    if report.total_clicks > 0 and not report.total_cvr:
        report.total_cvr = round(report.total_conversions / report.total_clicks * 100, 1)
    if report.total_cost > 0 and not report.total_roas and report.total_conv_revenue > 0:
        report.total_roas = round(report.total_conv_revenue / report.total_cost * 100, 1)


# ── 인사이트 생성 ──

def generate_gfa_insights(report: GfaReport) -> list:
    """GFA 보고서 인사이트 자동 생성 (종합 분석)."""
    insights = []

    if not report.total_cost and not report.campaigns:
        insights.append("데이터가 충분하지 않아 상세 인사이트를 생성할 수 없습니다.")
        return insights

    # ── 1. 핵심 성과 요약 ──
    if report.total_cost > 0:
        cpc = report.total_cpc or (round(report.total_cost / report.total_clicks) if report.total_clicks > 0 else 0)
        cvr = report.total_cvr or (round(report.total_conversions / report.total_clicks * 100, 1) if report.total_clicks > 0 else 0)
        cpm = report.total_cpm or (round(report.total_cost / report.total_impressions * 1000) if report.total_impressions > 0 else 0)

        insights.append(
            f"[핵심 요약] 총 광고비 {report.total_cost:,.0f}원 집행, "
            f"노출 {report.total_impressions:,}회 / 클릭 {report.total_clicks:,}회 / 전환 {report.total_conversions:,}건 달성"
        )

    # ── 2. 효율 지표 분석 ──
    efficiency_parts = []
    if report.total_clicks > 0:
        cpc_val = report.total_cpc or round(report.total_cost / report.total_clicks)
        efficiency_parts.append(f"CPC {cpc_val:,.0f}원")
    if report.total_impressions > 0:
        cpm_val = report.total_cpm or round(report.total_cost / report.total_impressions * 1000)
        ctr_val = report.total_ctr or round(report.total_clicks / report.total_impressions * 100, 2)
        efficiency_parts.append(f"CPM {cpm_val:,.0f}원")
        efficiency_parts.append(f"CTR {ctr_val:.2f}%")
    if report.total_clicks > 0 and report.total_conversions > 0:
        cvr_val = report.total_cvr or round(report.total_conversions / report.total_clicks * 100, 1)
        efficiency_parts.append(f"CVR {cvr_val:.1f}%")

    if efficiency_parts:
        insights.append(f"[효율 지표] {' / '.join(efficiency_parts)}")

    # ── 3. CTR 평가 ──
    ctr_val = report.total_ctr or (round(report.total_clicks / report.total_impressions * 100, 2) if report.total_impressions > 0 else 0)
    if ctr_val > 0:
        if ctr_val >= 1.5:
            ctr_grade = "우수 (업계 평균 상회)"
            ctr_comment = "높은 클릭률은 광고 소재와 타겟팅이 효과적임을 의미합니다."
        elif ctr_val >= 0.8:
            ctr_grade = "양호 (업계 평균 수준)"
            ctr_comment = "평균적인 수준이며, 소재 A/B 테스트로 개선 가능성이 있습니다."
        elif ctr_val >= 0.3:
            ctr_grade = "보통 (개선 여지 있음)"
            ctr_comment = "소재 이미지/문구 변경 또는 타겟 세그먼트 세분화를 검토하세요."
        else:
            ctr_grade = "주의 필요 (업계 평균 하회)"
            ctr_comment = "타겟팅 재설정, 소재 전면 교체, 지면 변경을 권장합니다."
        insights.append(f"[CTR 분석] CTR {ctr_val:.2f}% - {ctr_grade}. {ctr_comment}")

    # ── 4. CPC 평가 ──
    if report.total_clicks > 0:
        cpc_val = report.total_cpc or round(report.total_cost / report.total_clicks)
        if cpc_val > 0:
            if cpc_val <= 200:
                cpc_comment = "매우 효율적인 클릭 단가입니다."
            elif cpc_val <= 500:
                cpc_comment = "양호한 클릭 단가입니다."
            elif cpc_val <= 1000:
                cpc_comment = "보통 수준의 클릭 단가이며, 입찰 전략 최적화로 절감 가능합니다."
            else:
                cpc_comment = "높은 클릭 단가입니다. 입찰가 조정 또는 경쟁이 낮은 타겟 세그먼트를 검토하세요."
            insights.append(f"[CPC 분석] 클릭당 비용 {cpc_val:,.0f}원 - {cpc_comment}")

    # ── 5. 전환 분석 ──
    if report.total_conversions > 0 and report.total_clicks > 0:
        cvr_val = report.total_cvr or round(report.total_conversions / report.total_clicks * 100, 1)
        cpa = round(report.total_cost / report.total_conversions) if report.total_conversions > 0 else 0
        insights.append(
            f"[전환 분석] 전환율 {cvr_val:.1f}%, 전환당 비용(CPA) {cpa:,.0f}원. "
            f"총 {report.total_conversions:,}건 전환 달성"
        )
    elif report.total_clicks > 0 and report.total_conversions == 0:
        insights.append(
            f"[전환 분석] 클릭 {report.total_clicks:,}회 발생했으나 전환이 없습니다. "
            f"랜딩페이지 점검 및 전환 추적 설정을 확인하세요."
        )

    # ── 6. 예산 효율 분석 ──
    for c in report.campaigns:
        if c.budget > 0 and c.cost > 0:
            usage_pct = round(c.cost / c.budget * 100, 1)
            if usage_pct >= 90:
                insights.append(
                    f"[예산 분석] '{c.name}' 예산 {c.budget:,.0f}원 중 {usage_pct:.0f}% 소진 - "
                    f"예산 한도 도달 가능성이 높아 예산 증액을 검토하세요."
                )
            elif usage_pct < 30:
                insights.append(
                    f"[예산 분석] '{c.name}' 예산 {c.budget:,.0f}원 중 {usage_pct:.0f}%만 소진 - "
                    f"입찰가 또는 타겟 범위 확대를 검토하세요."
                )

    # ── 7. 캠페인별 비교 (2개 이상) ──
    if len(report.campaigns) >= 2:
        sorted_by_ctr = sorted(
            [c for c in report.campaigns if c.impressions > 100],
            key=lambda c: c.ctr, reverse=True
        )
        if sorted_by_ctr:
            best = sorted_by_ctr[0]
            worst = sorted_by_ctr[-1]
            if best.name != worst.name:
                insights.append(
                    f"[캠페인 비교] CTR 최고: '{best.name}' ({best.ctr:.2f}%) / "
                    f"CTR 최저: '{worst.name}' ({worst.ctr:.2f}%) - "
                    f"'{best.name}' 캠페인의 소재/타겟 전략을 다른 캠페인에 적용해보세요."
                )

    # ── 8. 액션 아이템 ──
    actions = []
    if ctr_val < 0.5 and report.total_impressions > 1000:
        actions.append("광고 소재(이미지/문구) 교체 및 A/B 테스트")
    if report.total_clicks > 50 and report.total_conversions == 0:
        actions.append("랜딩페이지 전환 경로 점검")
    if report.total_cpc and report.total_cpc > 800:
        actions.append("입찰 전략 재검토 (자동입찰 / 목표CPA)")

    for c in report.campaigns:
        if c.status and "중지" in c.status:
            actions.append(f"중지된 캠페인 '{c.name}' 재개 또는 정리 검토")
            break

    if actions:
        action_text = " / ".join(actions[:4])
        insights.append(f"[추천 액션] {action_text}")

    return insights
