import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional


HELP_TOPICS = {
    "tambah_produk": {
        "title": "Oinsá aumenta produtu",
        "text": (
            "🧾 Oinsá aumenta produtu:\n"
            "1) Loke menu Produtu\n"
            "2) Klik botoe ➕ Aumenta\n"
            "3) Hatama: Naran, Barcode, SKU (opsional), Folin Fa'an, Folin Sosa, Stok\n"
            "4) Hili Kategoria, Unidade, Supplier (opsional)\n"
            "5) Rai\n\n"
            "Dika sira:\n"
            "• Barcode tenke úniku\n"
            "• Folin sosa importante atu kalkula margem\n"
            "• Hatama min stock atu bele monitoriza stok ki'ik"
        ),
        "keywords": [
            "aumenta produtu", "oinsa aumenta produtu", "hatama produtu", "halo produtu",
            "produtu foun", "aumenta sasán", "hatama sasán",
            "tambah produk", "cara tambah produk", "input produk", "buat produk",
            "produk baru", "tambah barang", "input barang"
        ],
        "suggestions": ["edit produtu", "hapus produtu", "aumenta kategoria", "aumenta supplier"],
    },
    "edit_produk": {
        "title": "Oinsá edit produtu",
        "text": (
            "✏️ Oinsá edit produtu:\n"
            "1) Loke menu Produtu\n"
            "2) Buka produtu ne'ebé ita buka\n"
            "3) Klik botoe Edit\n"
            "4) Troka dadus ne'ebé presiza\n"
            "5) Rai"
        ),
        "keywords": [
            "edit produtu", "oinsa edit produtu", "troka produtu", "update produtu",
            "edit produk", "cara edit produk", "ubah produk", "update produk"
        ],
        "suggestions": ["aumenta produtu", "hapus produtu"],
    },
    "hapus_produk": {
        "title": "Oinsá hamoos produtu",
        "text": (
            "🗑️ Oinsá hamoos produtu:\n"
            "1) Loke menu Produtu\n"
            "2) Buka produtu\n"
            "3) Klik botoe Hamoos\n"
            "4) Konfirma\n\n"
            "Nota:\n"
            "• Produtu ne'ebé uza ona iha tranzasaun di'ak liu la presiza hamoos permanenti\n"
            "• Seguru liu maka halo produtu sai la ativu se presiza"
        ),
        "keywords": [
            "hamos produtu", "hamoos produtu", "oinsa hamoos produtu", "delete produtu", "remove produtu",
            "hapus produk", "cara hapus produk", "delete produk", "remove produk"
        ],
        "suggestions": ["edit produtu", "aumenta produtu"],
    },
    "retur_barang": {
        "title": "Oinsá halo retur sasán",
        "text": (
            "🔁 Oinsá halo retur sasán:\n"
            "1) Loke menu Retur / Product Return\n"
            "2) Hili invoice / order\n"
            "3) Hili item no qty ne'ebé atu retur\n"
            "4) Hatama razaun / nota\n"
            "5) Rai\n\n"
            "Nota:\n"
            "• Qty retur labele liu hosi qty ne'ebé fa'an tiha ona\n"
            "• Sistema sei ajusta stok bainhira retur prosesa"
        ),
        "keywords": [
            "retur sasán", "oinsa retur", "return sasán", "product return", "retur produtu",
            "retur barang", "cara retur", "return barang", "retur produk"
        ],
        "suggestions": ["relatóriu", "stock adjustment"],
    },
    "cetak_struk": {
        "title": "Oinsá imprime resibu",
        "text": (
            "🧾 Oinsá imprime resibu:\n"
            "1) Remata tranzasaun\n"
            "2) Haree katak printer thermal konekta ona\n"
            "3) Klik Print / Imprime\n\n"
            "Se la konsege:\n"
            "• Haree pairing Bluetooth\n"
            "• Haree permission Android\n"
            "• Haree medida surat 58mm/80mm tuir setting"
        ),
        "keywords": [
            "imprime resibu", "cetak struk", "print struk", "printer", "thermal", "print receipt"
        ],
        "suggestions": ["bank transfer qris", "relatóriu"],
    },
    "tambah_kategori": {
        "title": "Oinsá aumenta kategoria",
        "text": (
            "🏷️ Oinsá aumenta kategoria:\n"
            "1) Loke menu Kategoria\n"
            "2) Klik ➕ Aumenta\n"
            "3) Hatama naran kategoria\n"
            "4) Rai"
        ),
        "keywords": [
            "aumenta kategoria", "halo kategoria", "hatama kategoria",
            "tambah kategori", "buat kategori", "input kategori"
        ],
        "suggestions": ["aumenta produtu"],
    },
    "tambah_supplier": {
        "title": "Oinsá aumenta supplier",
        "text": (
            "🚚 Oinsá aumenta supplier:\n"
            "1) Loke menu Supplier\n"
            "2) Klik ➕ Aumenta\n"
            "3) Hatama naran, phone, email, address\n"
            "4) Rai"
        ),
        "keywords": [
            "supplier", "aumenta supplier", "halo supplier", "hatama supplier",
            "tambah supplier", "buat supplier", "input supplier"
        ],
        "suggestions": ["sosa", "aumenta produtu"],
    },
    "stok_opname": {
        "title": "Oinsá halo stok opname",
        "text": (
            "📦 Oinsá halo stok opname:\n"
            "1) Loke menu Inventory Count / Stok Opname\n"
            "2) Halo count foun\n"
            "3) Hatama stok fiziku\n"
            "4) Rai\n"
            "5) Haree diferensa\n"
            "6) Halo adjustment se presiza"
        ),
        "keywords": [
            "stok opname", "stock opname", "inventory count", "sura stok", "hitung stok"
        ],
        "suggestions": ["stock adjustment", "relatóriu"],
    },
    "stock_adjustment": {
        "title": "Oinsá halo stock adjustment",
        "text": (
            "⚖️ Oinsá halo stock adjustment:\n"
            "1) Loke menu Stock Adjustment\n"
            "2) Hili produtu\n"
            "3) Hatama stok foun / diferensa\n"
            "4) Hatama razaun adjustment\n"
            "5) Rai\n\n"
            "Ezemplu razaun:\n"
            "• sasán aat\n"
            "• lakon\n"
            "• korrije dadus\n"
            "• rezultadu opname"
        ),
        "keywords": [
            "stock adjustment", "adjustment", "koreksaun stok", "troka stok", "ubah stok"
        ],
        "suggestions": ["stok opname", "retur sasán"],
    },
    "pembelian": {
        "title": "Oinsá hatama sosa",
        "text": (
            "🛒 Oinsá hatama sosa:\n"
            "1) Loke menu Purchases\n"
            "2) Klik aumenta sosa\n"
            "3) Hili supplier\n"
            "4) Aumenta item, qty, cost price\n"
            "5) Rai\n\n"
            "Nota:\n"
            "• Sosa normaliza aumenta stok\n"
            "• Haree folin sosa loos tanba ne'e afeta lukru"
        ),
        "keywords": [
            "sosa", "purchase", "hatama sosa", "halo sosa",
            "pembelian", "input pembelian", "buat pembelian"
        ],
        "suggestions": ["aumenta supplier", "relatóriu"],
    },
    "customer_member": {
        "title": "Oinsá aumenta customer/member",
        "text": (
            "👥 Oinsá aumenta customer/member:\n"
            "1) Loke menu Customer\n"
            "2) Klik ➕ Aumenta\n"
            "3) Hatama naran, phone, email, hela fatin\n"
            "4) Rai\n\n"
            "Se membership ativu:\n"
            "• Customer bele halibur pontus\n"
            "• Istória sosa bele monitoriza"
        ),
        "keywords": [
            "customer", "member", "aumenta customer", "aumenta member", "halo customer",
            "tambah customer", "tambah member", "buat customer"
        ],
        "suggestions": ["discount", "relatóriu"],
    },
    "discount": {
        "title": "Oinsá uza diskuentu",
        "text": (
            "🏷️ Oinsá uza diskuentu:\n"
            "1) Aumenta item ba cart\n"
            "2) Hili diskuentu item ka diskuentu tranzasaun\n"
            "3) Hatama nominal / pursentu\n"
            "4) Rai depois kontinua selu\n\n"
            "Nota:\n"
            "• Diskuentu boot liu bele hamenus margem"
        ),
        "keywords": [
            "diskuentu", "discount", "oinsa uza diskuentu", "potongan harga", "cara pakai diskon"
        ],
        "suggestions": ["customer member", "relatóriu"],
    },
    "bank_transfer_qris": {
        "title": "Pagamentu transfer / QRIS",
        "text": (
            "🏦 Pagamentu Transfer / QRIS:\n"
            "1) Iha tempu checkout hili métodu selu\n"
            "2) Hili Transfer ka QRIS\n"
            "3) Hatudu konta bankária / QR code\n"
            "4) Rai prova pagamentu se feature ativu\n"
            "5) Remata tranzasaun depois pagamentu valida"
        ),
        "keywords": [
            "qris", "transfer", "bank transfer", "pagamentu qris", "selu transfer",
            "pembayaran qris", "bayar transfer"
        ],
        "suggestions": ["imprime resibu", "relatóriu"],
    },
    "laporan": {
        "title": "Oinsá haree relatóriu",
        "text": (
            "📊 Relatóriu ne'ebé normalmente iha:\n"
            "• Relatóriu vendas\n"
            "• Relatóriu despeza\n"
            "• Sumáriu lukru\n"
            "• Produtu sira ne'ebé fa'an barak liu\n"
            "• Alerta stok\n"
            "• Relatóriu tranzasaun\n"
            "• Relatóriu retur\n\n"
            "Uza filtru data atu rezultadu sai loos liu."
        ),
        "keywords": [
            "relatóriu", "report", "sales report", "relatoriu vendas", "laporan", "laporan penjualan", "profit"
        ],
        "suggestions": ["sosa", "retur sasán", "stok opname"],
    },
}


