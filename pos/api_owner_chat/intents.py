from dataclasses import dataclass


import re
from dataclasses import dataclass


@dataclass
class IntentResult:
    intent: str
    confidence: float
    entity: str | None = None
    slot: str | None = None
    number: int | None = None


def _normalize_text(text: str) -> str:
    text = (text or "").lower().strip()

    replacements = {
        # tetun / typo / indo / english normalization
        "oinsá": "oinsa",
        "ne'ebé": "ne'ebe",
        "fa'an": "faan",
        "ki'ik": "kiik",
        "menipis": "kiik",
        "stok menipis": "stok kiik",
        "produk": "produtu",
        "barang": "produtu",
        "sales": "vendas",
        "income": "reseita",
        "revenue": "reseita",
        "profit": "lukru",
        "laba": "lukru",
        "untung": "lukru",
        "expense": "despeza",
        "pengeluaran": "despeza",
        "diskon": "diskuentu",
        "discount": "diskuentu",
        "report": "relatoriu",
        "laporan": "relatoriu",
        "stok habis": "stok hotu ona",
        "produk habis": "produtu hotu ona",
        "out of stock": "stok hotu ona",
        "stock alert": "stok kiik",
        "stock movement": "movement stok",
        "inventory movement": "movement inventariu",
        "pergerakan stok": "movement stok",
        "mutasi stok": "movement stok",
        "stock adjustment": "adjustment stok",
        "take away": "takeaway",
        "take-away": "takeaway",
        "pick up": "pickup",
        "dinein": "dine in",
        "qris": "qris",
    }

    text = re.sub(r"[^\w\s<>/=.-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def _extract_number(text: str) -> int | None:
    match = re.search(r"(\d+)", text)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return None
    return None


def _token_set(text: str) -> set[str]:
    return set((text or "").split())


def _fuzzy_contains(text: str, phrase: str, min_overlap_ratio: float = 0.72) -> bool:
    """
    Lightweight fuzzy matcher.
    Cocok untuk typo ringan dan susunan kata yang sedikit beda.
    """
    if not text or not phrase:
        return False

    if phrase in text:
        return True

    t_words = _token_set(text)
    p_words = _token_set(phrase)

    if not p_words:
        return False

    overlap = len(t_words & p_words)
    ratio = overlap / max(1, len(p_words))

    return ratio >= min_overlap_ratio


def _contains_any(text: str, keywords: list[str], fuzzy: bool = True) -> bool:
    for k in keywords:
        if k in text:
            return True
        if fuzzy and _fuzzy_contains(text, k):
            return True
    return False


def _extract_stock_entity(text: str) -> str | None:
    candidates = [
        r"^stok\s+(.+)$",
        r"^stok produtu\s+(.+)$",
        r"^stok produk\s+(.+)$",
        r"^stock\s+(.+)$",
    ]

    blocked = {
        "kiik", "hotu ona", "minimum", "menus husi", "less than",
        "below", "alert", "movement", "inventariu", "stok"
    }

    for pattern in candidates:
        m = re.match(pattern, text)
        if m:
            entity = m.group(1).strip()
            if entity and entity not in blocked and len(entity) >= 2:
                return entity
    return None


def _detect_order_type(text: str) -> str | None:
    mapping = {
        "DINE_IN": [
            "dine in", "makan di tempat", "haan iha fatin", "eat in"
        ],
        "DELIVERY": [
            "delivery", "antar", "delivery order", "kirim"
        ],
        "TAKEAWAY": [
            "takeaway", "take away", "bungkus", "take out", "takeout"
        ],
        "PICKUP": [
            "pickup", "pick up", "ambil sendiri", "self pickup"
        ],
    }

    for slot, aliases in mapping.items():
        if _contains_any(text, aliases, fuzzy=True):
            return slot
    return None


def detect_intent(message: str) -> IntentResult:
    t = _normalize_text(message)

    if not t:
        return IntentResult("fallback", 0.10)

    number = _extract_number(t)

    # =========================================================
    # HELP
    # =========================================================
    if _contains_any(t, [
        "cara",
        "bagaimana",
        "gimana",
        "help",
        "bantuan",
        "tutorial",
        "oinsa",
        "ajuda",
        "hatudu hau",
        "ajuda hau",
    ]):
        return IntentResult("help", 0.92)

    # =========================================================
    # WHY PROFIT DOWN
    # =========================================================
    if _contains_any(t, [
        "tanba sa lukru tun",
        "kenapa lukru tun",
        "mengapa lukru tun",
        "why lukru down",
        "lukru tun",
        "profit turun",
        "kenapa profit turun",
    ]):
        return IntentResult("why_profit_down", 0.96)

    # =========================================================
    # PROMO RECOMMENDATION
    # =========================================================
    if _contains_any(t, [
        "rekomendasaun promo",
        "rekomendasi promo",
        "saran promo",
        "promo recommendation",
        "promo saida",
        "promo untuk produtu lambat",
        "promo buat produk lambat",
    ]):
        return IntentResult("promo_recommendation", 0.95)

    # =========================================================
    # COMPARE PERIOD
    # =========================================================
    if _contains_any(t, [
        "kompara",
        "bandingkan",
        "compare",
        "dibanding",
        "minggu ini dengan minggu lalu",
        "bulan ini dengan bulan lalu",
        "kompara semana ida ne e ho semana kotuk",
        "kompara fulan ida ne e ho fulan kotuk",
    ]):
        return IntentResult("compare_period", 0.94)

    # =========================================================
    # PAYMENT METHOD TOP
    # =========================================================
    if _contains_any(t, [
        "metodu pagamentu neebe barak liu",
        "metode pembayaran paling banyak",
        "payment method paling banyak",
        "top payment method",
        "metode bayar terbanyak",
        "cara bayar paling banyak",
    ]):
        return IntentResult("payment_method_top", 0.95)

    # =========================================================
    # CASH VS TRANSFER
    # =========================================================
    if _contains_any(t, [
        "cash vs transfer",
        "cash ho transfer",
        "cash vs non cash",
        "cash vs qris",
        "cash lawan transfer",
        "selu cash ho transfer",
    ]):
        return IntentResult("cash_vs_transfer", 0.95)

    # =========================================================
    # BUSIEST HOURS
    # =========================================================
    if _contains_any(t, [
        "oras neebe movimentu liu",
        "jam paling ramai",
        "jam ramai",
        "busiest hour",
        "busiest hours",
        "peak hour",
        "jam tersibuk",
    ]):
        return IntentResult("busiest_hours", 0.95)

    # =========================================================
    # DELIVERY FEE
    # =========================================================
    if _contains_any(t, [
        "taxa delivery",
        "delivery fee",
        "ongkir",
        "ongkos kirim",
        "biaya delivery",
        "fee delivery",
    ]):
        return IntentResult("delivery_fee_summary", 0.95)

    # =========================================================
    # DISCOUNT
    # =========================================================
    if _contains_any(t, [
        "diskuentu",
        "potongan harga",
        "discount",
        "diskon",
    ]):
        return IntentResult("discount_summary", 0.93)

    # =========================================================
    # SALES BY TYPE
    # =========================================================
    order_type = _detect_order_type(t)
    if order_type:
        sales_words = [
            "reseita", "vendas", "sales", "income", "penjualan", "omzet",
            "net sales", "revenue", "total"
        ]
        if _contains_any(t, sales_words, fuzzy=True) or order_type:
            return IntentResult("sales_by_type", 0.94, slot=order_type)

    # =========================================================
    # STOCK ALERT
    # =========================================================
    if _contains_any(t, [
        "stok kiik",
        "stok minimum",
        "min stock",
        "low stock",
        "alert stok",
        "stok minimum",
    ]):
        return IntentResult("stock_alert", 0.96)

    # =========================================================
    # STOCK OUT
    # =========================================================
    if _contains_any(t, [
        "produtu hotu ona",
        "stok hotu ona",
        "stok kosong",
        "produk habis",
        "stok habis",
        "out of stock",
    ]):
        return IntentResult("stock_out", 0.96)

    # =========================================================
    # STOCK THRESHOLD
    # =========================================================
    if _contains_any(t, [
        "stok menus husi",
        "stok kurang dari",
        "stok kurang",
        "stok di bawah",
        "stock below",
        "stock less than",
        "stok <=",
        "stock <=",
    ]):
        return IntentResult("stock_threshold", 0.93, number=number)

    # =========================================================
    # INVENTORY MOVEMENT
    # =========================================================
    if _contains_any(t, [
        "movement inventariu",
        "movement stok",
        "inventory movement",
        "pergerakan stok",
        "mutasi",
        "stock movement",
    ]):
        return IntentResult("inventory_movement", 0.94)

    # =========================================================
    # MOVEMENT ADJUSTMENT
    # =========================================================
    if _contains_any(t, [
        "movement adjustment",
        "adjustment movement",
        "adjustment stok",
        "stock adjustment",
        "koreksi stok",
    ]):
        return IntentResult("movement_adjustment", 0.94)

    # =========================================================
    # STOCK ITEM
    # =========================================================
    entity = _extract_stock_entity(t)
    if entity:
        return IntentResult("stock_item", 0.89, entity=entity)

    # =========================================================
    # TOP PRODUCTS
    # =========================================================
    if _contains_any(t, [
        "top produtu",
        "produtu neebe faan barak liu",
        "produk paling laku",
        "best seller",
        "bestseller",
        "top products",
        "produk terlaris",
    ]):
        return IntentResult("top_products", 0.95)

    # =========================================================
    # MARGIN
    # =========================================================
    if _contains_any(t, [
        "margem",
        "margin",
        "gross margin",
        "profit margin",
    ]):
        return IntentResult("margin_summary", 0.94)

    # =========================================================
    # PROFIT
    # =========================================================
    if _contains_any(t, [
        "lukru",
        "profit",
        "laba",
        "rugi",
        "untung",
    ]):
        return IntentResult("profit_summary", 0.94)

    # =========================================================
    # EXPENSE
    # =========================================================
    if _contains_any(t, [
        "despeza",
        "expense",
        "pengeluaran",
        "biaya",
        "beban",
    ]):
        if _contains_any(t, ["top", "terbesar", "aas liu"], fuzzy=False):
            return IntentResult("expense_top", 0.92)
        return IntentResult("expense_summary", 0.94)

    # =========================================================
    # ORDERS / AOV
    # =========================================================
    if _contains_any(t, [
        "total tranzasaun",
        "jumlah transaksi",
        "order count",
        "berapa transaksi",
        "rata rata transaksi",
        "average order",
        "avg order",
        "total order",
        "media pedido",
        "media order",
        "hira tranzasaun",
        "total pedido",
    ]):
        return IntentResult("orders_kpi", 0.90)

    # =========================================================
    # SALES / INCOME
    # =========================================================
    if _contains_any(t, [
        "reseita",
        "vendas",
        "income",
        "sales",
        "penjualan",
        "omzet",
        "net sales",
        "pendapatan",
        "revenue",
    ]):
        return IntentResult("sales_summary", 0.94)

    # =========================================================
    # CUSTOMER
    # =========================================================
    if _contains_any(t, [
        "top customer",
        "pelanggan terbaik",
        "customer terbaik",
        "kliente diak liu",
    ]):
        return IntentResult("top_customers", 0.82)

    if _contains_any(t, [
        "member points",
        "poin customer",
        "points customer",
        "pontus customer",
        "pontus member",
    ]):
        return IntentResult("customer_points", 0.82)

    return IntentResult("fallback", 0.30)