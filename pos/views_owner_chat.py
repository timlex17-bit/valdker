import logging
from datetime import timedelta

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from pos.permissions import IsOwnerManagerAdminOrPlatformAdmin
from pos.tenant import resolve_shop_for_user, validate_owner_chat_role
from pos.serializers_owner_chat import OwnerChatRequestSerializer
from pos.api_owner_chat.intents import detect_intent
from pos.api_owner_chat.utils import parse_date_range
from pos.api_owner_chat import queries
from pos.api_owner_chat.help_responses import HELP_TOPICS, HELP_FALLBACK_TEXT
from pos.api_owner_chat import insight

logger = logging.getLogger(__name__)


class OwnerChatAPIView(APIView):
    """
    Owner Assistant API (multi-tenant safe)

    Response shape intentionally kept stable:
    {
        "reply_text": str,
        "cards": list,
        "links": list,
        "meta": dict
    }
    """
    permission_classes = [
        IsAuthenticated,
        IsOwnerManagerAdminOrPlatformAdmin
    ]

    def get(self, request):
        return Response(
            {
                "detail": 'Favor uza POST JSON: {"message":"reseita ohin"} ho Authorization: Token <token>'
            },
            status=status.HTTP_200_OK
        )

    def post(self, request):
        ser = OwnerChatRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        message = (ser.validated_data.get("message") or "").strip()
        if not message:
            return Response(
                {
                    "reply_text": "Mensajen tenke iha.",
                    "cards": [],
                    "links": [],
                    "meta": {}
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # =========================================================
        # Resolve tenant shop + role validation
        # =========================================================
        shop = resolve_shop_for_user(request)
        validate_owner_chat_role(request.user, shop)

        intent_res = detect_intent(message)
        range_label, dr = parse_date_range(message)

        to_dt_inclusive = timezone.localtime(dr.end) - timedelta(microseconds=1)

        meta = {
            "intent": getattr(intent_res, "intent", "unknown"),
            "confidence": getattr(intent_res, "confidence", 0),
            "range": range_label,
            "from": timezone.localtime(dr.start).date().isoformat(),
            "to": to_dt_inclusive.date().isoformat(),
            "shop_id": getattr(shop, "id", None),
            "shop_code": getattr(shop, "code", ""),
            "shop_name": getattr(shop, "name", ""),
        }

        if getattr(intent_res, "intent", "unknown") in ("unknown", "fallback", None):
            reply = (
                f"🤖 Asistente Proprietáriu - {shop.name}\n\n"
                "Hau seidauk komprende pergunta ida ne'e. Ezemplu pergunta sira:\n\n"
                "📊 Analítika:\n"
                "• reseita ohin\n"
                "• vendas dine in ohin\n"
                "• taxa delivery semana ida ne'e\n"
                "• diskuentu fulan ida ne'e\n"
                "• métodu pagamentu ne'ebé barak liu\n"
                "• cash vs transfer ohin\n"
                "• oras ne'ebé movimentu liu\n"
                "• margem fulan ida ne'e\n"
                "• despeza fulan ida ne'e\n"
                "• lukru ohin\n\n"
                "📦 Inventáriu:\n"
                "• produtu sira ne'ebé fa'an barak liu fulan ida ne'e\n"
                "• stok ki'ik hela\n"
                "• stok hotu ona\n"
                "• stok menus husi 3\n"
                "• stok pizza\n"
                "• movement adjustment ohin\n"
                "• inventory movement ohin\n\n"
                "🤖 Insight:\n"
                "• kompara semana ida ne'e ho semana kotuk\n"
                "• tanba sa lukru tun\n"
                "• rekomendasaun promo\n\n"
                "🧾 Ajuda POS:\n"
                "• oinsá aumenta produtu\n"
                "• oinsá halo retur barang\n"
                "• oinsá imprime resibu\n"
                "• oinsá halo stok opname"
            )
            return Response(
                {"reply_text": reply, "cards": [], "links": [], "meta": meta},
                status=status.HTTP_200_OK
            )

        try:
            # =====================================================
            # HELP
            # =====================================================
            if intent_res.intent == "help":
                topic = getattr(intent_res, "slot", None)
                if topic and topic in HELP_TOPICS:
                    reply = f"🧾 {HELP_TOPICS[topic]['title']}\n\n{HELP_TOPICS[topic]['text']}"
                else:
                    reply = HELP_FALLBACK_TEXT

                return Response(
                    {"reply_text": reply, "cards": [], "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # SALES SUMMARY / ORDERS KPI
            # =====================================================
            if intent_res.intent in ("sales_summary", "orders_kpi"):
                r = queries.sales_summary(dr, shop=shop)

                if r["orders"] == 0:
                    reply = (
                        f"📊 Vendas - {shop.name} ({meta['from']} → {meta['to']})\n"
                        "Seidauk iha tranzasaun PAID iha períodu ida ne'e."
                    )
                    cards = [
                        {"label": "Total Pedido", "value": "0"},
                        {"label": "Vendas Líquida", "value": "$0.00"},
                        {"label": "Média Pedido", "value": "$0.00"},
                    ]
                else:
                    reply = (
                        f"📊 Vendas - {shop.name} ({meta['from']} → {meta['to']})\n"
                        f"Vendas Líquida: {queries.money(r['net_sales'])}\n"
                        f"Total Pedido: {r['orders']}\n"
                        f"Média Pedido: {queries.money(r['aov'])}"
                    )
                    cards = [
                        {"label": "Vendas Líquida", "value": queries.money(r["net_sales"])},
                        {"label": "Total Pedido", "value": str(r["orders"])},
                        {"label": "Média Pedido", "value": queries.money(r["aov"])},
                    ]

                links = [{
                    "title": "Loke Relatóriu Vendas",
                    "url": f"/admin/reports/sales/?from={meta['from']}&to={meta['to']}"
                }]

                return Response(
                    {"reply_text": reply, "cards": cards, "links": links, "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # SALES BY TYPE
            # =====================================================
            if intent_res.intent == "sales_by_type":
                order_type = getattr(intent_res, "slot", None) or "GENERAL"
                r = queries.sales_by_type(dr, order_type=order_type, shop=shop)

                reply = (
                    f"📊 Vendas {order_type} - {shop.name} ({meta['from']} → {meta['to']})\n"
                    f"Total: {queries.money(r['total'])}\n"
                    f"Total Pedido: {r['orders']}\n"
                    f"Diskuentu: {queries.money(r['discount'])}\n"
                    f"Taxa Delivery: {queries.money(r['delivery_fee'])}"
                )

                cards = [
                    {"label": f"Total {order_type}", "value": queries.money(r["total"])},
                    {"label": "Total Pedido", "value": str(r["orders"])},
                ]

                return Response(
                    {"reply_text": reply, "cards": cards, "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # DELIVERY FEE
            # =====================================================
            if intent_res.intent == "delivery_fee_summary":
                r = queries.delivery_fee_summary(dr, shop=shop)
                reply = (
                    f"🚚 Taxa Delivery - {shop.name} ({meta['from']} → {meta['to']})\n"
                    f"Total Taxa Delivery: {queries.money(r['delivery_fee'])}"
                )
                cards = [{"label": "Taxa Delivery", "value": queries.money(r["delivery_fee"])}]
                return Response(
                    {"reply_text": reply, "cards": cards, "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # DISCOUNT
            # =====================================================
            if intent_res.intent == "discount_summary":
                r = queries.discount_summary(dr, shop=shop)
                reply = (
                    f"🏷️ Diskuentu - {shop.name} ({meta['from']} → {meta['to']})\n"
                    f"Total Diskuentu: {queries.money(r['discount'])}"
                )
                cards = [{"label": "Diskuentu", "value": queries.money(r["discount"])}]
                return Response(
                    {"reply_text": reply, "cards": cards, "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # PAYMENT METHOD TOP
            # =====================================================
            if intent_res.intent == "payment_method_top":
                items = queries.payment_method_top(dr, limit=5, shop=shop)

                reply = f"💳 Métodu Pagamentu Top - {shop.name} ({meta['from']} → {meta['to']})"
                if not items:
                    reply += "\nSeidauk iha tranzasaun."
                else:
                    for i, it in enumerate(items, start=1):
                        reply += f"\n{i}. {it['method']} — {it['orders']} trx — {queries.money(it['total'])}"

                return Response(
                    {"reply_text": reply, "cards": [], "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # CASH VS TRANSFER
            # =====================================================
            if intent_res.intent == "cash_vs_transfer":
                r = queries.cash_vs_transfer(dr, shop=shop)
                reply = f"💰 Cash vs La'ós Cash - {shop.name} ({meta['from']} → {meta['to']})"
                reply += (
                    f"\n• CASH: {r['CASH']['orders']} trx — {queries.money(r['CASH']['total'])}"
                    f"\n• TRANSFER: {r['TRANSFER']['orders']} trx — {queries.money(r['TRANSFER']['total'])}"
                    f"\n• QRIS: {r['QRIS']['orders']} trx — {queries.money(r['QRIS']['total'])}"
                    f"\n• SELUK: {r['OTHER']['orders']} trx — {queries.money(r['OTHER']['total'])}"
                )
                return Response(
                    {"reply_text": reply, "cards": [], "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # BUSIEST HOURS
            # =====================================================
            if intent_res.intent == "busiest_hours":
                items = queries.busiest_hours(dr, limit=5, shop=shop)
                reply = f"⏰ Oras ne'ebé movimentu liu - {shop.name} ({meta['from']} → {meta['to']})"
                if not items:
                    reply += "\nSeidauk iha tranzasaun."
                else:
                    for i, it in enumerate(items, start=1):
                        reply += f"\n{i}. {it['hour']:02d}:00 — {it['orders']} trx — {queries.money(it['total'])}"

                return Response(
                    {"reply_text": reply, "cards": [], "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # EXPENSE
            # =====================================================
            if intent_res.intent in ("expense_summary", "expense_top"):
                r = queries.expense_summary(dr, shop=shop)
                reply = (
                    f"💸 Despeza - {shop.name} ({meta['from']} → {meta['to']})\n"
                    f"Total Despeza: {queries.money(r['total'])}"
                )

                if r["top"]:
                    reply += "\n\nDespeza Aas Liu:"
                    for i, it in enumerate(r["top"], start=1):
                        reply += f"\n{i}. {it['name']}: {queries.money(it['amount'])}"

                cards = [{"label": "Total Despeza", "value": queries.money(r["total"])}]
                links = [{
                    "title": "Loke Relatóriu Despeza",
                    "url": f"/admin/reports/expense/?from={meta['from']}&to={meta['to']}"
                }]

                return Response(
                    {"reply_text": reply, "cards": cards, "links": links, "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # PROFIT
            # =====================================================
            if intent_res.intent == "profit_summary":
                r = queries.profit_summary(dr, shop=shop)
                reply = (
                    f"🧮 Lukru - {shop.name} ({meta['from']} → {meta['to']})\n"
                    f"Vendas Líquida: {queries.money(r['net_sales'])}\n"
                    f"Despeza: {queries.money(r['expense'])}\n"
                    f"Lukru: {queries.money(r['profit'])}"
                )
                cards = [
                    {"label": "Vendas Líquida", "value": queries.money(r["net_sales"])},
                    {"label": "Despeza", "value": queries.money(r["expense"])},
                    {"label": "Lukru", "value": queries.money(r["profit"])},
                ]
                links = [{"title": "Loke Gráfiku Vendas", "url": "/admin/reports/sales-chart/"}]

                return Response(
                    {"reply_text": reply, "cards": cards, "links": links, "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # MARGIN
            # =====================================================
            if intent_res.intent == "margin_summary":
                r = queries.margin_summary(dr, shop=shop)
                reply = (
                    f"📈 Margem - {shop.name} ({meta['from']} → {meta['to']})\n"
                    f"Rendimentu: {queries.money(r['revenue'])}\n"
                    f"Kustu: {queries.money(r['cost'])}\n"
                    f"Lukru Brutu: {queries.money(r['gross_profit'])}\n"
                    f"Margem: {r['margin_pct']:.2f}%"
                )
                cards = [
                    {"label": "Lukru Brutu", "value": queries.money(r["gross_profit"])},
                    {"label": "Margem %", "value": f"{r['margin_pct']:.2f}%"},
                ]

                return Response(
                    {"reply_text": reply, "cards": cards, "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # TOP PRODUCTS
            # =====================================================
            if intent_res.intent == "top_products":
                items = queries.top_products(dr, shop=shop)
                reply = f"🏆 Produtu sira ne'ebé fa'an barak liu - {shop.name} ({meta['from']} → {meta['to']})"
                if not items:
                    reply += "\nLa iha dadus vendas iha períodu ida ne'e."
                else:
                    for i, it in enumerate(items, start=1):
                        reply += f"\n{i}. {it['name']} — Qty {it['qty']} — {queries.money(it['revenue'])}"

                links = [{
                    "title": "Loke Relatóriu Vendas",
                    "url": f"/admin/reports/sales/?from={meta['from']}&to={meta['to']}"
                }]

                return Response(
                    {"reply_text": reply, "cards": [], "links": links, "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # STOCK ALERT
            # =====================================================
            if intent_res.intent == "stock_alert":
                items = queries.stock_alert(shop=shop)
                reply = f"⚠️ Stok ki'ik hela - {shop.name} (stock <= threshold)"
                if not items:
                    reply += "\nStok hotu seguru."
                else:
                    for i, it in enumerate(items[:15], start=1):
                        reply += f"\n{i}. {it['name']} — Stock {it['stock']} (Threshold {it.get('min_stock')})"

                cards = [{"label": "Item Alert", "value": str(len(items))}]
                return Response(
                    {"reply_text": reply, "cards": cards, "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # STOCK THRESHOLD
            # =====================================================
            if intent_res.intent == "stock_threshold":
                th = int(getattr(intent_res, "number", None) or 5)
                items = queries.stock_threshold(threshold=th, shop=shop)
                reply = f"⚠️ Stok menus husi / hanesan ho {th} - {shop.name}"
                if not items:
                    reply += "\nStok hotu seguru."
                else:
                    for i, it in enumerate(items[:15], start=1):
                        reply += f"\n{i}. {it['name']} — Stock {it['stock']}"

                cards = [{"label": "Item Alert", "value": str(len(items))}]
                return Response(
                    {"reply_text": reply, "cards": cards, "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # STOCK OUT
            # =====================================================
            if intent_res.intent == "stock_out":
                items = queries.stock_out(shop=shop)
                reply = f"🚫 Stok hotu ona - {shop.name} (stock <= 0)"
                if not items:
                    reply += "\nLa iha produtu ne'ebé stok hotu ona."
                else:
                    for i, it in enumerate(items[:15], start=1):
                        reply += f"\n{i}. {it['name']} — Stock {it['stock']}"

                cards = [{"label": "Stok Hotu", "value": str(len(items))}]
                return Response(
                    {"reply_text": reply, "cards": cards, "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # STOCK ITEM
            # =====================================================
            if intent_res.intent == "stock_item":
                name = (getattr(intent_res, "entity", "") or "").strip()
                items = queries.stock_item_by_name(name, shop=shop)
                reply = f"📦 Stok produtu - {shop.name}: {name}"
                if not items:
                    reply += "\nProdutu la hetan."
                else:
                    for i, it in enumerate(items, start=1):
                        reply += f"\n{i}. {it['name']} — Stock {it['stock']}"

                return Response(
                    {"reply_text": reply, "cards": [], "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # MOVEMENT ADJUSTMENT
            # =====================================================
            if intent_res.intent == "movement_adjustment":
                items = queries.movement_by_type(dr, movement_type="ADJUSTMENT", limit=10, shop=shop)
                reply = f"🛠️ Movement Adjustment - {shop.name} ({meta['from']} → {meta['to']})"
                if not items:
                    reply += "\nLa iha adjustment."
                else:
                    for i, it in enumerate(items, start=1):
                        reply += f"\n{i}. {it['product']} ({it['delta']}): {it['note']}"

                return Response(
                    {"reply_text": reply, "cards": [], "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # INVENTORY MOVEMENT
            # =====================================================
            if intent_res.intent == "inventory_movement":
                r = queries.inventory_movement(dr, shop=shop)
                reply = f"🔁 Movement Inventáriu - {shop.name} ({meta['from']} → {meta['to']})"
                if r["by_type"]:
                    reply += "\n\nSumáriu:"
                    for x in r["by_type"]:
                        reply += f"\n• {x['type']}: {x['count']} trx (qty {x['qty']})"
                if r["recent"]:
                    reply += "\n\nDadus ikus:"
                    for x in r["recent"]:
                        reply += f"\n- {x['type']} {x['product']} ({x['delta']}): {x['note']}"

                return Response(
                    {"reply_text": reply, "cards": [], "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # COMPARE PERIOD
            # =====================================================
            if intent_res.intent == "compare_period":
                cmp = insight.compare_period(dr, queries.for_shop(shop))
                this_sales = cmp["this"]["sales"]["net_sales"]
                prev_sales = cmp["prev"]["sales"]["net_sales"]
                d_sales = cmp["delta"]["sales"]
                this_profit = cmp["this"]["profit"]["profit"]
                prev_profit = cmp["prev"]["profit"]["profit"]
                d_profit = cmp["delta"]["profit"]

                reply = (
                    f"📊 Komparasaun Períodu - {shop.name} ({meta['from']} → {meta['to']}) vs períodu uluk\n"
                    f"Vendas: {queries.money(this_sales)} (uluk {queries.money(prev_sales)}) → Δ {queries.money(d_sales)}\n"
                    f"Lukru: {queries.money(this_profit)} (uluk {queries.money(prev_profit)}) → Δ {queries.money(d_profit)}\n"
                    f"Despeza Δ: {queries.money(cmp['delta']['expense'])}\n"
                    f"Margem Δ: {cmp['delta']['margin_pct']:.2f}%"
                )

                return Response(
                    {"reply_text": reply, "cards": [], "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # WHY PROFIT DOWN
            # =====================================================
            if intent_res.intent == "why_profit_down":
                res = insight.why_profit_down(dr, queries.for_shop(shop))
                reply = f"📉 Analiza Lukru - {shop.name}\n{res['text']}"
                return Response(
                    {"reply_text": reply, "cards": [], "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            # =====================================================
            # PROMO RECOMMENDATION
            # =====================================================
            if intent_res.intent == "promo_recommendation":
                reply = insight.promo_recommendation(dr, queries.for_shop(shop))
                reply = f"🎯 Rekomendasaun Promo - {shop.name}\n{reply}"
                return Response(
                    {"reply_text": reply, "cards": [], "links": [], "meta": meta},
                    status=status.HTTP_200_OK
                )

            return Response(
                {
                    "reply_text": f"Intent '{intent_res.intent}' seidauk iha handle.",
                    "cards": [],
                    "links": [],
                    "meta": meta
                },
                status=status.HTTP_200_OK
            )

        except Exception:
            logger.exception("OwnerChat query failed")
            return Response(
                {
                    "reply_text": "Akontese erru bainhira foti dadus relatóriu. Favor haree log servidor.",
                    "cards": [],
                    "links": [],
                    "meta": meta
                },
                status=status.HTTP_200_OK
            )