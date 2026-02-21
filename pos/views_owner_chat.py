import logging
from datetime import timedelta

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from pos.permissions import IsOwnerOrManager
from pos.serializers_owner_chat import OwnerChatRequestSerializer
from pos.api_owner_chat.intents import detect_intent
from pos.api_owner_chat.utils import parse_date_range
from pos.api_owner_chat import queries

logger = logging.getLogger(__name__)


class OwnerChatAPIView(APIView):
    permission_classes = [IsOwnerOrManager]

    # Optional: supaya GET tidak 405 di browser
    def get(self, request):
        return Response(
            {
                "detail": "Use POST JSON: {\"message\":\"income hari ini\"} "
                          "with Authorization: Token <token>"
            },
            status=status.HTTP_200_OK
        )

    def post(self, request):
        ser = OwnerChatRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        message = ser.validated_data["message"].strip()

        intent_res = detect_intent(message)
        range_label, dr = parse_date_range(message)

        # timezone safe inclusive end
        to_dt_inclusive = timezone.localtime(dr.end) - timedelta(microseconds=1)

        meta = {
            "intent": intent_res.intent,
            "confidence": intent_res.confidence,
            "range": range_label,
            "from": timezone.localtime(dr.start).date().isoformat(),
            "to": to_dt_inclusive.date().isoformat(),
        }

        if intent_res.intent == "unknown":
            reply = (
                "Saya belum mengerti. Coba:\n"
                "• income hari ini\n"
                "• sales 7 hari terakhir\n"
                "• expense bulan ini\n"
                "• profit kemarin\n"
                "• top produk bulan ini\n"
                "• stok menipis\n"
                "• inventory movement hari ini"
            )
            return Response(
                {"reply_text": reply, "cards": [], "links": [], "meta": meta},
                status=status.HTTP_200_OK
            )

        try:
            # ==============================
            # SALES / INCOME
            # ==============================
            if intent_res.intent in ("sales_summary", "orders_kpi"):
                r = queries.sales_summary(dr)

                if r["orders"] == 0:
                    reply = (
                        f"📊 Sales ({meta['from']} → {meta['to']})\n"
                        "Belum ada transaksi PAID pada range ini."
                    )
                    cards = [
                        {"label": "Orders", "value": "0"},
                        {"label": "Net Sales", "value": "$0.00"},
                        {"label": "Avg Order", "value": "$0.00"},
                    ]
                else:
                    reply = (
                        f"📊 Sales ({meta['from']} → {meta['to']})\n"
                        f"Net Sales: {queries.money(r['net_sales'])}\n"
                        f"Orders: {r['orders']}\n"
                        f"Avg Order: {queries.money(r['aov'])}"
                    )
                    cards = [
                        {"label": "Net Sales", "value": queries.money(r["net_sales"])},
                        {"label": "Orders", "value": str(r["orders"])},
                        {"label": "Avg Order", "value": queries.money(r["aov"])},
                    ]

                links = [{
                    "title": "Buka Sales Report",
                    "url": f"/admin/reports/sales/?from={meta['from']}&to={meta['to']}"
                }]

                return Response(
                    {"reply_text": reply, "cards": cards, "links": links, "meta": meta},
                    status=status.HTTP_200_OK
                )

            # ==============================
            # EXPENSE
            # ==============================
            if intent_res.intent in ("expense_summary", "expense_top"):
                r = queries.expense_summary(dr)

                reply = (
                    f"💸 Expense ({meta['from']} → {meta['to']})\n"
                    f"Total Expense: {queries.money(r['total'])}"
                )

                if r["top"]:
                    reply += "\n\nTop Expense:"
                    for i, it in enumerate(r["top"], start=1):
                        reply += f"\n{i}. {it['name']}: {queries.money(it['amount'])}"

                cards = [{
                    "label": "Total Expense",
                    "value": queries.money(r["total"])
                }]

                links = [{
                    "title": "Buka Expense Report",
                    "url": f"/admin/reports/expense/?from={meta['from']}&to={meta['to']}"
                }]

                return Response(
                    {"reply_text": reply, "cards": cards, "links": links, "meta": meta},
                    status=status.HTTP_200_OK
                )

            # ==============================
            # PROFIT
            # ==============================
            if intent_res.intent == "profit_summary":
                r = queries.profit_summary(dr)

                reply = (
                    f"🧮 Profit ({meta['from']} → {meta['to']})\n"
                    f"Net Sales: {queries.money(r['net_sales'])}\n"
                    f"Expense: {queries.money(r['expense'])}\n"
                    f"Profit: {queries.money(r['profit'])}"
                )

                cards = [
                    {"label": "Net Sales", "value": queries.money(r["net_sales"])},
                    {"label": "Expense", "value": queries.money(r["expense"])},
                    {"label": "Profit", "value": queries.money(r["profit"])},
                ]

                links = [{
                    "title": "Buka Sales Chart",
                    "url": "/admin/reports/sales-chart/"
                }]

                return Response(
                    {"reply_text": reply, "cards": cards, "links": links, "meta": meta},
                    status=status.HTTP_200_OK
                )

            # ==============================
            # TOP PRODUCTS
            # ==============================
            if intent_res.intent == "top_products":
                items = queries.top_products(dr)

                reply = f"🏆 Top Products ({meta['from']} → {meta['to']})"

                if not items:
                    reply += "\nTidak ada data penjualan pada range ini."
                else:
                    for i, it in enumerate(items, start=1):
                        reply += (
                            f"\n{i}. {it['name']} — Qty {it['qty']} — "
                            f"{queries.money(it['revenue'])}"
                        )

                links = [{
                    "title": "Buka Sales Report",
                    "url": f"/admin/reports/sales/?from={meta['from']}&to={meta['to']}"
                }]

                return Response(
                    {"reply_text": reply, "cards": [], "links": links, "meta": meta},
                    status=status.HTTP_200_OK
                )

            # ==============================
            # STOCK ALERT
            # ==============================
            if intent_res.intent == "stock_alert":
                items = queries.stock_alert()

                reply = "⚠️ Stok menipis (stock < min_stock)"

                if not items:
                    reply += "\nSemua stok aman."
                else:
                    for i, it in enumerate(items[:15], start=1):
                        reply += (
                            f"\n{i}. {it['name']} — "
                            f"Stock {it['stock']} (Min {it['min_stock']})"
                        )

                cards = [{
                    "label": "Items Alert",
                    "value": str(len(items))
                }]

                links = [{
                    "title": "Buka Inventory (Admin)",
                    "url": "/admin/"
                }]

                return Response(
                    {"reply_text": reply, "cards": cards, "links": links, "meta": meta},
                    status=status.HTTP_200_OK
                )

            # ==============================
            # INVENTORY MOVEMENT
            # ==============================
            if intent_res.intent == "inventory_movement":
                r = queries.inventory_movement(dr)

                reply = f"🔁 Inventory Movement ({meta['from']} → {meta['to']})"

                if r["by_type"]:
                    reply += "\n\nSummary:"
                    for x in r["by_type"]:
                        reply += f"\n• {x['type']}: {x['count']} trx (qty {x['qty']})"

                if r["recent"]:
                    reply += "\n\nRecent:"
                    for x in r["recent"]:
                        reply += (
                            f"\n- {x['type']} {x['product']} "
                            f"({x['delta']}): {x['note']}"
                        )

                return Response(
                    {"reply_text": reply, "cards": [], "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            return Response(
                {"reply_text": "Intent belum di-handle.", "cards": [], "links": [], "meta": meta},
                status=status.HTTP_200_OK
            )

        except Exception:
            logger.exception("OwnerChat query failed")
            return Response(
                {
                    "reply_text": "Terjadi error saat mengambil data report. Cek log server.",
                    "cards": [],
                    "links": [],
                    "meta": meta
                },
                status=status.HTTP_200_OK
            )