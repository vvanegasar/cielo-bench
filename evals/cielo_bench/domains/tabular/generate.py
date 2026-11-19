"""Deterministic generator of the synthetic distributor database (SQLite).

The company, its customers, products and figures are fictional. Given the seed, the
generator always produces the same rows on any platform and Python version:

* the only source of randomness is ``random.Random(seed).random()``, the one method whose
  sequence Python guarantees across versions; integers, choices and shuffles are derived
  from it here, not taken from ``randint``/``choice``/``shuffle``;
* money is computed in integer cents and only divided by 100 when written;
* no transcendental functions (their last bit can differ between C libraries).

The file is written with a fixed page size, in one transaction, in primary-key order,
then compacted with VACUUM, so the same SQLite version writes the same bytes. Across
SQLite versions the bytes can differ (the header records the library version), so the
identity of the data is the **content hash**: SHA-256 over the DDL and every row in
primary-key order. Both hashes are recorded in the manifest and in the golden set.

Realism built in: monthly seasonality (December peak, January dip), weekly patterns,
growth, quarterly shocks, price increases each January, segment-specific baskets and
discounts, cancellations, returns (voided invoices), late and partial payments, overdue
invoices, stock-outs, discontinued and newly launched products, and missing values in
documented columns.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .schema import (
    AS_OF,
    DB_VERSION,
    PAYMENT_METHODS,
    REGIONS,
    SEED,
    SEGMENTS,
    SNAPSHOT_INFO,
    START,
    TABLES,
    WAREHOUSES,
    indexes_ddl,
    schema_ddl,
)

GENERATOR_VERSION = "1"


class Rng:
    """Deterministic helpers built only on ``random.Random.random()``."""

    def __init__(self, seed: str):
        import random

        self._random = random.Random(seed).random

    def u(self) -> float:
        return self._random()

    def uniform(self, a: float, b: float) -> float:
        return a + (b - a) * self._random()

    def int(self, a: int, b: int) -> int:
        """Integer in [a, b], both inclusive."""
        return a + int(self._random() * (b - a + 1))

    def chance(self, p: float) -> bool:
        return self._random() < p

    def choice(self, seq):
        return seq[int(self._random() * len(seq))]

    def weighted(self, items, weights):
        cum, total = [], 0.0
        for w in weights:
            total += w
            cum.append(total)
        return items[min(len(items) - 1, bisect.bisect_right(cum, self._random() * total))]

    def shuffle(self, items: list) -> list:
        out = list(items)
        for i in range(len(out) - 1, 0, -1):
            j = int(self._random() * (i + 1))
            out[i], out[j] = out[j], out[i]
        return out

    def noise(self) -> float:
        """Approximately standard normal (sum of three uniforms), bounded in [-3, 3]."""
        return 2.0 * (self._random() + self._random() + self._random() - 1.5)


# --------------------------------------------------------------------------- catalogue
# (name and pack, list price in USD for 2024). Prices rise 4 % on 2025-01-01 and 5 % on
# 2026-01-01. Names are generic product descriptions, not brands.
CATALOG: dict[str, tuple[str, list[tuple[str, float]]]] = {
    "Beverages": (
        "BEV",
        [
            ("Agua sin gas 600 ml x24", 7.90),
            ("Agua con gas 600 ml x24", 8.60),
            ("Gaseosa cola 1.5 L x12", 13.20),
            ("Gaseosa limón 1.5 L x12", 12.80),
            ("Gaseosa naranja 400 ml x24", 11.40),
            ("Jugo de naranja 1 L x12", 15.60),
            ("Jugo de mango 1 L x12", 14.90),
            ("Jugo de mora 200 ml x24", 9.80),
            ("Té helado de limón 500 ml x24", 16.80),
            ("Bebida energética 250 ml x24", 24.50),
            ("Bebida hidratante 500 ml x12", 10.90),
            ("Café molido 500 g x12", 46.80),
            ("Café instantáneo 170 g x12", 52.40),
            ("Chocolate de mesa 500 g x10", 27.00),
            ("Malta 330 ml x24", 12.60),
            ("Agua saborizada 1 L x12", 9.90),
            ("Kombucha de jengibre 330 ml x12", 21.60),
            ("Leche de almendras 1 L x12", 28.80),
            ("Té verde 20 sobres x24", 31.20),
            ("Aromática de frutos rojos 20 sobres x24", 18.00),
            ("Jugo de manzana 200 ml x24", 10.20),
            ("Gaseosa sin azúcar 1.5 L x12", 13.50),
        ],
    ),
    "Snacks": (
        "SNK",
        [
            ("Papas fritas clásicas 45 g x24", 11.80),
            ("Papas fritas de limón 45 g x24", 11.80),
            ("Platanitos 40 g x24", 10.60),
            ("Maní salado 50 g x24", 9.40),
            ("Mezcla de frutos secos 100 g x12", 19.80),
            ("Galletas de avena 300 g x12", 17.40),
            ("Galletas de chocolate 250 g x12", 16.20),
            ("Galletas saladas 9 tacos x10", 14.50),
            ("Barra de cereal 25 g x48", 15.80),
            ("Chocolatina 30 g x48", 18.70),
            ("Gomitas surtidas 100 g x24", 13.90),
            ("Crispetas de mantequilla 80 g x24", 12.30),
            ("Tostadas integrales 150 g x12", 11.20),
            ("Rosquitas de queso 40 g x24", 10.80),
            ("Chicharrón 30 g x24", 13.40),
            ("Wafer de vainilla 25 g x48", 14.60),
            ("Turrón de maní 25 g x48", 12.90),
            ("Uvas pasas 100 g x24", 15.10),
            ("Pretzels 120 g x12", 13.70),
            ("Tortillas de maíz 150 g x12", 12.10),
        ],
    ),
    "Dairy": (
        "DAI",
        [
            ("Leche entera 1 L x12", 11.60),
            ("Leche deslactosada 1 L x12", 13.20),
            ("Leche descremada 1 L x12", 12.10),
            ("Yogur de fresa 200 g x24", 17.80),
            ("Yogur griego natural 150 g x24", 22.60),
            ("Kumis 1 L x12", 14.40),
            ("Queso campesino 500 g x10", 26.50),
            ("Queso mozzarella 1 kg x6", 34.80),
            ("Mantequilla con sal 250 g x20", 31.00),
            ("Crema de leche 200 ml x24", 19.20),
            ("Arequipe 500 g x12", 21.90),
            ("Leche en polvo 400 g x12", 38.40),
            ("Queso crema 230 g x12", 20.70),
            ("Bebida láctea de chocolate 200 ml x24", 15.30),
            ("Avena líquida 1 L x12", 13.80),
            ("Margarina 500 g x12", 16.40),
            ("Queso parmesano rallado 100 g x12", 24.90),
            ("Yogur bebible de mora 1 L x12", 18.60),
            ("Leche condensada 395 g x24", 29.70),
            ("Cuajada 400 g x10", 19.50),
        ],
    ),
    "Pantry": (
        "PAN",
        [
            ("Arroz blanco 1 kg x25", 27.50),
            ("Arroz integral 1 kg x12", 19.20),
            ("Lentejas 500 g x24", 21.60),
            ("Fríjol rojo 500 g x24", 26.40),
            ("Garbanzos 500 g x24", 23.80),
            ("Pasta spaghetti 500 g x24", 18.70),
            ("Pasta conchitas 250 g x24", 11.90),
            ("Aceite de girasol 1 L x12", 29.40),
            ("Aceite de oliva 500 ml x12", 64.80),
            ("Azúcar blanca 1 kg x25", 24.30),
            ("Panela 500 g x24", 16.80),
            ("Sal refinada 1 kg x25", 9.60),
            ("Harina de trigo 1 kg x25", 21.20),
            ("Harina de maíz precocida 1 kg x24", 25.90),
            ("Atún en aceite 170 g x48", 71.50),
            ("Sardinas en salsa de tomate 425 g x24", 38.20),
            ("Salsa de tomate 400 g x24", 22.70),
            ("Mayonesa 400 g x24", 27.30),
            ("Avena en hojuelas 500 g x24", 20.40),
            ("Cereal de maíz 500 g x12", 26.10),
            ("Mermelada de fresa 300 g x24", 25.60),
            ("Caldo de gallina 12 cubos x24", 17.90),
        ],
    ),
    "Cleaning": (
        "CLN",
        [
            ("Detergente en polvo 1 kg x18", 32.40),
            ("Detergente líquido 2 L x6", 27.60),
            ("Jabón en barra 300 g x50", 38.50),
            ("Lavaloza en crema 450 g x24", 26.80),
            ("Lavaloza líquido 750 ml x12", 19.70),
            ("Blanqueador 2 L x6", 11.40),
            ("Desinfectante de lavanda 1 L x12", 16.90),
            ("Limpiavidrios 500 ml x12", 18.30),
            ("Suavizante de ropa 2 L x6", 21.50),
            ("Esponjas doble uso x12", 9.80),
            ("Bolsas de basura grandes x10 x20", 23.40),
            ("Guantes de caucho talla M x24", 28.60),
            ("Ambientador en aerosol 400 ml x12", 30.20),
            ("Cera para pisos 1 L x12", 25.80),
            ("Limpiador multiusos 1 L x12", 17.60),
            ("Trapeador de microfibra x12", 41.30),
            ("Escoba plástica x12", 36.90),
            ("Alcohol antiséptico 700 ml x12", 22.10),
            ("Quitagrasa 500 ml x12", 20.80),
            ("Paños de limpieza x5 x24", 24.70),
        ],
    ),
    "Personal care": (
        "PER",
        [
            ("Champú 400 ml x12", 34.80),
            ("Acondicionador 400 ml x12", 36.20),
            ("Jabón de tocador 110 g x36", 27.40),
            ("Jabón líquido de manos 1 L x12", 29.90),
            ("Crema dental 100 ml x36", 48.60),
            ("Cepillo dental medio x24", 26.40),
            ("Enjuague bucal 500 ml x12", 39.50),
            ("Desodorante en barra 50 g x24", 52.80),
            ("Crema corporal 400 ml x12", 41.70),
            ("Protector solar FPS 50 120 ml x12", 88.20),
            ("Toallas higiénicas x10 x24", 37.60),
            ("Pañales etapa 3 x30 x4", 46.90),
            ("Pañitos húmedos x100 x12", 31.30),
            ("Gel antibacterial 500 ml x12", 27.80),
            ("Afeitadoras desechables x3 x24", 33.50),
            ("Algodón 100 g x24", 21.40),
            ("Copitos x150 x24", 19.60),
            ("Talco para pies 120 g x12", 23.90),
            ("Champú infantil 400 ml x12", 38.70),
            ("Crema para peinar 300 ml x12", 30.60),
        ],
    ),
    "Paper goods": (
        "PAP",
        [
            ("Papel higiénico doble hoja x12 x4", 26.80),
            ("Papel higiénico institucional x6 x2", 22.40),
            ("Toallas de cocina x3 x8", 18.90),
            ("Servilletas x300 x12", 21.60),
            ("Pañuelos faciales x90 x24", 29.40),
            ("Vasos desechables 7 oz x50 x20", 24.80),
            ("Platos desechables x20 x30", 27.20),
            ("Papel aluminio 7 m x24", 31.50),
            ("Papel film 30 m x12", 19.30),
            ("Bolsas para alimentos x50 x24", 22.70),
            ("Toallas de manos interfoliadas x150 x20", 33.60),
            ("Servilletas de lujo x100 x24", 25.10),
            ("Manteles desechables x12", 14.20),
            ("Cucharas desechables x50 x20", 16.40),
            ("Tenedores desechables x50 x20", 16.40),
            ("Bandejas de icopor x25 x20", 21.80),
            ("Contenedores para llevar x50 x10", 28.90),
            ("Pitillos x100 x24", 12.60),
            ("Rollo de papel kraft 50 m x4", 34.20),
            ("Papel parafinado x25 x12", 15.70),
        ],
    ),
}

# Category mix of each segment's baskets (weights).
SEGMENT_CATEGORY_MIX = {
    "retail": {
        "Beverages": 0.22,
        "Snacks": 0.18,
        "Dairy": 0.14,
        "Pantry": 0.20,
        "Cleaning": 0.10,
        "Personal care": 0.09,
        "Paper goods": 0.07,
    },
    "horeca": {
        "Beverages": 0.30,
        "Snacks": 0.08,
        "Dairy": 0.20,
        "Pantry": 0.24,
        "Cleaning": 0.07,
        "Personal care": 0.01,
        "Paper goods": 0.10,
    },
    "pharmacy": {
        "Beverages": 0.14,
        "Snacks": 0.10,
        "Dairy": 0.03,
        "Pantry": 0.02,
        "Cleaning": 0.10,
        "Personal care": 0.46,
        "Paper goods": 0.15,
    },
    "institutional": {
        "Beverages": 0.10,
        "Snacks": 0.04,
        "Dairy": 0.03,
        "Pantry": 0.16,
        "Cleaning": 0.32,
        "Personal care": 0.08,
        "Paper goods": 0.27,
    },
}
SEGMENT_SHARE = {"retail": 0.45, "horeca": 0.25, "pharmacy": 0.15, "institutional": 0.15}
REGION_SHARE = {"Centro": 0.32, "Norte": 0.22, "Sur": 0.18, "Oriente": 0.16, "Occidente": 0.12}
SEGMENT_TERMS = {
    "retail": ((30, 0.7), (15, 0.3)),
    "horeca": ((15, 0.5), (30, 0.5)),
    "pharmacy": ((45, 0.6), (30, 0.4)),
    "institutional": ((60, 0.7), (45, 0.3)),
}
SEGMENT_DISCOUNT = {
    "retail": ((0, 0.5), (2, 0.3), (5, 0.2)),
    "horeca": ((0, 0.4), (3, 0.4), (5, 0.2)),
    "pharmacy": ((2, 0.4), (5, 0.4), (8, 0.2)),
    "institutional": ((5, 0.4), (8, 0.4), (10, 0.2)),
}
SEGMENT_TYPES = {
    "retail": ("Market", "Minimarket", "Supermarket", "Grocers", "Store", "Express"),
    "horeca": ("Bistro", "Restaurant", "Hotel", "Bakery", "Deli", "Grill"),
    "pharmacy": ("Pharmacy", "Drugstore"),
    "institutional": ("School", "Clinic", "Club", "Academy"),
}

# Monthly seasonality and weekday pattern of the number of orders.
SEASON = {1: 0.86, 2: 0.90, 3: 1.00, 4: 0.96, 5: 1.02, 6: 1.04, 7: 0.98, 8: 1.00, 9: 0.95, 10: 1.05, 11: 1.14, 12: 1.30}
WEEKDAY = (1.22, 1.12, 1.04, 1.04, 1.14, 0.38, 0.06)  # Monday .. Sunday
BASE_ORDERS_PER_DAY = 7.4
GROWTH_PER_YEAR = 0.09
PRICE_STEPS = ((date(2025, 1, 1), 104), (date(2026, 1, 1), 105))  # percent of the previous price

N_CUSTOMERS = 240
SYLLABLES = (
    "ba",
    "be",
    "bo",
    "ca",
    "ce",
    "co",
    "da",
    "de",
    "di",
    "do",
    "fa",
    "fe",
    "ga",
    "go",
    "la",
    "le",
    "li",
    "lo",
    "lu",
    "ma",
    "me",
    "mi",
    "mo",
    "na",
    "ne",
    "ni",
    "no",
    "pa",
    "pe",
    "po",
    "ra",
    "re",
    "ri",
    "ro",
    "sa",
    "se",
    "si",
    "so",
    "ta",
    "te",
    "ti",
    "to",
    "va",
    "ve",
    "vi",
    "za",
    "zo",
    "qui",
    "gue",
    "tal",
    "mar",
    "ven",
    "dor",
    "lin",
)
ENDINGS = ("", "", "n", "r", "l", "s")
# Generated roots that are ordinary words or well-known names are skipped.
NAME_BLOCKLIST = frozenset(
    {
        "corona",
        "paloma",
        "sabana",
        "camino",
        "molino",
        "bonito",
        "saludo",
        "tomate",
        "venado",
        "casino",
        "domino",
        "pepino",
        "camisa",
        "maleta",
        "zapato",
        "boleta",
        "galleta",
        "mariposa",
        "colina",
        "medalla",
        "palomar",
        "comida",
        "gordo",
        "falda",
        "lunares",
        "pinata",
        "tortuga",
        "marina",
        "carola",
        "malibu",
        "salami",
        "bikini",
        "tequila",
        "salsa",
        "pasta",
        "lasana",
        "pelota",
        "patata",
        "patatas",
        "panela",
        "canela",
        "manzana",
        "naranja",
        "parador",
    }
)


def _cents(amount: float) -> int:
    return round(amount * 100)


def _round_div(numerator: int, denominator: int) -> int:
    """Integer division rounded half up (all values here are non-negative)."""
    return (2 * numerator + denominator) // (2 * denominator)


def _days(a: date, b: date) -> int:
    return (b - a).days


@dataclass
class Customer:
    customer_id: int
    name: str
    segment: str
    region: str
    email: str | None
    credit_limit: float | None
    payment_terms_days: int
    created_on: date
    churn_on: date | None
    weight: float
    size: float
    discount_pct: int
    payer: str  # punctual | late | chronic


@dataclass
class Product:
    product_id: int
    sku: str
    name: str
    category: str | None
    true_category: str
    price_cents: dict[int, int]  # epoch -> list price
    unit_cost: float | None
    reorder_level: int
    is_active: int
    launch_on: date
    discontinued_on: date | None
    popularity: float
    base_qty: int


@dataclass
class Dataset:
    customers: list[Customer] = field(default_factory=list)
    products: list[Product] = field(default_factory=list)
    orders: list[tuple] = field(default_factory=list)  # (id, customer, date, status, channel, ship)
    items: list[tuple] = field(default_factory=list)  # (id, order, product, qty, unit_cents, disc)
    invoices: list[tuple] = field(default_factory=list)  # (id, number, order, issue, due, cents, status)
    payments: list[tuple] = field(default_factory=list)  # (id, invoice, date, cents, method)
    inventory: list[tuple] = field(default_factory=list)  # (product, warehouse, qty, counted)
    item_cents: dict[int, int] = field(default_factory=dict)  # order_id -> invoiced cents


def _customer_names(rng: Rng, n: int) -> list[str]:
    names: list[str] = []
    seen_roots: set[str] = set()
    while len(names) < n:
        root = rng.choice(SYLLABLES) + rng.choice(SYLLABLES) + rng.choice(SYLLABLES)
        ending = rng.choice(ENDINGS)
        if root[-1] in "aeiou":  # no endings after a consonant ("-dorr", "-tall")
            root += ending
        if len(root) < 5 or len(root) > 10 or root in NAME_BLOCKLIST or root in seen_roots:
            continue
        seen_roots.add(root)
        names.append(root.capitalize())
    return names


def make_customers(rng: Rng) -> list[Customer]:
    roots = _customer_names(rng, N_CUSTOMERS)
    order = rng.shuffle(list(range(N_CUSTOMERS)))  # rank of each customer (0 = biggest)
    customers = []
    used_names: set[str] = set()
    for i in range(N_CUSTOMERS):
        segment = rng.weighted(SEGMENTS, [SEGMENT_SHARE[s] for s in SEGMENTS])
        region = rng.weighted(REGIONS, [REGION_SHARE[r] for r in REGIONS])
        kind = rng.choice(SEGMENT_TYPES[segment])
        name = f"{roots[i]} {kind}"
        if name in used_names:  # cannot happen (unique roots); kept as a guard
            name = f"{roots[i]} {kind} {i}"
        used_names.add(name)
        rank = order[i]
        weight = 1.0 / (rank + 4.0)
        size = 0.6 + 1.6 * (4.0 / (rank + 4.0))  # 2.2 for the biggest, ~0.6 for the smallest
        if rng.chance(0.72):
            created = date(2018, 1, 1) + timedelta(days=rng.int(0, _days(date(2018, 1, 1), date(2023, 12, 31))))
        else:
            created = START + timedelta(days=rng.int(0, _days(START, date(2026, 8, 31))))
        churn = None
        if rng.chance(0.08):
            churn = date(2024, 6, 1) + timedelta(days=rng.int(0, _days(date(2024, 6, 1), date(2026, 6, 30))))
            if churn <= created + timedelta(days=60):
                churn = None
        terms = rng.weighted([t for t, _ in SEGMENT_TERMS[segment]], [w for _, w in SEGMENT_TERMS[segment]])
        discount = rng.weighted([d for d, _ in SEGMENT_DISCOUNT[segment]], [w for _, w in SEGMENT_DISCOUNT[segment]])
        payer = rng.weighted(("punctual", "late", "chronic"), (0.60, 0.28, 0.12))
        slug = f"{roots[i].lower()}-{kind.lower()}"
        email = None if rng.chance(0.12) else f"{rng.choice(('compras', 'pedidos', 'orders'))}@{slug}.example"
        base_limit = {"retail": 6000, "horeca": 9000, "pharmacy": 12000, "institutional": 20000}[segment]
        credit = None if rng.chance(0.07) else float(500 * max(4, int(base_limit * size * rng.uniform(0.6, 1.4) / 500)))
        customers.append(
            Customer(i + 1, name, segment, region, email, credit, terms, created, churn, weight, size, discount, payer)
        )
    return customers


def _price_epochs(cents_2024: int) -> dict[int, int]:
    prices = {2024: cents_2024}
    current = cents_2024
    for when, pct in PRICE_STEPS:
        current = _round_div(current * pct, 100)
        prices[when.year] = current
    return prices


def make_products(rng: Rng) -> list[Product]:
    products = []
    pid = 0
    for c_index, (category, (prefix, items)) in enumerate(CATALOG.items()):
        ranks = rng.shuffle(list(range(len(items))))
        for k, (name, price) in enumerate(items):
            pid += 1
            sku = f"{prefix}-{1000 + 13 * (k + 1) + 3 * c_index:04d}"  # codes with gaps, like a real catalogue
            prices = _price_epochs(_cents(price))
            cost = None if rng.chance(0.05) else round(prices[2026] / 100 * rng.uniform(0.56, 0.80), 2)
            launch = START
            if rng.chance(0.07):
                launch = date(2025, 1, 1) + timedelta(days=rng.int(0, 400))
            discontinued = None
            if launch == START and rng.chance(0.06):
                discontinued = date(2025, 3, 1) + timedelta(days=rng.int(0, 450))
            products.append(
                Product(
                    product_id=pid,
                    sku=sku,
                    name=name,
                    category=None if rng.chance(0.03) else category,
                    true_category=category,
                    price_cents=prices,
                    unit_cost=cost,
                    reorder_level=0,
                    is_active=0 if discontinued else 1,
                    launch_on=launch,
                    discontinued_on=discontinued,
                    popularity=1.0 / (ranks[k] + 2.0),
                    base_qty=rng.int(2, 12),
                )
            )
    return products


def _quarter_shocks(rng: Rng) -> dict[tuple[int, int], float]:
    shocks = {}
    for year in (2024, 2025, 2026):
        for q in (1, 2, 3, 4):
            shocks[(year, q)] = 1.0 + 0.06 * rng.noise()
    return shocks


def _active(c: Customer, d: date) -> bool:
    return c.created_on <= d and (c.churn_on is None or d < c.churn_on)


def _sellable(p: Product, d: date) -> bool:
    return p.launch_on <= d and (p.discontinued_on is None or d < p.discontinued_on)


def make_orders(ds: Dataset, rng: Rng) -> None:
    shocks = _quarter_shocks(rng)
    by_category: dict[str, list[Product]] = defaultdict(list)
    for p in ds.products:
        by_category[p.true_category].append(p)
    weekday_mean = sum(WEEKDAY) / 7.0
    order_id = item_id = 0
    month_cache: dict[tuple[int, int], tuple[list[Customer], list[float]]] = {}
    d = START
    while d <= AS_OF:
        key = (d.year, d.month)
        if key not in month_cache:
            active = [c for c in ds.customers if _active(c, d)]
            month_cache[key] = (active, [c.weight for c in active])
        active, weights = month_cache[key]
        years = _days(START, d) / 365.0
        expected = (
            BASE_ORDERS_PER_DAY
            * SEASON[d.month]
            * WEEKDAY[d.weekday()]
            / weekday_mean
            * (1.0 + GROWTH_PER_YEAR * years)
            * shocks[(d.year, (d.month - 1) // 3 + 1)]
        )
        n_orders = int(expected * (0.55 + 0.9 * rng.u()) + rng.u())
        for _ in range(n_orders):
            customer = rng.weighted(active, weights)
            order_id += 1
            web_share = 0.15 + 0.20 * years / 2.75
            channel_weights = (0.62 - web_share * 0.6, 0.38 - web_share * 0.4, web_share)
            channel = rng.weighted(("field_sales", "phone", "web"), channel_weights)
            if rng.chance(0.03):
                channel = None
            if rng.chance(0.03):
                status, ship = "cancelled", None
            else:
                ship = d + timedelta(days=rng.weighted((0, 1, 2, 3), (0.35, 0.45, 0.15, 0.05)))
                transit = rng.weighted((1, 2, 3), (0.5, 0.35, 0.15))
                if ship > AS_OF:
                    status, ship = "pending", None
                elif ship + timedelta(days=transit) > AS_OF:
                    status = "shipped"
                elif rng.chance(0.025):
                    status = "returned"
                else:
                    status = "delivered"
            # basket
            mix = SEGMENT_CATEGORY_MIX[customer.segment]
            n_lines = rng.weighted((1, 2, 3, 4, 5, 6, 7, 8), (0.10, 0.16, 0.20, 0.18, 0.14, 0.10, 0.07, 0.05))
            chosen: set[int] = set()
            price_year = 2024 if d < PRICE_STEPS[0][0] else 2025 if d < PRICE_STEPS[1][0] else 2026
            lines = []
            for _line in range(n_lines * 2):  # a few extra draws to skip duplicates and unsellable items
                if len(lines) >= n_lines:
                    break
                category = rng.weighted(list(mix), list(mix.values()))
                pool = by_category[category]
                product = rng.weighted(pool, [p.popularity for p in pool])
                if product.product_id in chosen or not _sellable(product, d):
                    continue
                chosen.add(product.product_id)
                qty = max(1, int(product.base_qty * customer.size * rng.uniform(0.4, 1.6) + rng.u()))
                discount = customer.discount_pct + (5 if rng.chance(0.04) else 0)
                lines.append((product.product_id, qty, product.price_cents[price_year], discount))
            if not lines:  # every draw was a duplicate: take the first sellable product
                product = next(p for p in ds.products if _sellable(p, d))
                lines.append((product.product_id, 1, product.price_cents[price_year], customer.discount_pct))
            total = 0
            for product_id, qty, unit_cents, discount in lines:
                item_id += 1
                ds.items.append((item_id, order_id, product_id, qty, unit_cents, discount))
                total += _round_div(qty * unit_cents * (100 - discount), 100)
            # data gap: a few delivered orders never got their ship date recorded
            gap = ship is not None and status == "delivered" and rng.chance(0.008)
            ship_recorded = None if gap else ship
            ds.orders.append((order_id, customer.customer_id, d, status, channel, ship_recorded, ship))
            ds.item_cents[order_id] = total
        d += timedelta(days=1)


def make_invoices_and_payments(ds: Dataset, rng: Rng) -> None:
    customers = {c.customer_id: c for c in ds.customers}
    to_invoice = []
    for oid, cid, odate, status, _channel, _ship_recorded, ship in ds.orders:
        if status in ("cancelled", "pending"):
            continue
        issue = ship if ship is not None else odate + timedelta(days=1)
        to_invoice.append((issue, oid, cid, status))
    to_invoice.sort()
    seq: dict[int, int] = defaultdict(int)
    invoice_id = payment_id = 0
    for issue, oid, cid, status in to_invoice:
        invoice_id += 1
        seq[issue.year] += 1
        customer = customers[cid]
        due = issue + timedelta(days=customer.payment_terms_days)
        cents = ds.item_cents[oid]
        paid = 0
        if status != "returned":
            if customer.payer == "punctual":
                delay, never, partial = rng.int(-6, 7), 0.002, 0.03
            elif customer.payer == "late":
                delay, never, partial = rng.int(4, 48), 0.01, 0.09
            else:
                delay, never, partial = rng.int(15, 120), 0.10, 0.18
            if not rng.chance(never):
                first_date = max(issue + timedelta(days=1), due + timedelta(days=delay))
                if rng.chance(partial):
                    first = _round_div(cents * rng.int(30, 70), 100)
                    plan = [(first_date, first), (first_date + timedelta(days=rng.int(15, 75)), cents - first)]
                else:
                    plan = [(first_date, cents)]
                for pay_date, pay_cents in plan:
                    if pay_date > AS_OF or pay_cents <= 0:
                        continue
                    payment_id += 1
                    method = None if rng.chance(0.03) else rng.weighted(PAYMENT_METHODS, (0.65, 0.15, 0.12, 0.08))
                    ds.payments.append((payment_id, invoice_id, pay_date, pay_cents, method))
                    paid += pay_cents
        if status == "returned":
            inv_status = "void"
        elif paid >= cents:
            inv_status = "paid"
        elif due < AS_OF:
            inv_status = "overdue"
        else:
            inv_status = "open"
        number = f"INV-{issue.year}-{seq[issue.year]:05d}"
        ds.invoices.append((invoice_id, number, oid, issue, due, cents, inv_status))


def make_inventory(ds: Dataset, rng: Rng) -> None:
    """Stock on hand at the snapshot, relative to each product's reorder level.

    The reorder level is about three weeks of the product's average daily demand per
    warehouse over the last 91 days (rounded to a catalogue-friendly number). Stock is drawn
    from four bands: stock-out, below the reorder level, normal and overstock.
    """
    order_meta = {o[0]: o for o in ds.orders}
    window_start = AS_OF - timedelta(days=90)
    total: dict[int, int] = defaultdict(int)
    for _iid, oid, pid, qty, _unit, _disc in ds.items:
        order = order_meta[oid]
        if order[2] >= window_start and order[3] != "cancelled":
            total[pid] += qty
    nice = (10, 15, 20, 25, 30, 40, 50, 60, 75, 80, 100, 120, 150)
    scale = {"Centro": 1.5, "Norte": 0.85, "Sur": 1.0}
    for p in ds.products:
        per_wh_daily = total[p.product_id] / 91.0 / len(WAREHOUSES)
        target = max(10.0, per_wh_daily * 21.0)
        p.reorder_level = min(nice, key=lambda n: (abs(n - target), n))
        warehouses = WAREHOUSES if p.is_active else ("Centro",)
        for wh in warehouses:
            if not p.is_active:
                qty = rng.int(0, 30)
            else:
                band = rng.weighted(("out", "low", "normal", "high"), (0.04, 0.24, 0.52, 0.20))
                if band == "out":
                    qty = 0
                elif band == "low":
                    qty = int(p.reorder_level * rng.uniform(0.25, 0.95) + rng.u())
                elif band == "normal":
                    qty = int(p.reorder_level * scale[wh] * rng.uniform(1.1, 3.2) + rng.u())
                else:
                    qty = int(p.reorder_level * scale[wh] * rng.uniform(3.2, 7.0) + rng.u())
            counted = None if rng.chance(0.08) else AS_OF - timedelta(days=rng.int(0, 45))
            ds.inventory.append((p.product_id, wh, qty, counted))


def generate() -> Dataset:
    ds = Dataset()
    ds.customers = make_customers(Rng(f"{SEED}/customers"))
    ds.products = make_products(Rng(f"{SEED}/products"))
    make_orders(ds, Rng(f"{SEED}/orders"))
    make_invoices_and_payments(ds, Rng(f"{SEED}/payments"))
    make_inventory(ds, Rng(f"{SEED}/inventory"))
    return ds


# --------------------------------------------------------------------------- writing
def _iso(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


def _money(cents: int) -> float:
    return cents / 100


def rows(ds: Dataset) -> dict[str, list[tuple]]:
    """Rows to insert, per table, in primary-key order, with SQL-ready values."""
    out: dict[str, list[tuple]] = {
        "customers": [
            (
                c.customer_id,
                c.name,
                c.segment,
                c.region,
                c.email,
                c.credit_limit,
                c.payment_terms_days,
                _iso(c.created_on),
            )
            for c in ds.customers
        ],
        "products": [
            (
                p.product_id,
                p.sku,
                p.name,
                p.category,
                _money(p.price_cents[2026]),
                p.unit_cost,
                p.reorder_level,
                p.is_active,
            )
            for p in ds.products
        ],
        "orders": [
            (oid, cid, _iso(d), status, channel, _iso(ship_recorded))
            for (oid, cid, d, status, channel, ship_recorded, _ship) in ds.orders
        ],
        "order_items": [
            (iid, oid, pid, qty, _money(unit), disc / 100) for (iid, oid, pid, qty, unit, disc) in ds.items
        ],
        "invoices": [
            (iid, number, oid, _iso(issue), _iso(due), _money(cents), status)
            for (iid, number, oid, issue, due, cents, status) in ds.invoices
        ],
        "payments": [(pid, iid, _iso(d), _money(cents), method) for (pid, iid, d, cents, method) in ds.payments],
        "inventory": sorted((pid, wh, qty, _iso(counted)) for (pid, wh, qty, counted) in ds.inventory),
        "snapshot_info": sorted(SNAPSHOT_INFO),
    }
    return out


def write_database(path: Path, ds: Dataset | None = None) -> None:
    """Write the database to ``path`` atomically (a temporary file, then a rename)."""
    ds = ds or generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp, isolation_level=None)
    try:
        con.execute("PRAGMA page_size = 4096")
        con.execute("PRAGMA journal_mode = DELETE")
        con.execute("PRAGMA user_version = 1")
        con.executescript(schema_ddl())
        con.execute("BEGIN")
        for table in TABLES:
            data = rows(ds)[table.name]
            marks = ", ".join("?" for _ in table.columns)
            con.executemany(f"INSERT INTO {table.name} VALUES ({marks})", data)
        con.execute("COMMIT")
        con.executescript(indexes_ddl())
        con.execute("VACUUM")
    finally:
        con.close()
    os.replace(tmp, path)


# --------------------------------------------------------------------------- hashing
def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def content_sha256(path: Path) -> str:
    """SHA-256 over the DDL and every row in primary-key order (independent of file format)."""
    h = hashlib.sha256()
    h.update(schema_ddl().encode("utf-8"))
    uri = path.resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        for table in TABLES:
            cols = ", ".join(c.name for c in table.columns)
            h.update(f"\n#{table.name}({cols})\n".encode())
            for row in con.execute(f"SELECT {cols} FROM {table.name} ORDER BY {', '.join(table.primary_key)}"):
                h.update(json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                h.update(b"\n")
    finally:
        con.close()
    return h.hexdigest()


def row_counts(path: Path) -> dict[str, int]:
    uri = path.resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        return {t.name: con.execute(f"SELECT COUNT(*) FROM {t.name}").fetchone()[0] for t in TABLES}
    finally:
        con.close()


def manifest(path: Path) -> dict[str, Any]:
    return {
        "file": path.name,
        "db_version": DB_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "as_of_date": AS_OF.isoformat(),
        "bytes": path.stat().st_size,
        "file_sha256": file_sha256(path),
        "content_sha256": content_sha256(path),
        "sqlite_version": sqlite3.sqlite_version,
        "row_counts": row_counts(path),
        "note": (
            "Synthetic data: the company, customers and products are fictional. file_sha256 depends "
            "on the SQLite version that wrote the file; content_sha256 does not."
        ),
    }
