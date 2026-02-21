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
from pos.api_owner_chat.help_responses import HELP_TOPICS, HELP_FALLBACK_TEXT
from pos.api_owner_chat import insight

logger = logging.getLogger(__name__)


class OwnerChatAPIView(APIView):
    permission_classes = [IsOwnerOrManager]

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

        # timezone safe inclusive end (for meta only)
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
                "Saya belum mengerti. Contoh pertanyaan:\n"
                "📊 Analytics:\n"
                "• income hari ini\n"
                "• penjualan dine in hari ini\n"
                "• delivery fee minggu ini\n"
                "• diskon bulan ini\n"
                "• payment method paling banyak\n"
                "• cash vs transfer hari ini\n"
                "• jam paling ramai\n"
                "• margin bulan ini\n\n"
                "📦 Inventory:\n"
                "• top produk bulan ini\n"
                "• stok menipis\n"
                "• stok habis\n"
                "• stok kurang dari 3\n"
                "• stok pizza\n"
                "• movement adjustment hari ini\n"
                "• inventory movement hari ini\n\n"
                "🤖 Insight:\n"
                "• bandingkan minggu ini dengan minggu lalu\n"
                "• kenapa profit turun\n"
                "• rekomendasi promo"
            )
            return Response({"reply_text": reply, "cards": [], "links": [], "meta": meta}, status=200)

        try:
            # =========================================================
            # HELP
            # =========================================================
            if intent_res.intent == "help":
                topic = intent_res.slot
                if topic and topic in HELP_TOPICS:
                    reply = f"🧾 {HELP_TOPICS[topic]['title']}\n\n{HELP_TOPICS[topic]['text']}"
                else:
                    reply = HELP_FALLBACK_TEXT
                return Response({"reply_text": reply, "cards": [], "links": [], "meta": meta}, status=200)

            # =========================================================
            # SALES / INCOME (existing)
            # =========================================================
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

                return Response({"reply_text": reply, "cards": cards, "links": links, "meta": meta}, status=200)

            # =========================================================
            # SALES ADVANCED: sales_by_type
            # =========================================================
            if intent_res.intent == "sales_by_type":
                order_type = intent_res.slot or "GENERAL"
                r = queries.sales_by_type(dr, order_type=order_type)

                reply = (
                    f"📊 Sales {order_type} ({meta['from']} → {meta['to']})\n"
                    f"Total: {queries.money(r['total'])}\n"
                    f"Orders: {r['orders']}\n"
                    f"Discount: {queries.money(r['discount'])}\n"
                    f"Delivery Fee: {queries.money(r['delivery_fee'])}"
                )

                cards = [
                    {"label": f"{order_type} Total", "value": queries.money(r["total"])},
                    {"label": "Orders", "value": str(r["orders"])},
                ]

                return Response({"reply_text": reply, "cards": cards, "links": [], "meta": meta}, status=200)

            # =========================================================
            # delivery_fee_summary
            # =========================================================
            if intent_res.intent == "delivery_fee_summary":
                r = queries.delivery_fee_summary(dr)
                reply = (
                    f"🚚 Delivery Fee ({meta['from']} → {meta['to']})\n"
                    f"Total Delivery Fee: {queries.money(r['delivery_fee'])}"
                )
                cards = [{"label": "Delivery Fee", "value": queries.money(r["delivery_fee"])}]
                return Response({"reply_text": reply, "cards": cards, "links": [], "meta": meta}, status=200)

            # =========================================================
            # discount_summary
            # =========================================================
            if intent_res.intent == "discount_summary":
                r = queries.discount_summary(dr)
                reply = (
                    f"🏷️ Discount ({meta['from']} → {meta['to']})\n"
                    f"Total Discount: {queries.money(r['discount'])}"
                )
                cards = [{"label": "Discount", "value": queries.money(r["discount"])}]
                return Response({"reply_text": reply, "cards": cards, "links": [], "meta": meta}, status=200)

            # =========================================================
            # payment_method_top
            # =========================================================
            if intent_res.intent == "payment_method_top":
                items = queries.payment_method_top(dr, limit=5)

                reply = f"💳 Payment Method Top ({meta['from']} → {meta['to']})"
                if not items:
                    reply += "\nBelum ada transaksi."
                else:
                    for i, it in enumerate(items, start=1):
                        reply += f"\n{i}. {it['method']} — {it['orders']} trx — {queries.money(it['total'])}"

                return Response({"reply_text": reply, "cards": [], "links": [], "meta": meta}, status=200)

            # =========================================================
            # cash_vs_transfer
            # =========================================================
            if intent_res.intent == "cash_vs_transfer":
                r = queries.cash_vs_transfer(dr)
                reply = f"💰 Cash vs Non-Cash ({meta['from']} → {meta['to']})"
                reply += (
                    f"\n• CASH: {r['CASH']['orders']} trx — {queries.money(r['CASH']['total'])}"
                    f"\n• TRANSFER: {r['TRANSFER']['orders']} trx — {queries.money(r['TRANSFER']['total'])}"
                    f"\n• QRIS: {r['QRIS']['orders']} trx — {queries.money(r['QRIS']['total'])}"
                    f"\n• OTHER: {r['OTHER']['orders']} trx — {queries.money(r['OTHER']['total'])}"
                )
                return Response({"reply_text": reply, "cards": [], "links": [], "meta": meta}, status=200)

            # =========================================================
            # busiest_hours
            # =========================================================
            if intent_res.intent == "busiest_hours":
                items = queries.busiest_hours(dr, limit=5)
                reply = f"⏰ Jam Paling Ramai ({meta['from']} → {meta['to']})"
                if not items:
                    reply += "\nBelum ada transaksi."
                else:
                    for i, it in enumerate(items, start=1):
                        reply += f"\n{i}. {it['hour']:02d}:00 — {it['orders']} trx — {queries.money(it['total'])}"
                return Response({"reply_text": reply, "cards": [], "links": [], "meta": meta}, status=200)

            # =========================================================
            # EXPENSE (existing)
            # =========================================================
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

                cards = [{"label": "Total Expense", "value": queries.money(r["total"])}]
                links = [{
                    "title": "Buka Expense Report",
                    "url": f"/admin/reports/expense/?from={meta['from']}&to={meta['to']}"
                }]

                return Response({"reply_text": reply, "cards": cards, "links": links, "meta": meta}, status=200)

            # =========================================================
            # PROFIT (existing)
            # =========================================================
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

                links = [{"title": "Buka Sales Chart", "url": "/admin/reports/sales-chart/"}]

                return Response({"reply_text": reply, "cards": cards, "links": links, "meta": meta}, status=200)

            # =========================================================
            # margin_summary
            # =========================================================
            if intent_res.intent == "margin_summary":
                r = queries.margin_summary(dr)
                reply = (
                    f"📈 Margin ({meta['from']} → {meta['to']})\n"
                    f"Revenue: {queries.money(r['revenue'])}\n"
                    f"Cost: {queries.money(r['cost'])}\n"
                    f"Gross Profit: {queries.money(r['gross_profit'])}\n"
                    f"Margin: {r['margin_pct']:.2f}%"
                )
                cards = [
                    {"label": "Gross Profit", "value": queries.money(r["gross_profit"])},
                    {"label": "Margin %", "value": f"{r['margin_pct']:.2f}%"},
                ]
                return Response({"reply_text": reply, "cards": cards, "links": [], "meta": meta}, status=200)

            # =========================================================
            # TOP PRODUCTS (existing)
            # =========================================================
            if intent_res.intent == "top_products":
                items = queries.top_products(dr)

                reply = f"🏆 Top Products ({meta['from']} → {meta['to']})"
                if not items:
                    reply += "\nTidak ada data penjualan pada range ini."
                else:
                    for i, it in enumerate(items, start=1):
                        reply += f"\n{i}. {it['name']} — Qty {it['qty']} — {queries.money(it['revenue'])}"

                links = [{"title": "Buka Sales Report", "url": f"/admin/reports/sales/?from={meta['from']}&to={meta['to']}"}]
                return Response({"reply_text": reply, "cards": [], "links": links, "meta": meta}, status=200)

            # =========================================================
            # STOCK ALERTS
            # =========================================================
            if intent_res.intent == "stock_alert":
                items = queries.stock_alert()
                reply = "⚠️ Stok menipis (stock <= threshold)"
                if not items:
                    reply += "\nSemua stok aman."
                else:
                    for i, it in enumerate(items[:15], start=1):
                        reply += f"\n{i}. {it['name']} — Stock {it['stock']} (Threshold {it.get('min_stock')})"

                cards = [{"label": "Items Alert", "value": str(len(items))}]
                return Response({"reply_text": reply, "cards": cards, "links": [], "meta": meta}, status=200)

            if intent_res.intent == "stock_threshold":
                th = int(intent_res.number or 5)
                items = queries.stock_threshold(threshold=th)
                reply = f"⚠️ Stok kurang dari / sama dengan {th}"
                if not items:
                    reply += "\nSemua stok aman."
                else:
                    for i, it in enumerate(items[:15], start=1):
                        reply += f"\n{i}. {it['name']} — Stock {it['stock']}"

                cards = [{"label": "Items Alert", "value": str(len(items))}]
                return Response({"reply_text": reply, "cards": cards, "links": [], "meta": meta}, status=200)

            if intent_res.intent == "stock_out":
                items = queries.stock_out()
                reply = "🚫 Stok habis (stock <= 0)"
                if not items:
                    reply += "\nTidak ada produk stok habis."
                else:
                    for i, it in enumerate(items[:15], start=1):
                        reply += f"\n{i}. {it['name']} — Stock {it['stock']}"

                cards = [{"label": "Stock Out", "value": str(len(items))}]
                return Response({"reply_text": reply, "cards": cards, "links": [], "meta": meta}, status=200)

            if intent_res.intent == "stock_item":
                name = (intent_res.entity or "").strip()
                items = queries.stock_item_by_name(name)
                reply = f"📦 Stok produk: {name}"
                if not items:
                    reply += "\nTidak ditemukan produk."
                else:
                    for i, it in enumerate(items, start=1):
                        reply += f"\n{i}. {it['name']} — Stock {it['stock']}"
                return Response({"reply_text": reply, "cards": [], "links": [], "meta": meta}, status=200)

            # =========================================================
            # MOVEMENT ADJUSTMENT
            # =========================================================
            if intent_res.intent == "movement_adjustment":
                items = queries.movement_by_type(dr, movement_type="ADJUSTMENT", limit=10)
                reply = f"🛠️ Adjustment Movement ({meta['from']} → {meta['to']})"
                if not items:
                    reply += "\nTidak ada adjustment."
                else:
                    for i, it in enumerate(items, start=1):
                        reply += f"\n{i}. {it['product']} ({it['delta']}): {it['note']}"
                return Response({"reply_text": reply, "cards": [], "links": [], "meta": meta}, status=200)

            # =========================================================
            # INVENTORY MOVEMENT (existing)
            # =========================================================
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
                        reply += f"\n- {x['type']} {x['product']} ({x['delta']}): {x['note']}"

                return Response({"reply_text": reply, "cards": [], "links": [], "meta": meta}, status=200)

            # =========================================================
            # SMART INSIGHT: compare_period
            # =========================================================
            if intent_res.intent == "compare_period":
                cmp = insight.compare_period(dr, queries)

                this_sales = cmp["this"]["sales"]["net_sales"]
                prev_sales = cmp["prev"]["sales"]["net_sales"]
                d_sales = cmp["delta"]["sales"]

                this_profit = cmp["this"]["profit"]["profit"]
                prev_profit = cmp["prev"]["profit"]["profit"]
                d_profit = cmp["delta"]["profit"]

                reply = (
                    f"📊 Perbandingan Periode ({meta['from']} → {meta['to']}) vs periode sebelumnya\n"
                    f"Sales: {queries.money(this_sales)} (prev {queries.money(prev_sales)}) → Δ {queries.money(d_sales)}\n"
                    f"Profit: {queries.money(this_profit)} (prev {queries.money(prev_profit)}) → Δ {queries.money(d_profit)}\n"
                    f"Expense Δ: {queries.money(cmp['delta']['expense'])}\n"
                    f"Margin Δ: {cmp['delta']['margin_pct']:.2f}%"
                )

                return Response({"reply_text": reply, "cards": [], "links": [], "meta": meta}, status=200)

            # =========================================================
            # SMART INSIGHT: why_profit_down
            # =========================================================
            if intent_res.intent == "why_profit_down":
                res = insight.why_profit_down(dr, queries)
                reply = res["text"]
                return Response({"reply_text": reply, "cards": [], "links": [], "meta": meta}, status=200)

            # =========================================================
            # SMART INSIGHT: promo recommendation
            # =========================================================
            if intent_res.intent == "promo_recommendation":
                reply = insight.promo_recommendation(dr, queries)
                return Response({"reply_text": reply, "cards": [], "links": [], "meta": meta}, status=200)

            # ---------------------------------------------------------
            return Response(
                {"reply_text": "Intent belum di-handle.", "cards": [], "links": [], "meta": meta},
                status=200
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
                status=200
            )