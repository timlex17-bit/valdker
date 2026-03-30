import logging
from typing import Optional, Dict

from django.conf import settings

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
Anda adalah asisten help desk untuk aplikasi ValdKerPOS.
Tugas Anda hanya membantu user memahami cara menggunakan fitur POS.

Aturan:
1. Jawab hanya topik yang berkaitan dengan penggunaan aplikasi POS.
2. Jangan mengarang data transaksi, stok, customer, atau laporan.
3. Jika pertanyaan meminta data bisnis nyata, arahkan user ke menu laporan/transaksi yang sesuai.
4. Jangan pernah membahas data toko lain.
5. Jawab dalam Bahasa Indonesia yang singkat, jelas, dan praktis.
6. Jika tidak yakin, katakan dengan jujur bahwa Anda tidak yakin dan beri saran menu yang relevan.
7. Fokus pada langkah-langkah penggunaan aplikasi.
"""


def _build_user_prompt(message: str, user=None) -> str:
    username = getattr(user, "username", "") or "-"
    role = getattr(user, "role", "") or "-"
    shop_name = "-"
    shop_code = "-"

    shop = getattr(user, "shop", None)
    if shop:
        shop_name = getattr(shop, "name", "-") or "-"
        shop_code = getattr(shop, "code", "-") or "-"

    return f"""
Context User:
- username: {username}
- role: {role}
- shop_name: {shop_name}
- shop_code: {shop_code}

Pertanyaan user:
{message}

Format jawaban:
- judul singkat
- isi penjelasan langkah demi langkah
- beri tips jika relevan
"""


def ask_help_ai(message: str, user=None) -> Optional[Dict]:
    api_key = getattr(settings, "OPENAI_API_KEY", None)
    model = getattr(settings, "OPENAI_HELP_MODEL", "gpt-5-mini")

    if not api_key:
        logger.info("OPENAI_API_KEY not configured, skipping AI fallback.")
        return None

    if OpenAI is None:
        logger.warning("openai package is not installed.")
        return None

    try:
        client = OpenAI(api_key=api_key)

        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(message, user=user)},
            ],
        )

        text = (getattr(response, "output_text", "") or "").strip()
        if not text:
            return None

        title = "Bantuan ValdKerPOS"
        first_line = text.splitlines()[0].strip() if text.splitlines() else ""
        if first_line and len(first_line) <= 80:
            title = first_line.replace("#", "").strip()

        return {
            "title": title,
            "text": text,
            "source": "ai",
            "confidence": 0.70,
            "suggestions": [
                "cara tambah produk",
                "cara cetak struk",
                "cara stok opname",
                "cara lihat laporan",
            ],
        }

    except Exception as exc:
        logger.exception("AI fallback failed: %s", exc)
        return None