HELP_FALLBACK_TEXT = (
    "🧾 Ajuda POS\n"
    "Ezemplu pergunta sira ne'ebé bele husu:\n"
    "• oinsa aumenta produtu\n"
    "• oinsa edit produtu\n"
    "• oinsa hamoos produtu\n"
    "• oinsa halo retur sasán\n"
    "• oinsa imprime resibu\n"
    "• oinsa aumenta kategoria\n"
    "• oinsa aumenta supplier\n"
    "• oinsa halo stok opname\n"
    "• oinsa halo stock adjustment\n"
    "• oinsa hatama sosa\n"
    "• oinsa aumenta customer\n"
    "• oinsa uza diskuentu\n"
    "• pagamentu qris\n"
    "• oinsa haree relatóriu"
)


SYNONYMS = {
    # Tetun
    "sasán": "produtu",
    "sasan": "produtu",
    "artiklu": "produtu",
    "halo": "aumenta",
    "hamoos": "hapus",
    "hamos": "hapus",
    "imprime": "cetak",
    "resibu": "struk",
    "fila": "retur",
    "troka": "edit",
    "kategoria": "kategori",
    "sura": "hitung",
    "despeza": "expense",
    "lukru": "profit",
    "selu": "bayar",
    "sosa": "pembelian",

    # Indonesia / English
    "barang": "produk",
    "item": "produk",
    "buat": "tambah",
    "hapuskan": "hapus",
    "print": "cetak",
    "receipt": "struk",
    "return": "retur",
    "customer": "customer",
    "member": "member",
}


