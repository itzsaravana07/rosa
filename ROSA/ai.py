"""xAI Grok integration. The API key is only ever used here, server-side.

Every answer is grounded: we pick real products from the database, pass them to
Grok as the only allowed catalogue, and validate whatever Grok returns.
"""
import json
import re

import requests
from django.conf import settings
from django.db.models import Q
from django.db.models.functions import Coalesce

from .models import Product


class AIUnavailable(Exception):
    pass


STOPWORDS = {
    "the", "and", "for", "with", "you", "any", "can", "have", "need", "want", "show", "give", "some", "under",
    "below", "within", "budget", "compare", "recommend", "suggest", "something", "looking", "find", "best",
    "good", "please", "what", "which", "that", "this", "than", "from", "about", "gift", "rupees", "inr",
}


def _call_grok(messages, temperature=0.3, max_tokens=700):
    if not settings.GROK_CONFIGURED:
        raise AIUnavailable("The shopping assistant isn't switched on yet. Add GROK_API_KEY to the .env file.")
    try:
        resp = requests.post(
            f"{settings.GROK_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {settings.GROK_API_KEY}", "Content-Type": "application/json"},
            json={"model": settings.GROK_MODEL, "messages": messages,
                  "temperature": temperature, "max_tokens": max_tokens},
            timeout=45,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except requests.RequestException as exc:
        raise AIUnavailable("The assistant couldn't be reached. Please try again in a moment.") from exc
    except (KeyError, IndexError, ValueError) as exc:
        raise AIUnavailable("The assistant sent an unexpected reply. Please try again.") from exc


def product_facts(p: Product) -> dict:
    return {
        "slug": p.slug,
        "name": p.name,
        "brand": p.brand,
        "category": str(p.category),
        "mrp_inr": float(p.price),
        "sale_price_inr": float(p.sale_price),
        "discount_percent": p.discount_percent,
        "in_stock": p.in_stock,
        "sizes": [s.name for s in p.sizes.all()],
        "colours": [c.name for c in p.colours.all()],
        "description": (p.description or "")[:300],
    }


def extract_budget(text: str):
    m = re.search(r"(?:₹|rs\.?|inr|under|below|within|upto|up to|budget(?: of)?)\s*([0-9][0-9,]*)", text.lower())
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def retrieve_products(message: str, budget=None, limit=12):
    qs = (Product.objects.filter(is_active=True, stock__gt=0)
          .select_related("category", "category__parent")
          .prefetch_related("sizes", "colours", "images")
          .annotate(effective=Coalesce("discount_price", "price")))
    if budget:
        qs = qs.filter(effective__lte=budget)
    words = [w for w in re.findall(r"[a-zA-Z]{3,}", message.lower()) if w not in STOPWORDS]
    if words:
        cond = Q()
        for w in set(words):
            cond |= (Q(name__icontains=w) | Q(brand__icontains=w) | Q(description__icontains=w)
                     | Q(category__name__icontains=w) | Q(category__parent__name__icontains=w))
        matched = list(qs.filter(cond).distinct().order_by("-is_featured", "effective")[:limit])
        if matched:
            return matched
    return list(qs.order_by("-is_featured", "-created_at")[:limit])


def _parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        return None


def shopping_assistant(message: str, history=None, budget=None):
    budget = budget or extract_budget(message)
    candidates = retrieve_products(message, budget)
    catalogue = [product_facts(p) for p in candidates]
    system = (
        "You are the ROSA fashion store's shopping assistant. Recommend ONLY products from the CATALOG JSON below. "
        "Never invent products, prices, sizes or stock. Prices are in Indian rupees. "
        "If nothing fits the request or budget, say so honestly and suggest the closest options from the catalog. "
        "Keep the reply under 120 words, friendly and specific. "
        'Respond ONLY with JSON: {"reply": "<text>", "product_slugs": ["<slug>", ...]} using at most 4 slugs.\n'
        f"CATALOG: {json.dumps(catalogue, ensure_ascii=False)}"
    )
    msgs = [{"role": "system", "content": system}]
    for turn in (history or [])[-6:]:
        if turn.get("role") in ("user", "assistant") and isinstance(turn.get("content"), str):
            msgs.append({"role": turn["role"], "content": turn["content"][:600]})
    msgs.append({"role": "user", "content": message[:600]})

    raw = _call_grok(msgs)
    data = _parse_json(raw)
    by_slug = {p.slug: p for p in candidates}
    if isinstance(data, dict) and "reply" in data:
        reply = str(data["reply"])
        slugs = [s for s in data.get("product_slugs", []) if s in by_slug][:4]
    else:
        reply, slugs = raw, []
    return reply, [by_slug[s] for s in slugs]


def compare_products(products):
    facts = [product_facts(p) for p in products]
    msgs = [
        {"role": "system", "content": (
            "You compare fashion products for ROSA shoppers using ONLY the JSON facts provided. "
            "Do not invent materials, fit or features that are not in the facts. Prices are in Indian rupees. "
            "Give a short comparison (price, discount, sizes, colours, availability) then a one-line "
            "'best for' verdict for each. Under 150 words, plain text.")},
        {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
    ]
    return _call_grok(msgs, max_tokens=500)


def generate_product_description(product: Product) -> str:
    facts = product_facts(product)
    msgs = [
        {"role": "system", "content": (
            "You write product descriptions for ROSA, a premium fashion brand. Warm, elegant, concrete. "
            "70-110 words, one paragraph, no emojis, no markdown. Use only the facts given; "
            "do not invent fabric, fit or care details.")},
        {"role": "user", "content": json.dumps(
            {k: facts[k] for k in ("name", "brand", "category", "sizes", "colours")}, ensure_ascii=False)},
    ]
    return _call_grok(msgs, temperature=0.7, max_tokens=300)
