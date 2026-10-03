"""Import Sheets CSV exports into a new, empty database after full validation."""
import argparse
import csv
from collections import defaultdict
from pathlib import Path
from .core import connect, quantity, format_quantity

# Explicit resolutions of discrepancies in Adam's original sheets.
# These apply only to the private import and never alter the reusable sample.
UNIT_RESOLUTIONS = {"onion": "", "lettuce": "bag", "rice": "cup"}


def read(path, expected):
    with open(path, encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not expected.issubset(reader.fieldnames or []):
            raise ValueError(f"{path}: missing columns {sorted(expected - set(reader.fieldnames or []))}")
        return list(reader)


def prepare(meals_path, ingredients_path, resolutions=None):
    resolutions = UNIT_RESOLUTIONS if resolutions is None else resolutions
    meals = read(meals_path, {"Meal"})
    ingredients = read(ingredients_path, {"Meal", "Ingredient", "Quantity", "Measurement"})
    names, item_names, units, entries = {}, {}, defaultdict(set), []
    for line, row in enumerate(meals, 2):
        name = row["Meal"].strip()
        if not name or name.casefold() in names:
            raise ValueError(f"Meals row {line}: empty or duplicate group name: {name!r}")
        names[name.casefold()] = name
    for line, row in enumerate(ingredients, 2):
        group, item = row["Meal"].strip(), row["Ingredient"].strip()
        if group.casefold() not in names or not item:
            raise ValueError(f"Ingredients row {line}: unknown group or blank item")
        try:
            amount = format_quantity(quantity(row["Quantity"]))
        except ValueError as exc:
            raise ValueError(f"Ingredients row {line}: {exc}") from exc
        key = item.casefold()
        item_names.setdefault(key, item)
        units[key].add(row["Measurement"].strip())
        entries.append((names[group.casefold()], key, amount))
    conflicts = {item: sorted(found) for item, found in units.items() if len(found) > 1}
    unresolved = {item: found for item, found in conflicts.items() if item not in resolutions}
    if unresolved:
        raise ValueError(f"Conflicting item units (resolve before import): {unresolved}")
    final_units = {key: resolutions[key] if key in conflicts else next(iter(found))
                   for key, found in units.items()}
    if len({(group.casefold(), item) for group, item, _ in entries}) != len(entries):
        raise ValueError("Duplicate item within a group; resolve before import")
    return list(names.values()), item_names, final_units, entries, conflicts


def import_files(database, meals, ingredients):
    groups, item_names, units, entries, conflicts = prepare(meals, ingredients)
    if Path(database).exists():
        raise FileExistsError("Import only into a new database; back up and remove the existing file first")
    conn = connect(database)
    try:
        with conn:
            for order, group in enumerate(groups):
                conn.execute("INSERT INTO groups(name,sort_order) VALUES(?,?)", (group, order))
            for key, item in item_names.items():
                conn.execute("INSERT INTO items(name,unit) VALUES(?,?)", (item, units[key]))
            group_ids = {r["name"].casefold(): r["id"] for r in conn.execute("SELECT id,name FROM groups")}
            item_ids = {r["name"].casefold(): r["id"] for r in conn.execute("SELECT id,name FROM items")}
            for order, (group, key, amount) in enumerate(entries):
                conn.execute("INSERT INTO group_items(group_id,item_id,quantity,sort_order) VALUES(?,?,?,?)",
                             (group_ids[group.casefold()], item_ids[key], amount, order))
    finally:
        conn.close()
    return len(groups), len(item_names), len(entries), conflicts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meals_csv")
    parser.add_argument("ingredients_csv")
    parser.add_argument("database", help="Path to a NEW SQLite database")
    args = parser.parse_args()
    result = import_files(args.database, args.meals_csv, args.ingredients_csv)
    print(f"Imported {result[0]} groups, {result[1]} items and {result[2]} group items")
    if result[3]:
        print("Unit resolutions:", result[3], "=>", UNIT_RESOLUTIONS)


if __name__ == "__main__":
    main()