def normalize_text(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    parts = []
    for token in text.split():
        parts.append(SYNONYMS.get(token, token))
    return " ".join(parts)


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def get_topic_suggestions(current_key: Optional[str] = None, limit: int = 4) -> List[str]:
    suggestions = []

    if current_key and current_key in HELP_TOPICS:
        raw = HELP_TOPICS[current_key].get("suggestions", [])
        for item in raw:
            suggestions.append(item)

    if not suggestions:
        suggestions = [
            "oinsa aumenta produtu",
            "oinsa imprime resibu",
            "oinsa halo stok opname",
            "oinsa haree relatóriu",
        ]

    return suggestions[:limit]


def match_local_help(message: str) -> Optional[Dict]:
    """
    Return:
    {
        "topic_key": ...,
        "title": ...,
        "text": ...,
        "source": "local",
        "confidence": float,
        "suggestions": [...]
    }
    """
    text = normalize_text(message)
    if not text:
        return None

    best_key = None
    best_score = 0.0

    for topic_key, topic in HELP_TOPICS.items():
        variants = topic.get("keywords", [])
        for variant in variants:
            v = normalize_text(variant)

            if v in text:
                score = 0.98
            elif text in v:
                score = 0.95
            else:
                score = similarity(text, v)

                text_words = set(text.split())
                variant_words = set(v.split())
                overlap = len(text_words & variant_words)
                if overlap:
                    score = max(score, min(0.90, 0.45 + (0.15 * overlap)))

            if score > best_score:
                best_score = score
                best_key = topic_key

    if not best_key:
        return None

    if best_score < 0.62:
        return None

    topic = HELP_TOPICS[best_key]
    return {
        "topic_key": best_key,
        "title": topic["title"],
        "text": topic["text"],
        "source": "local",
        "confidence": round(best_score, 3),
        "suggestions": get_topic_suggestions(best_key),
    }


def get_fallback_help_payload() -> Dict:
    return {
        "title": "Ajuda POS",
        "text": HELP_FALLBACK_TEXT,
        "source": "fallback",
        "confidence": 0.0,
        "suggestions": get_topic_suggestions(),
    }