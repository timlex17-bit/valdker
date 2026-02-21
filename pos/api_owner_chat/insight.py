from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal


@dataclass
class DateRangeLike:
    start: object
    end: object


def previous_period(dr) -> DateRangeLike:
    """
    Previous period with the same duration:
    [prev_start, prev_end) where prev_end = dr.start
    """
    delta = dr.end - dr.start
    prev_end = dr.start
    prev_start = dr.start - delta
    return DateRangeLike(start=prev_start, end=prev_end)


def compare_period(dr, queries):
    """
    Compare this period vs previous period (same length).
    Returns dict ready for reply formatting.
    """
    prev_dr = previous_period(dr)

    this_sales = queries.sales_summary(dr)
    this_profit = queries.profit_summary(dr)
    this_margin = queries.margin_summary(dr)

    prev_sales = queries.sales_summary(prev_dr)
    prev_profit = queries.profit_summary(prev_dr)
    prev_margin = queries.margin_summary(prev_dr)

    def d(x):
        try:
            return Decimal(str(x))
        except Exception:
            return Decimal("0.00")

    return {
        "this": {
            "sales": this_sales,
            "profit": this_profit,
            "margin": this_margin,
        },
        "prev": {
            "sales": prev_sales,
            "profit": prev_profit,
            "margin": prev_margin,
        },
        "delta": {
            "sales": d(this_sales["net_sales"]) - d(prev_sales["net_sales"]),
            "profit": d(this_profit["profit"]) - d(prev_profit["profit"]),
            "expense": d(this_profit["expense"]) - d(prev_profit["expense"]),
            "margin_pct": d(this_margin["margin_pct"]) - d(prev_margin["margin_pct"]),
        }
    }


def why_profit_down(dr, queries):
    """
    Explain profit decrease using simple, reliable rules.
    """
    cmp = compare_period(dr, queries)

    this_profit = cmp["this"]["profit"]["profit"]
    prev_profit = cmp["prev"]["profit"]["profit"]

    if this_profit >= prev_profit:
        return {
            "status": "not_down",
            "text": "Profit tidak turun pada periode ini (dibanding periode sebelumnya).",
            "cmp": cmp
        }

    this_sales = cmp["this"]["sales"]["net_sales"]
    prev_sales = cmp["prev"]["sales"]["net_sales"]
    this_exp = cmp["this"]["profit"]["expense"]
    prev_exp = cmp["prev"]["profit"]["expense"]
    this_margin_pct = cmp["this"]["margin"]["margin_pct"]
    prev_margin_pct = cmp["prev"]["margin"]["margin_pct"]

    reasons = []

    if this_sales < prev_sales:
        reasons.append("Penjualan turun dibanding periode sebelumnya.")
    if this_exp > prev_exp:
        reasons.append("Expense naik dibanding periode sebelumnya.")
    if this_margin_pct < prev_margin_pct:
        reasons.append("Margin turun (harga jual/discount/cost mempengaruhi).")

    if not reasons:
        reasons.append("Ada kombinasi faktor (sales, expense, atau margin).")

    txt = "📉 Profit turun. Kemungkinan penyebab:\n" + "\n".join([f"• {r}" for r in reasons])

    return {
        "status": "down",
        "text": txt,
        "cmp": cmp
    }


def promo_recommendation(dr, queries):
    """
    Simple promo ideas:
    - Promote top sellers (upsell/bundle)
    - Promote high-stock items (clearance)
    """
    top = queries.top_products(dr)
    high_stock = queries.high_stock_products(limit=5)

    ideas = []
    if top:
        ideas.append("🔥 Promo Upsell/Bundle untuk best seller:")
        for i, it in enumerate(top[:3], start=1):
            ideas.append(f"{i}. {it['name']} — bisa bundle + minuman / add-on")

    if high_stock:
        ideas.append("\n📦 Clearance ringan untuk stok tinggi:")
        for i, it in enumerate(high_stock[:3], start=1):
            ideas.append(f"{i}. {it['name']} — stok {it['stock']} (diskon kecil 5–10%)")

    if not ideas:
        ideas = ["Belum ada cukup data untuk rekomendasi promo pada periode ini."]

    return "\n".join(ideas)