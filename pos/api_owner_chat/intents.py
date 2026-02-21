from dataclasses import dataclass


@dataclass
class IntentResult:
    intent: str
    confidence: float
    entity: str | None = None  # product/customer name if any


def detect_intent(message: str) -> IntentResult:
    """
    Rule-based intent detector.
    Output confidence tinggi hanya kalau keyword kuat.
    """
    t = (message or "").lower().strip()

    # STOCK
    if any(k in t for k in ["stok menipis", "stock alert", "min_stock", "stok minimum"]):
        return IntentResult("stock_alert", 0.95)
    if any(k in t for k in ["produk habis", "stok habis", "out of stock"]):
        return IntentResult("stock_out", 0.92)
    if any(k in t for k in ["inventory movement", "mutasi", "pergerakan stok", "stock movement"]):
        return IntentResult("inventory_movement", 0.92)
    if t.startswith("stok ") or "stok produk" in t:
        # contoh: "stok nasi goreng"
        entity = t.replace("stok produk", "").replace("stok", "").strip()
        if entity:
            return IntentResult("stock_item", 0.85, entity=entity)

    # PRODUCTS
    if any(k in t for k in ["top produk", "produk paling laku", "best seller", "bestseller"]):
        return IntentResult("top_products", 0.92)

    # PROFIT
    if any(k in t for k in ["profit", "laba", "rugi"]):
        return IntentResult("profit_summary", 0.92)

    # EXPENSE
    if any(k in t for k in ["expense", "pengeluaran", "biaya"]):
        if "top" in t:
            return IntentResult("expense_top", 0.90)
        return IntentResult("expense_summary", 0.92)

    # SALES / INCOME
    if any(k in t for k in ["income", "sales", "penjualan", "omzet", "net sales"]):
        return IntentResult("sales_summary", 0.92)

    # ORDERS / AOV
    if any(k in t for k in ["total transaksi", "jumlah transaksi", "order count", "berapa transaksi", "rata-rata transaksi", "average order"]):
        return IntentResult("orders_kpi", 0.88)

    # CUSTOMER (optional)
    if any(k in t for k in ["top customer", "pelanggan terbaik"]):
        return IntentResult("top_customers", 0.80)
    if any(k in t for k in ["member points", "poin customer", "points customer"]):
        return IntentResult("customer_points", 0.80)
