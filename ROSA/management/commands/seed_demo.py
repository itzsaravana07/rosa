"""Create demo categories, products and homepage blocks with generated placeholder images.

    python manage.py seed_demo

Replace the placeholders with real photography from the admin (Products, Promotions).
"""
import io
import random

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from PIL import Image, ImageDraw, ImageFont

from ROSA.models import Category, Colour, Product, ProductImage, Promotion, Size

TONES = ["#E9D5BD", "#D9B48F", "#C98F5E", "#B9A28A", "#CFC3B4", "#E3C4A8", "#8E7B6A", "#F0DEC8"]


def make_image(text, size=(800, 1000), tone=None, sub=""):
    tone = tone or random.choice(TONES)
    img = Image.new("RGB", size, tone)
    d = ImageDraw.Draw(img)
    w, h = size
    d.ellipse((w * 0.2, h * 0.12, w * 0.8, h * 0.62), fill=_shade(tone, 0.93))
    try:
        big = ImageFont.load_default(size=int(w * 0.07))
        small = ImageFont.load_default(size=int(w * 0.035))
    except TypeError:
        big = small = ImageFont.load_default()
    d.text((w / 2, h * 0.80), text, fill="#252525", font=big, anchor="mm")
    if sub:
        d.text((w / 2, h * 0.87), sub, fill="#252525", font=small, anchor="mm")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return ContentFile(buf.getvalue())


def _shade(hex_color, factor):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return (int(r * factor), int(g * factor), int(b * factor))


CATALOGUE = {
    "Men": (["Shirts", "Knitwear", "Outerwear"], [
        ("Linen Camp Shirt", "ROSA", 2499, 1899, 30, True, True),
        ("Merino Crew Sweater", "ROSA", 3999, None, 18, True, False),
        ("Wool Overcoat", "ROSA Atelier", 8999, 6999, 8, False, True),
    ]),
    "Women": (["Dresses", "Knitwear", "Coats"], [
        ("Camel Wrap Coat", "ROSA Atelier", 9499, 7499, 10, True, True),
        ("Cable-Knit Sweater", "ROSA", 3499, 2799, 22, True, True),
        ("Satin Midi Dress", "ROSA", 4299, None, 14, True, False),
        ("Pleated Wide Trousers", "ROSA", 2999, 2399, 25, False, True),
    ]),
    "Kids": (["Everyday", "Party"], [
        ("Cotton Play Set", "ROSA Kids", 1299, 999, 40, True, False),
        ("Corduroy Dungarees", "ROSA Kids", 1799, None, 20, False, True),
    ]),
    "Accessories": (["Bags", "Scarves"], [
        ("Leather Tote Bag", "ROSA", 5499, 4399, 12, True, True),
        ("Wool Scarf", "ROSA", 1499, None, 35, False, False),
    ]),
    "Essentials": (["Basics"], [
        ("Organic Cotton Tee", "ROSA", 799, 599, 80, True, False),
        ("Ribbed Tank", "ROSA", 699, None, 60, False, True),
    ]),
}


class Command(BaseCommand):
    help = "Create demo data (safe to re-run; skips what exists)."

    def handle(self, *args, **options):
        for i, n in enumerate(["XS", "S", "M", "L", "XL"], 1):
            Size.objects.get_or_create(name=n, defaults={"order": i})
        colours = [Colour.objects.get_or_create(name=n, defaults={"hex_code": h})[0] for n, h in
                   [("Sand", "#D9B48F"), ("Charcoal", "#252525"), ("Ivory", "#F5EEDF"), ("Burnt orange", "#E58A24")]]
        sizes = list(Size.objects.all())

        for order, (root_name, (children, products)) in enumerate(CATALOGUE.items(), 1):
            root, _ = Category.objects.get_or_create(
                name=root_name, parent=None, defaults={"order": order, "show_in_nav": root_name != "Essentials"})
            kids = [Category.objects.get_or_create(name=c, parent=root, defaults={"order": j})[0]
                    for j, c in enumerate(children, 1)]
            for idx, (name, brand, price, sale, stock, featured, new) in enumerate(products):
                if Product.objects.filter(name=name).exists():
                    continue
                p = Product.objects.create(
                    name=name, brand=brand, category=kids[idx % len(kids)], price=price, discount_price=sale,
                    stock=stock, is_featured=featured, is_new_arrival=new,
                    description=f"{name} from {brand}. Replace this text from the admin (or use the AI description action).")
                if root_name != "Accessories":
                    p.sizes.set(sizes)
                p.colours.set(random.sample(colours, 2))
                tone = random.choice(TONES)
                for key, label in ProductImage.LABELS:
                    pi = ProductImage(product=p, label=key)
                    pi.image.save(f"{p.slug}-{key}.jpg", make_image(name, tone=tone, sub=label), save=False)
                    pi.save()
                self.stdout.write(f"  + {name}")

        if not Promotion.objects.exists():
            def promo(placement, title, order=0, **kw):
                pr = Promotion(placement=placement, title=title, order=order, **kw)
                size = (1000, 1200) if placement == "hero" else (700, 900) if placement == "hero_secondary" \
                    else (700, 700) if placement == "card" else (1800, 700)
                pr.image.save(f"{placement}-{order}.jpg", make_image(title, size=size, sub="Replace in admin"), save=False)
                pr.save()

            promo("hero", "The new season edit", kicker="Autumn / Winter",
                  text="Discover your style. Define your identity. Explore our latest collections.",
                  button_label="SHOP COLLECTION", link_url="/shop/?new=1")
            promo("hero_secondary", "Layered knitwear", link_url="/shop/women/")
            promo("card", "Summer Collection", 1, kicker="Men's collections", text="Light linen and easy cotton.", link_url="/shop/men/")
            promo("card", "Everyday Essentials", 2, kicker="Basics", text="The pieces you reach for first.", link_url="/shop/essentials/")
            promo("card", "Exclusive Deals", 3, kicker="Flash sale", text="Up to 40% off this week.", link_url="/shop/?sale=1")
            promo("banner", "Winter layers, up to 30% off", kicker="Limited time",
                  text="Coats, knitwear and scarves chosen for the cold months.",
                  button_label="Shop the sale", link_url="/shop/?sale=1")
        self.stdout.write(self.style.SUCCESS("Demo data ready."))
